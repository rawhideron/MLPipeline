#!/bin/bash

#####################################################################
# Keycloak Realm and OAuth Client Setup Script
# Configures MLPipeline realm and OAuth clients in Keycloak
#####################################################################

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Configuration
NAMESPACE="MLPipeline"
REALM_NAME="MLPipeline"
KEYCLOAK_URL="${KEYCLOAK_URL:-https://keycloak:8080}"
DOMAIN="mlpipeline.duckdns.org"

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Keycloak Realm Configuration${NC}"
echo -e "${BLUE}========================================${NC}"

#####################################################################
# Step 1: Get Keycloak Admin Token
#####################################################################
echo -e "\n${YELLOW}[Step 1] Authenticating with Keycloak...${NC}"

read -p "Enter Keycloak master realm username [admin]: " KC_USER
KC_USER=${KC_USER:-admin}

read -sp "Enter Keycloak master realm password: " KC_PASSWORD
echo

# Get admin token
echo "  - Retrieving admin token..."
ADMIN_TOKEN=$(curl -s -X POST \
    "$KEYCLOAK_URL/realms/master/protocol/openid-connect/token" \
    -H "Content-Type: application/x-www-form-urlencoded" \
    -d "client_id=admin-cli" \
    -d "username=$KC_USER" \
    -d "password=$KC_PASSWORD" \
    -d "grant_type=password" | jq -r '.access_token')

if [ "$ADMIN_TOKEN" == "null" ] || [ -z "$ADMIN_TOKEN" ]; then
    echo -e "${RED}ERROR: Failed to authenticate with Keycloak${NC}"
    exit 1
fi

echo -e "${GREEN}✓ Successfully authenticated with Keycloak${NC}"

#####################################################################
# Step 2: Create MLPipeline Realm
#####################################################################
echo -e "\n${YELLOW}[Step 2] Creating MLPipeline realm...${NC}"

# Check if realm exists
EXISTING_REALM=$(curl -s "$KEYCLOAK_URL/admin/realms/$REALM_NAME" \
    -H "Authorization: Bearer $ADMIN_TOKEN" | jq -r '.realm // empty')

if [ "$EXISTING_REALM" == "$REALM_NAME" ]; then
    echo -e "${YELLOW}  ! Realm '$REALM_NAME' already exists, skipping creation${NC}"
else
    echo "  - Creating realm..."
    curl -s -X POST \
        "$KEYCLOAK_URL/admin/realms" \
        -H "Authorization: Bearer $ADMIN_TOKEN" \
        -H "Content-Type: application/json" \
        -d '{
            "realm": "'$REALM_NAME'",
            "enabled": true,
            "displayName": "MLPipeline",
            "displayNameHtml": "<b>MLPipeline</b> - NLP ML Pipeline",
            "accessCodeLifespan": 60,
            "accessCodeLifespanLogin": 1800,
            "accessCodeLifespanUserAction": 300,
            "accountTheme": "keycloak",
            "adminTheme": "keycloak",
            "emailTheme": "keycloak",
            "loginTheme": "keycloak",
            "sslRequired": "external",
            "userManagedAccessAllowed": true,
            "passwordPolicy": "length(8) and specialChars(1) and digits(1) and lowerCase(1) and upperCase(1)"
        }' > /dev/null
    
    echo -e "${GREEN}✓ Created realm '$REALM_NAME'${NC}"
fi

#####################################################################
# Step 3: Create OAuth Clients
#####################################################################
echo -e "\n${YELLOW}[Step 3] Creating OAuth clients...${NC}"

# Function to create OAuth client
create_oauth_client() {
    local CLIENT_ID=$1
    local CLIENT_NAME=$2
    local REDIRECT_URIS=$3
    
    echo "  - Creating client: $CLIENT_NAME..."
    
    # Check if client exists
    EXISTING_CLIENT=$(curl -s \
        "$KEYCLOAK_URL/admin/realms/$REALM_NAME/clients?clientId=$CLIENT_ID" \
        -H "Authorization: Bearer $ADMIN_TOKEN" | jq -r '.[0].id // empty')
    
    if [ -z "$EXISTING_CLIENT" ]; then
        curl -s -X POST \
            "$KEYCLOAK_URL/admin/realms/$REALM_NAME/clients" \
            -H "Authorization: Bearer $ADMIN_TOKEN" \
            -H "Content-Type: application/json" \
            -d '{
                "clientId": "'$CLIENT_ID'",
                "name": "'$CLIENT_NAME'",
                "enabled": true,
                "clientAuthenticationType": "client_secret_basic",
                "publicClient": false,
                "redirectUris": ['$REDIRECT_URIS'],
                "webOrigins": ["https://'$DOMAIN'"],
                "standardFlowEnabled": true,
                "implicitFlowEnabled": false,
                "directAccessGrantsEnabled": true,
                "serviceAccountsEnabled": true,
                "authorizationServicesEnabled": true,
                "attributes": {
                    "saml.assertion.signature": "false",
                    "saml.force.post.binding": "false",
                    "saml.multivalued.roles": "false",
                    "saml.encrypt": "false",
                    "saml_force_name_id_format": "false",
                    "saml.client.signature": "false",
                    "saml.authnstatement": "false"
                }
            }' > /dev/null
        
        echo -e "${GREEN}  ✓ Created client: $CLIENT_ID${NC}"
    else
        echo -e "${YELLOW}  ! Client '$CLIENT_ID' already exists${NC}"
    fi
}

