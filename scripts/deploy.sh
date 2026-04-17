#!/bin/bash

#####################################################################
# MLPipeline Kubernetes Deployment Script
# Deploys MLPipeline to kind-reunion cluster in MLPipeline namespace
#####################################################################

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
CLUSTER_NAME="kind-reunion"
NAMESPACE="MLPipeline"
DOMAIN="mlpipeline.duckdns.org"
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$( cd "$SCRIPT_DIR/.." && pwd )"

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}MLPipeline Kubernetes Deployment${NC}"
echo -e "${BLUE}========================================${NC}"

#####################################################################
# STEP 1: Verify Prerequisites
#####################################################################
echo -e "\n${YELLOW}[Step 1] Verifying prerequisites...${NC}"

# Check kubectl
if ! command -v kubectl &> /dev/null; then
    echo -e "${RED}ERROR: kubectl not found. Please install kubectl.${NC}"
    exit 1
fi

# Check helm
if ! command -v helm &> /dev/null; then
    echo -e "${RED}ERROR: Helm not found. Please install Helm 3.${NC}"
    exit 1
fi

# Verify cluster connection
if ! kubectl cluster-info &> /dev/null; then
    echo -e "${RED}ERROR: Cannot connect to Kubernetes cluster.${NC}"
    exit 1
fi

# Get current cluster context
CURRENT_CONTEXT=$(kubectl config current-context)
echo -e "${GREEN}✓ Connected to cluster: ${CURRENT_CONTEXT}${NC}"

# Verify we're on kind-reunion
if [[ "$CURRENT_CONTEXT" != *"kind-reunion"* ]]; then
    echo -e "${YELLOW}WARNING: Current context is '$CURRENT_CONTEXT', not 'kind-reunion'${NC}"
    read -p "Continue anyway? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

#####################################################################
# STEP 2: Create Namespace
#####################################################################
echo -e "\n${YELLOW}[Step 2] Creating namespace...${NC}"

if kubectl get namespace $NAMESPACE &> /dev/null; then
    echo -e "${GREEN}✓ Namespace '$NAMESPACE' already exists${NC}"
else
    kubectl create namespace $NAMESPACE
    echo -e "${GREEN}✓ Created namespace '$NAMESPACE'${NC}"
fi

# Label namespace
kubectl label namespace $NAMESPACE app.kubernetes.io/name=mlpipeline --overwrite

#####################################################################
# STEP 3: Apply Kubernetes Manifests
#####################################################################
echo -e "\n${YELLOW}[Step 3] Applying Kubernetes manifests...${NC}"

# Create service accounts and RBAC
echo "  - Applying service accounts and RBAC..."
kubectl apply -f "$PROJECT_ROOT/kubernetes/service-accounts.yaml"

# Create secrets
echo "  - Creating secrets..."
kubectl apply -f "$PROJECT_ROOT/kubernetes/postgres-secret.yaml"

# Create configmaps
echo "  - Creating configmaps..."
kubectl apply -f "$PROJECT_ROOT/kubernetes/configmap.yaml"

# Create ingress
echo "  - Creating ingress..."
kubectl apply -f "$PROJECT_ROOT/kubernetes/ingress.yaml"

echo -e "${GREEN}✓ Kubernetes manifests applied${NC}"

#####################################################################
# STEP 4: Deploy PostgreSQL
#####################################################################
echo -e "\n${YELLOW}[Step 4] Deploying PostgreSQL via Helm...${NC}"

# Add Bitnami Helm repository
helm repo add bitnami https://charts.bitnami.com/bitnami
helm repo update

# Deploy PostgreSQL
if helm list -n $NAMESPACE | grep -q "mlpipeline-postgres"; then
    echo -e "${YELLOW}  ! PostgreSQL already deployed, skipping...${NC}"
else
    echo "  - Installing PostgreSQL..."
    helm install mlpipeline-postgres bitnami/postgresql \
        --namespace $NAMESPACE \
        --set auth.username=airflow \
        --set auth.password=airflow_secure_password_change_me \
        --set auth.database=airflow \
        --set primary.persistence.enabled=true \
        --set primary.persistence.size=10Gi
    
    echo -e "${GREEN}✓ PostgreSQL deployed${NC}"
fi

# Wait for PostgreSQL to be ready
echo "  - Waiting for PostgreSQL to be ready..."
kubectl wait --for=condition=ready pod \
    -l app.kubernetes.io/name=postgresql,app.kubernetes.io/instance=mlpipeline-postgres \
    -n $NAMESPACE \
    --timeout=300s

#####################################################################
# STEP 5: Deploy Airflow via Helm
#####################################################################
echo -e "\n${YELLOW}[Step 5] Deploying Apache Airflow via Helm...${NC}"

