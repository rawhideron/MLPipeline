#!/bin/bash

#####################################################################
# MLPipeline Cleanup Script
# Removes all MLPipeline resources from Kubernetes cluster
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

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}MLPipeline Cleanup${NC}"
echo -e "${BLUE}========================================${NC}"

# Confirm deletion
echo -e "\n${RED}WARNING: This will delete all MLPipeline resources!${NC}"
read -p "Are you sure you want to continue? Type 'yes' to confirm: " -r
echo
if [[ ! $REPLY == "yes" ]]; then
    echo "Cleanup cancelled."
    exit 0
fi

echo -e "\n${YELLOW}Removing MLPipeline resources...${NC}"

# Delete Helm releases
echo "  - Uninstalling Helm releases..."
helm uninstall mlpipeline-serving -n $NAMESPACE 2>/dev/null || true
helm uninstall mlpipeline-airflow -n $NAMESPACE 2>/dev/null || true
helm uninstall mlpipeline-postgres -n $NAMESPACE 2>/dev/null || true

# Delete Kubernetes resources
echo "  - Deleting Kubernetes resources..."
kubectl delete -n $NAMESPACE \
    configmaps,secrets,serviceaccounts,roles,rolebindings,services,ingress \
    -l app.kubernetes.io/name=mlpipeline \
    2>/dev/null || true

# Delete persistent volume claims
echo "  - Deleting persistent volume claims..."
kubectl delete -n $NAMESPACE pvc \
    -l app.kubernetes.io/name=mlpipeline \
    2>/dev/null || true

# Delete namespace
echo "  - Deleting namespace..."
kubectl delete namespace $NAMESPACE 2>/dev/null || true

echo -e "\n${GREEN}✓ Cleanup completed${NC}"
echo -e "${YELLOW}Note: Persistent volumes may need to be manually deleted${NC}\n"
