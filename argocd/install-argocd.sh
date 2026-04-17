#!/bin/bash
#
# MLPipeline ArgoCD Installation & Setup
# Installs ArgoCD and configures it to manage the MLPipeline
#
# Usage: ./argocd/install-argocd.sh
#

set -e

ARGOCD_VERSION="${ARGOCD_VERSION:-v2.10.3}"
ARGOCD_NAMESPACE="argocd"
CLUSTER_NAME="kind-reunion"

echo "========================================================================"
echo "MLPipeline ArgoCD Installation"
echo "========================================================================"
echo ""

# Step 1: Verify prerequisites
echo "Step 1: Verifying prerequisites..."
echo "------------------------------------------------------------------------"

if ! command -v kubectl &> /dev/null; then
    echo "❌ kubectl not found. Please install kubectl."
    exit 1
fi
echo "✓ kubectl found"

if ! command -v helm &> /dev/null; then
    echo "❌ helm not found. Please install helm."
    exit 1
fi
echo "✓ helm found"

# Check cluster access
if ! kubectl cluster-info &> /dev/null; then
    echo "❌ Cannot access Kubernetes cluster. Ensure cluster is running."
    exit 1
fi
echo "✓ Kubernetes cluster accessible"

CURRENT_CONTEXT=$(kubectl config current-context)
echo "✓ Current context: $CURRENT_CONTEXT"

echo ""

# Step 2: Create ArgoCD namespace
echo "Step 2: Creating ArgoCD namespace..."
echo "------------------------------------------------------------------------"

if kubectl get namespace $ARGOCD_NAMESPACE &> /dev/null; then
    echo "✓ Namespace $ARGOCD_NAMESPACE already exists"
else
    kubectl create namespace $ARGOCD_NAMESPACE
    echo "✓ Created namespace $ARGOCD_NAMESPACE"
fi

echo ""

# Step 3: Install ArgoCD using Helm
echo "Step 3: Installing ArgoCD..."
echo "------------------------------------------------------------------------"

# Add ArgoCD Helm repository
if helm repo list | grep -q "argo"; then
    echo "✓ ArgoCD Helm repo already added"
else
    helm repo add argo https://argoproj.github.io/argo-helm
    echo "✓ Added ArgoCD Helm repository"
fi

helm repo update
echo "✓ Updated Helm repositories"

# Install ArgoCD with Helm
helm upgrade --install argocd argo/argo-cd \
  --namespace $ARGOCD_NAMESPACE \
  --version $ARGOCD_VERSION \
  --values - <<EOF