# Airflow Webserver Client
create_oauth_client \
    "airflow-webserver" \
    "Airflow Webserver" \
    '"https://'$DOMAIN'/airflow/oauth-authorized/keycloak"'

# FastAPI Serving Client
create_oauth_client \
    "mlpipeline-serving" \
    "MLPipeline Serving API" \
    '"https://'$DOMAIN'/api/auth/callback"'

#####################################################################
# Step 4: Create Roles
#####################################################################
echo -e "\n${YELLOW}[Step 4] Creating roles...${NC}"

create_role() {
    local ROLE_NAME=$1
    local DESCRIPTION=$2
    
    echo "  - Creating role: $ROLE_NAME..."
    
    curl -s -X POST \
        "$KEYCLOAK_URL/admin/realms/$REALM_NAME/roles" \
        -H "Authorization: Bearer $ADMIN_TOKEN" \
        -H "Content-Type: application/json" \
        -d '{
            "name": "'$ROLE_NAME'",
            "description": "'$DESCRIPTION'",
            "composite": false,
            "clientRole": false,
            "containerId": "'$REALM_NAME'"
        }' > /dev/null 2>&1 || echo "  ! Role '$ROLE_NAME' may already exist"
}

create_role "mlpipeline-admin" "MLPipeline Administrator"
create_role "mlpipeline-user" "MLPipeline Regular User"
create_role "data-scientist" "Data Scientist Role"
create_role "ml-engineer" "ML Engineer Role"

echo -e "${GREEN}✓ Roles configured${NC}"

#####################################################################
# Step 5: Create Test User
#####################################################################
echo -e "\n${YELLOW}[Step 5] Creating test user...${NC}"

TEST_USER_PASSWORD=$(openssl rand -base64 12)

echo "  - Creating test user 'testuser'..."

curl -s -X POST \
    "$KEYCLOAK_URL/admin/realms/$REALM_NAME/users" \
    -H "Authorization: Bearer $ADMIN_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{
        "username": "testuser",
        "email": "testuser@mlpipeline.local",
        "firstName": "Test",
        "lastName": "User",
        "enabled": true,
        "emailVerified": true,
        "credentials": [{
            "type": "password",
            "value": "'$TEST_USER_PASSWORD'",
            "temporary": false
        }]
    }' > /dev/null 2>&1 || echo "  ! Test user may already exist"

echo -e "${GREEN}✓ Test user created with password: $TEST_USER_PASSWORD${NC}"

#####################################################################
# Step 6: Configure Client Scopes and Protocol Mappers
#####################################################################
echo -e "\n${YELLOW}[Step 6] Configuring client scopes...${NC}"

# Get client secrets
echo "  - Retrieving client secrets..."

AIRFLOW_CLIENT_ID=$(curl -s \
    "$KEYCLOAK_URL/admin/realms/$REALM_NAME/clients?clientId=airflow-webserver" \
    -H "Authorization: Bearer $ADMIN_TOKEN" | jq -r '.[0].id')

SERVING_CLIENT_ID=$(curl -s \
    "$KEYCLOAK_URL/admin/realms/$REALM_NAME/clients?clientId=mlpipeline-serving" \
    -H "Authorization: Bearer $ADMIN_TOKEN" | jq -r '.[0].id')

if [ ! -z "$AIRFLOW_CLIENT_ID" ]; then
    AIRFLOW_SECRET=$(curl -s \
        "$KEYCLOAK_URL/admin/realms/$REALM_NAME/clients/$AIRFLOW_CLIENT_ID/client-secret" \
        -H "Authorization: Bearer $ADMIN_TOKEN" | jq -r '.value')
fi

if [ ! -z "$SERVING_CLIENT_ID" ]; then
    SERVING_SECRET=$(curl -s \
        "$KEYCLOAK_URL/admin/realms/$REALM_NAME/clients/$SERVING_CLIENT_ID/client-secret" \
        -H "Authorization: Bearer $ADMIN_TOKEN" | jq -r '.value')
fi

#####################################################################
# Summary
#####################################################################
echo -e "\n${BLUE}========================================${NC}"
echo -e "${BLUE}Keycloak Configuration Complete!${NC}"
echo -e "${BLUE}========================================${NC}"

echo -e "\n${GREEN}Realm Details:${NC}"
echo "  Realm Name: $REALM_NAME"
echo "  Realm URL:  $KEYCLOAK_URL/realms/$REALM_NAME"

echo -e "\n${GREEN}OAuth Client Credentials:${NC}"
echo ""
echo "  Airflow Webserver:"
echo "    Client ID:     airflow-webserver"
if [ ! -z "$AIRFLOW_SECRET" ]; then
    echo "    Client Secret: $AIRFLOW_SECRET"
fi
echo "    Redirect URI:  https://$DOMAIN/airflow/oauth-authorized/keycloak"
echo ""
echo "  FastAPI Serving:"
echo "    Client ID:     mlpipeline-serving"
if [ ! -z "$SERVING_SECRET" ]; then
    echo "    Client Secret: $SERVING_SECRET"
fi
echo "    Redirect URI:  https://$DOMAIN/api/auth/callback"

echo -e "\n${GREEN}Test User Credentials:${NC}"
echo "  Username: testuser"
echo "  Password: $TEST_USER_PASSWORD"

echo -e "\n${GREEN}Next Steps:${NC}"
echo "  1. Update Kubernetes secrets with OAuth client credentials"
echo "  2. Restart Airflow and FastAPI pods"
echo "  3. Access https://$DOMAIN/airflow and log in with OAuth"
echo ""

echo -e "${GREEN}✓ Keycloak setup completed successfully${NC}\n"