# Add Apache Airflow Helm repository
helm repo add apache-airflow https://airflow.apache.org
helm repo update

# Deploy Airflow
if helm list -n $NAMESPACE | grep -q "mlpipeline-airflow"; then
    echo -e "${YELLOW}  ! Airflow already deployed, upgrading...${NC}"
    helm upgrade mlpipeline-airflow apache-airflow/airflow \
        -f "$PROJECT_ROOT/helm/mlpipeline-airflow/values.yaml" \
        --namespace $NAMESPACE \
        --wait
else
    echo "  - Installing Airflow..."
    helm install mlpipeline-airflow apache-airflow/airflow \
        -f "$PROJECT_ROOT/helm/mlpipeline-airflow/values.yaml" \
        --namespace $NAMESPACE \
        --wait
    
    echo -e "${GREEN}✓ Airflow deployed${NC}"
fi

#####################################################################
# STEP 6: Build and Deploy FastAPI Serving
#####################################################################
echo -e "\n${YELLOW}[Step 6] Building and deploying FastAPI serving...${NC}"

# Build FastAPI image (if docker available)
if command -v docker &> /dev/null; then
    echo "  - Building FastAPI Docker image..."
    docker build -t mlpipeline-serving:1.0.0 \
        -f "$PROJECT_ROOT/serving/Dockerfile" \
        "$PROJECT_ROOT" || echo -e "${YELLOW}  ! Docker build failed, skipping image build${NC}"
else
    echo -e "${YELLOW}  ! Docker not found, skipping image build${NC}"
fi

# Deploy FastAPI via Helm
if helm list -n $NAMESPACE | grep -q "mlpipeline-serving"; then
    echo -e "${YELLOW}  ! FastAPI already deployed, upgrading...${NC}"
    helm upgrade mlpipeline-serving "$PROJECT_ROOT/helm/mlpipeline-serving" \
        --namespace $NAMESPACE \
        --wait
else
    echo "  - Installing FastAPI serving..."
    helm install mlpipeline-serving "$PROJECT_ROOT/helm/mlpipeline-serving" \
        --namespace $NAMESPACE \
        --wait
    
    echo -e "${GREEN}✓ FastAPI serving deployed${NC}"
fi

#####################################################################
# STEP 7: Verify Deployment
#####################################################################
echo -e "\n${YELLOW}[Step 7] Verifying deployment...${NC}"

echo "  - Checking pod status..."
kubectl get pods -n $NAMESPACE

echo -e "\n  - Checking services..."
kubectl get svc -n $NAMESPACE

echo -e "\n  - Checking ingress..."
kubectl get ingress -n $NAMESPACE

#####################################################################
# STEP 8: Setup Keycloak
#####################################################################
echo -e "\n${YELLOW}[Step 8] Keycloak configuration...${NC}"

if [[ -f "$SCRIPT_DIR/setup-keycloak.sh" ]]; then
    read -p "Do you want to configure Keycloak now? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        bash "$SCRIPT_DIR/setup-keycloak.sh"
    fi
else
    echo -e "${YELLOW}  ! setup-keycloak.sh not found${NC}"
fi

#####################################################################
# Summary
#####################################################################
echo -e "\n${BLUE}========================================${NC}"
echo -e "${BLUE}Deployment Complete!${NC}"
echo -e "${BLUE}========================================${NC}"

echo -e "\n${GREEN}Services:${NC}"
echo -e "  Airflow Webserver:  ${BLUE}https://$DOMAIN/airflow${NC}"
echo -e "  FastAPI Serving:    ${BLUE}https://$DOMAIN/api${NC}"
echo -e "  Health Check:       ${BLUE}https://$DOMAIN/api/health${NC}"

echo -e "\n${GREEN}Useful Commands:${NC}"
echo "  # Port forward to Airflow webserver"
echo "  kubectl port-forward -n $NAMESPACE svc/airflow-webserver 8080:8080"
echo ""
echo "  # Port forward to FastAPI"
echo "  kubectl port-forward -n $NAMESPACE svc/mlpipeline-serving 8000:8000"
echo ""
echo "  # View Airflow logs"
echo "  kubectl logs -n $NAMESPACE -f deployment/airflow-scheduler"
echo ""
echo "  # View FastAPI logs"
echo "  kubectl logs -n $NAMESPACE -f deployment/mlpipeline-serving"
echo ""

echo -e "\n${GREEN}Next Steps:${NC}"
echo "  1. Configure Keycloak realm and OAuth clients"
echo "  2. Set up TLS certificate for $DOMAIN"
echo "  3. Upload sample data to /data/raw"
echo "  4. Trigger training DAG from Airflow UI"
echo ""

echo -e "${GREEN}✓ Deployment script completed successfully${NC}\n"
