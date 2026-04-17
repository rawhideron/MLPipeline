# Keycloak Setup Guide

Manual configuration guide for Keycloak OAuth integration with MLPipeline.

## Overview

MLPipeline uses Keycloak for OAuth2 authentication on:
- Airflow webserver
- FastAPI serving API

This guide covers:
1. Accessing Keycloak admin console
2. Creating MLPipeline realm
3. Configuring OAuth clients for Airflow and FastAPI
4. Setting up users and roles
5. Obtaining client credentials

## Access Keycloak Admin Console

```
URL: https://keycloak:8080/admin
Username: admin
Password: (your admin password)
```

## Step 1: Create MLPipeline Realm

1. Navigate to "Realms" in left sidebar
2. Click "Create" button
3. Enter realm name: `MLPipeline`
4. Click "Create"

Configure realm settings:

| Setting | Value |
|---------|-------|
| Enabled | ON |
| Display name | MLPipeline |
| Display name HTML | `<b>MLPipeline</b> - NLP ML Pipeline` |
| User Profile Enabled | ON |
| Require HTTPS | External |

## Step 2: Create OAuth2 Clients

### 2a. Airflow Webserver Client

1. In MLPipeline realm, go to "Clients"
2. Click "Create client"
3. Fill in:
   - **Client ID**: `airflow-webserver`
   - **Name**: Airflow Webserver
   - **Type**: OpenID Connect
4. Click "Next"
5. Configure "Capability config":
   - Standard flow enabled: **ON**
   - Implicit flow enabled: **OFF**
   - Direct access grants enabled: **ON**
   - Service account enabled: **ON**
6. Click "Next"
7. Configure "Login settings":
   - Root URL: `https://mlpipeline.duckdns.org/airflow`
   - Valid redirect URIs: `https://mlpipeline.duckdns.org/airflow/oauth-authorized/keycloak`
   - Valid post logout redirect URIs: `https://mlpipeline.duckdns.org/airflow`
   - Web origins: `https://mlpipeline.duckdns.org`
8. Click "Save"

Get client credentials:

1. Go to "Credentials" tab
2. Copy **Client Secret** for later use
3. The Client ID is `airflow-webserver`

### 2b. FastAPI Serving Client

1. In MLPipeline realm, go to "Clients"
2. Click "Create client"
3. Fill in:
   - **Client ID**: `mlpipeline-serving`
   - **Name**: MLPipeline Serving API
   - **Type**: OpenID Connect
4. Repeat steps 4-7 with:
   - Root URL: `https://mlpipeline.duckdns.org/api`
   - Valid redirect URIs: `https://mlpipeline.duckdns.org/api/auth/callback`
   - Valid post logout redirect URIs: `https://mlpipeline.duckdns.org/api`

Get client credentials same as above.

## Step 3: Create Roles

Navigate to "Realm Roles":

1. Click "Create role"
2. Create the following roles:

| Role Name | Description |
|-----------|-------------|
| `mlpipeline-admin` | MLPipeline Administrator |
| `mlpipeline-user` | MLPipeline Regular User |
| `data-scientist` | Data Scientist Role |
| `ml-engineer` | ML Engineer Role |

## Step 4: Create Test User

1. Go to "Users" in left sidebar
2. Click "Create user"
3. Fill in:
   - **Username**: `testuser`
   - **Email**: `testuser@mlpipeline.local`
   - **First name**: Test
   - **Last name**: User
   - **Email verified**: ON
   - **Enabled**: ON
4. Click "Create"

Set password:

1. Go to "Credentials" tab
2. Click "Set password"
3. Enter temporary password
4. Uncheck "Temporary"
5. Click "Set Password"

Assign roles:

1. Go to "Role mapping" tab
2. Assign roles:
   - `mlpipeline-admin`
   - `data-scientist`

## Step 5: Configure Mappers (Optional)

To include custom claims in JWT tokens:

1. Go to "Clients" → `airflow-webserver` → "Mappers"
2. Click "Configure a new mapper"
3. Select "User Realm Role"
4. Configure:
   - **Name**: realm roles
   - **Token claim name**: roles
   - **Claim JSON Type**: String
   - **Add to ID token**: ON
   - **Add to access token**: ON
   - **Multivalued**: ON
5. Click "Save"

Repeat for other clients as needed.

## Step 6: Update Kubernetes Secrets

Once you have client credentials, update Kubernetes secrets:

```bash
# Update Keycloak secrets with actual credentials
kubectl edit secret keycloak-serving-secret -n MLPipeline
kubectl edit secret keycloak-airflow-secret -n MLPipeline
```

Update the `client-secret` field with values from Keycloak.

## Step 7: Restart Services

Restart services to apply new Keycloak configuration:

```bash
# Restart Airflow
kubectl rollout restart deployment/airflow-webserver -n MLPipeline
kubectl rollout restart deployment/airflow-scheduler -n MLPipeline

# Restart FastAPI
kubectl rollout restart deployment/mlpipeline-serving -n MLPipeline
```

