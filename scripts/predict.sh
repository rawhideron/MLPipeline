#!/bin/bash

#####################################################################
# Real-time Sentiment Prediction CLI
# Gets a Keycloak access token and calls the live /api/predict
# endpoint on the MLPipeline serving API for immediate feedback,
# instead of routing text through the mlpipeline_inference batch DAG.
#####################################################################

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

NAMESPACE="mlpipeline"
API_URL="https://mlpipeline.duckdns.org/api/predict"

if [[ -z "$1" ]]; then
    echo -e "${RED}Usage: $0 \"<text to classify>\"${NC}"
    exit 1
fi
TEXT="$1"

if ! command -v kubectl &> /dev/null; then
    echo -e "${RED}ERROR: kubectl not found.${NC}"
    exit 1
fi

#####################################################################
# STEP 1: Pull Keycloak client config + secret from the cluster
#####################################################################
echo -e "${YELLOW}[Step 1] Fetching Keycloak client config...${NC}"

REALM_URL=$(kubectl get configmap mlpipeline-config -n "$NAMESPACE" -o jsonpath='{.data.KEYCLOAK_REALM_URL}')
CLIENT_ID=$(kubectl get configmap mlpipeline-config -n "$NAMESPACE" -o jsonpath='{.data.OAUTH_CLIENT_ID}')
CLIENT_SECRET=$(kubectl get secret keycloak-serving-secret -n "$NAMESPACE" -o jsonpath='{.data.client-secret}' | base64 -d)
echo -e "${GREEN}✓ Client config pulled (client_id=${CLIENT_ID})${NC}"

#####################################################################
# STEP 2: Get an access token (Keycloak client-credentials flow)
#####################################################################
echo -e "\n${YELLOW}[Step 2] Requesting access token...${NC}"

TOKEN_RESPONSE=$(curl -sf -X POST \
    "${REALM_URL}/protocol/openid-connect/token" \
    -H "Content-Type: application/x-www-form-urlencoded" \
    -d "client_id=${CLIENT_ID}" \
    -d "client_secret=${CLIENT_SECRET}" \
    -d "grant_type=client_credentials")

TOKEN=$(echo "$TOKEN_RESPONSE" | python3 -c "import sys, json; print(json.load(sys.stdin)['access_token'])")
echo -e "${GREEN}✓ Token acquired${NC}"

#####################################################################
# STEP 3: Call /predict
#####################################################################
echo -e "\n${YELLOW}[Step 3] Calling ${API_URL}...${NC}"

curl -sf -X POST "$API_URL" \
    -H "Authorization: Bearer ${TOKEN}" \
    -H "Content-Type: application/json" \
    -d "$(python3 -c "import json, sys; print(json.dumps({'text': sys.argv[1]}))" "$TEXT")" \
    | python3 -m json.tool