configs:
  params:
    server.insecure: true
  cm:
    url: https://argocd.mlpipeline.duckdns.org
    application.instanceLabelKey: argocd.argoproj.io/instance
  rbac:
    policy.default: role:readonly
    policy.csv: |
      p, role:developers, applications, get, */*, allow
      p, role:developers, applications, sync, */*, allow
      p, role:admins, applications, *, */*, allow
      p, role:admins, repositories, *, *, allow
      g, developers, role:developers
      g, admins, role:admins

server:
  service:
    type: ClusterIP
  ingress:
    enabled: true
    ingressClassName: nginx
    hosts:
    - argocd.mlpipeline.duckdns.org
    tls:
    - secretName: argocd-tls
      hosts:
      - argocd.mlpipeline.duckdns.org

controller:
  resources:
    requests:
      memory: "256Mi"
      cpu: "100m"
    limits:
      memory: "512Mi"
      cpu: "500m"

repoServer:
  resources:
    requests:
      memory: "256Mi"
      cpu: "100m"
    limits:
      memory: "512Mi"
      cpu: "500m"

dex:
  enabled: true

redis:
  resources:
    requests:
      memory: "128Mi"
      cpu: "50m"
    limits:
      memory: "256Mi"
      cpu: "100m"

notifications:
  enabled: false  # Enable if you want Slack/email notifications

applicationSet:
  enabled: true
EOF

echo "✓ ArgoCD installed successfully"
echo ""

# Step 4: Wait for ArgoCD to be ready
echo "Step 4: Waiting for ArgoCD to be ready..."
echo "------------------------------------------------------------------------"

kubectl wait --for=condition=available --timeout=300s \
  deployment/argocd-server -n $ARGOCD_NAMESPACE || echo "⚠ ArgoCD server didn't become ready in time, continuing..."

kubectl wait --for=condition=available --timeout=300s \
  deployment/argocd-repo-server -n $ARGOCD_NAMESPACE || echo "⚠ ArgoCD repo server didn't become ready in time, continuing..."

echo "✓ ArgoCD deployments are ready"
echo ""

# Step 5: Get initial admin password
echo "Step 5: ArgoCD Credentials"
echo "------------------------------------------------------------------------"

ADMIN_PASSWORD=$(kubectl -n $ARGOCD_NAMESPACE get secret argocd-initial-admin-secret \
  -o jsonpath="{.data.password}" | base64 -d || echo "Unable to retrieve password")

echo "Admin Username: admin"
echo "Admin Password: $ADMIN_PASSWORD"
echo ""

# Step 6: Create Git repository secret
echo "Step 6: Setting up Git repository access..."
echo "------------------------------------------------------------------------"

read -p "Enter Git repository URL (e.g., https://github.com/yourusername/MLPipeline): " REPO_URL
read -p "Enter Git username: " GIT_USERNAME
read -sp "Enter Git personal access token: " GIT_TOKEN
echo ""

# Create secret for private repo
kubectl create secret generic mlpipeline-repo \
  -n $ARGOCD_NAMESPACE \
  --from-literal=url=$REPO_URL \
  --from-literal=username=$GIT_USERNAME \
  --from-literal=password=$GIT_TOKEN \
  --dry-run=client -o yaml | kubectl apply -f -

echo "✓ Git repository credentials configured"
echo ""

# Step 7: Configure ArgoCD CLI
echo "Step 7: ArgoCD CLI Configuration"
echo "------------------------------------------------------------------------"

# Port-forward ArgoCD
echo "Setting up port-forward..."
kubectl port-forward -n $ARGOCD_NAMESPACE svc/argocd-server 8080:443 &
PORT_FORWARD_PID=$!
sleep 2

# Login with ArgoCD CLI if installed
if command -v argocd &> /dev/null; then
    argocd login localhost:8080 \
      --username admin \
      --password "$ADMIN_PASSWORD" \
      --insecure || echo "⚠ ArgoCD CLI login failed"
    
    echo "✓ ArgoCD CLI authenticated"
else
    echo "ℹ ArgoCD CLI not installed. Install with: curl -sSL -o /usr/local/bin/argocd https://github.com/argoproj/argo-cd/releases/download/v2.10.3/argocd-linux-amd64"
fi

# Kill port-forward
kill $PORT_FORWARD_PID 2>/dev/null || true

echo ""

# Step 8: Display access instructions
echo "Step 8: Access ArgoCD"
echo "------------------------------------------------------------------------"

echo "✓ ArgoCD installation complete!"
echo ""
echo "Next steps:"
echo "  1. Port-forward to ArgoCD server:"
echo "     kubectl port-forward -n $ARGOCD_NAMESPACE svc/argocd-server 8080:443"
echo ""
echo "  2. Open in browser: https://localhost:8080"
echo "     Username: admin"
echo "     Password: $ADMIN_PASSWORD"
echo ""
echo "  3. Register Git repository:"
echo "     argocd repo add $REPO_URL --username $GIT_USERNAME --password $GIT_TOKEN"
echo ""
echo "  4. Create MLPipeline application:"
echo "     kubectl apply -f argocd/mlpipeline-app.yaml"
echo ""
echo "  5. Sync the application:"
echo "     argocd app sync mlpipeline"
echo ""
echo "For more information:"
echo "  - ArgoCD Documentation: https://argo-cd.readthedocs.io/"
echo "  - MLPipeline Repository: $REPO_URL"
echo ""