Wait for rollout:

```bash
kubectl rollout status deployment/airflow-webserver -n MLPipeline
kubectl rollout status deployment/mlpipeline-serving -n MLPipeline
```

## Verify OAuth Integration

### Test Airflow Login

1. Navigate to `https://mlpipeline.duckdns.org/airflow`
2. Should redirect to Keycloak login
3. Login with test user credentials
4. Should be redirected back to Airflow webserver

Check logs if login fails:

```bash
kubectl logs -n MLPipeline -f deployment/airflow-webserver
kubectl logs -n MLPipeline -f deployment/oauth2-proxy
```

### Test FastAPI API Access

```bash
# Get access token
TOKEN=$(curl -s -X POST \
    "https://keycloak:8080/realms/MLPipeline/protocol/openid-connect/token" \
    -H "Content-Type: application/x-www-form-urlencoded" \
    -d "client_id=mlpipeline-serving" \
    -d "client_secret=<client-secret>" \
    -d "username=testuser" \
    -d "password=<password>" \
    -d "grant_type=password" | jq -r '.access_token')

# Make API request with token
curl -X POST https://mlpipeline.duckdns.org/api/predict \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"text": "This is great!"}'
```

## Troubleshooting

### Login Redirect Loop

**Problem**: Keycloak login redirects back to login page repeatedly.

**Solution**:
1. Verify redirect URIs are correctly configured
2. Check that HTTPS is enabled
3. Verify domain DNS is working: `nslookup mlpipeline.duckdns.org`

### Invalid Client Secret

**Problem**: OAuth client secret mismatch error.

**Solution**:
1. Regenerate client secret in Keycloak
2. Update Kubernetes secret: `kubectl edit secret keycloak-serving-secret -n MLPipeline`
3. Restart affected services

### Token Verification Failed

**Problem**: JWT token verification fails in FastAPI.

**Solution**:
1. Verify Keycloak realm URL matches configuration
2. Check that `KEYCLOAK_REALM_URL` environment variable is correct
3. Ensure token audience matches client ID
4. Check OAuth middleware logs: `kubectl logs -n MLPipeline <pod-name> -f`

### User Can't Access API

**Problem**: Valid token but API returns 403 Forbidden.

**Solution**:
1. Check user has appropriate role assignments
2. Verify scope configuration in OAuth client
3. Check API authorization middleware

## Security Best Practices

1. **Change Default Passwords**: Replace all `_change_me` passwords with strong ones
2. **Enable HTTPS**: Always use TLS/SSL for OAuth flows
3. **Rotate Secrets**: Periodically regenerate client secrets
4. **Use Service Accounts**: For service-to-service OAuth authentication
5. **Audit Logs**: Enable Keycloak audit logging
6. **Rate Limiting**: Configure rate limiting on Keycloak auth endpoint
7. **Token Expiration**: Set appropriate token lifetimes:
   - Access token: 5 minutes
   - Refresh token: 24 hours
   - Realm: 30 days

## API Reference

### Get Token

```bash
curl -X POST \
    "${KEYCLOAK_URL}/realms/${REALM}/protocol/openid-connect/token" \
    -H "Content-Type: application/x-www-form-urlencoded" \
    -d "client_id=${CLIENT_ID}" \
    -d "client_secret=${CLIENT_SECRET}" \
    -d "username=${USERNAME}" \
    -d "password=${PASSWORD}" \
    -d "grant_type=password"
```

Response:

```json
{
  "access_token": "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9...",
  "expires_in": 300,
  "refresh_expires_in": 86400,
  "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "Bearer",
  "not_before_policy": 0,
  "session_state": "...",
  "scope": "openid email profile"
}
```

### Refresh Token

```bash
curl -X POST \
    "${KEYCLOAK_URL}/realms/${REALM}/protocol/openid-connect/token" \
    -H "Content-Type: application/x-www-form-urlencoded" \
    -d "client_id=${CLIENT_ID}" \
    -d "client_secret=${CLIENT_SECRET}" \
    -d "refresh_token=${REFRESH_TOKEN}" \
    -d "grant_type=refresh_token"
```

### Logout

```bash
curl -X POST \
    "${KEYCLOAK_URL}/realms/${REALM}/protocol/openid-connect/logout" \
    -H "Content-Type: application/x-www-form-urlencoded" \
    -d "client_id=${CLIENT_ID}" \
    -d "client_secret=${CLIENT_SECRET}" \
    -d "refresh_token=${REFRESH_TOKEN}"
```

## References

- [Keycloak Documentation](https://www.keycloak.org/documentation)
- [OpenID Connect Protocol](https://openid.net/specs/openid-connect-core-1_0.html)
- [OAuth 2.0 Authorization Framework](https://tools.ietf.org/html/rfc6749)

---

**Last Updated**: April 2026  
**Status**: Stable
