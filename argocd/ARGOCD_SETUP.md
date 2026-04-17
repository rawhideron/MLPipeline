# ArgoCD Setup for MLPipeline

Complete guide for deploying and managing MLPipeline using ArgoCD GitOps workflow.

## Table of Contents

1. [Overview](#overview)
2. [Prerequisites](#prerequisites)
3. [Installation](#installation)
4. [Configuration](#configuration)
5. [Deployment](#deployment)
6. [Operations](#operations)
7. [Troubleshooting](#troubleshooting)
8. [Advanced Topics](#advanced-topics)

## Overview

[ArgoCD](https://argo-cd.readthedocs.io/) is a declarative, GitOps continuous delivery tool for Kubernetes. It simplifies MLPipeline management by:

- **Declarative**: Define desired state in Git
- **Automated**: Automatic sync when repository changes
- **Visible**: Web UI shows deployment status and history
- **Reliable**: Health monitoring and automatic remediation
- **Auditable**: All changes tracked in Git

### Architecture

```
Git Repository (MLPipeline)
        ↓
    ArgoCD Controller
        ↓
  Kubernetes Cluster (kind-reunion)
        ├── MLPipeline Namespace
        │   ├── Airflow
        │   ├── FastAPI
        │   ├── PostgreSQL
        │   ├── Ingress
        │   └── RBAC
```

## Prerequisites

### Required

- `kubectl` 1.24+
- `helm` 3.10+
- Kubernetes cluster (kind-reunion) running
- `git` installed
- Git repository with MLPipeline code

### Optional

- `argocd` CLI for command-line operations
- Slack/email for notifications
- Keycloak for SSO (advanced)

## Installation

### 1. Quick Install with Script

```bash
cd /home/rongoodman/Projects/MLPipeline
chmod +x argocd/install-argocd.sh
./argocd/install-argocd.sh
```

The script will:
- Verify kubectl and helm
- Create `argocd` namespace
- Install ArgoCD via Helm
- Configure Git repository access
- Display credentials and access instructions

### 2. Manual Installation

```bash
# Add Helm repository
helm repo add argo https://argoproj.github.io/argo-helm
helm repo update

# Install ArgoCD
kubectl create namespace argocd
helm install argocd argo/argo-cd \
  --namespace argocd \
  --values argocd/values-argocd.yaml
```

### 3. Verify Installation

```bash
# Check ArgoCD pods
kubectl get pods -n argocd

# Expected output:
# argocd-application-controller-0   Running
# argocd-dex-server-xxx             Running
# argocd-redis-xxx                  Running
# argocd-repo-server-xxx            Running
# argocd-server-xxx                 Running
```

## Configuration

### Step 1: Access ArgoCD

```bash
# Option A: Port-forward
kubectl port-forward -n argocd svc/argocd-server 8080:443

# Visit: https://localhost:8080
```

```bash
# Option B: Using ArgoCD CLI
argocd login localhost:8080 \
  --username admin \
  --password <INITIAL_PASSWORD> \
  --insecure
```

Get initial password:
```bash
kubectl -n argocd get secret argocd-initial-admin-secret \
  -o jsonpath="{.data.password}" | base64 -d
```

### Step 2: Register Git Repository

```bash
argocd repo add https://github.com/yourusername/MLPipeline \
  --username <GIT_USERNAME> \
  --password <PERSONAL_ACCESS_TOKEN>
```

Or via UI:
1. Settings → Repositories → Connect Repo
2. Choose HTTPS and enter credentials
3. Click Connect

### Step 3: Configure AppProject (Optional)

AppProject defines access control:

```bash
kubectl apply -f argocd/mlpipeline-app.yaml
```

This creates:
- `mlpipeline-project`: Project with RBAC policies
- Access to `MLPipeline` namespace
- Access to Git repository

## Deployment

### Option 1: Deploy Entire MLPipeline

```bash
# Single Application managing all components
kubectl apply -f argocd/mlpipeline-app.yaml

# Verify creation
argocd app list | grep mlpipeline
```

Expected output:
```
mlpipeline  https://github.com/yourusername/MLPipeline  main   MLPipeline  OutOfSync  Unknown
```

### Option 2: Deploy Components Individually

```bash
# Using ApplicationSet for granular control
kubectl apply -f argocd/mlpipeline-appset.yaml

# List all generated applications
argocd app list | grep mlpipeline
```

Expected output:
```
mlpipeline-airflow    ...  main  MLPipeline  OutOfSync  Unknown
mlpipeline-postgres   ...  main  MLPipeline  OutOfSync  Unknown
mlpipeline-fastapi    ...  main  MLPipeline  OutOfSync  Unknown
mlpipeline-manifests  ...  main  MLPipeline  OutOfSync  Unknown
```

### Option 3: Sync Application

After creating application, sync to deploy:

```bash
# Sync via CLI
argocd app sync mlpipeline

# Or use auto-sync in spec (already enabled in manifests)
```

Watch sync progress:
```bash
argocd app wait mlpipeline --sync
```

## Operations

### View Application Status

```bash
# List applications
argocd app list

# Get detailed status
argocd app get mlpipeline

# Watch sync status
argocd app watch mlpipeline
```

### Check Pod Status

```bash
# All MLPipeline pods
kubectl get pods -n MLPipeline

# Specific component
kubectl get deployment -n MLPipeline

# Pod logs
kubectl logs -n MLPipeline -l app=airflow-scheduler -f
```

### Manual Sync

```bash
# Sync specific application
argocd app sync mlpipeline

# Sync with prune (delete resources not in Git)
argocd app sync mlpipeline --prune

# Force sync (ignore sync status)
argocd app sync mlpipeline --force
```

### Refresh Application

```bash
# Hard refresh from Git
argocd app get mlpipeline --refresh

# Check Git changes
git diff origin/main
```

### Rollback to Previous Version

```bash
# List revision history
argocd app history mlpipeline

# Rollback to previous revision
argocd app rollback mlpipeline 1

# Sync after rollback
argocd app sync mlpipeline
```

### Update Application Configuration

Edit Git repository:

```bash
# Modify Helm values
vim helm/mlpipeline-airflow/values.yaml

# Commit and push
git add helm/
git commit -m "Update Airflow configuration"
git push origin main
```

ArgoCD will automatically detect and sync (if auto-sync enabled).

## Troubleshooting

### Application Out of Sync

**Problem**: Application shows "OutOfSync" status

**Solution**:
```bash
# Check difference from Git
argocd app diff mlpipeline

# Manually sync
argocd app sync mlpipeline

# Or enable auto-sync in spec:
kubectl patch application mlpipeline \
  -p '{"spec":{"syncPolicy":{"automated":{"prune":true,"selfHeal":true}}}}' \
  --type merge -n argocd
```

### Pod Not Deploying

**Problem**: Pod stays in Pending or ImagePullBackOff

**Solution**:
```bash
# Check pod events
kubectl describe pod -n MLPipeline <POD_NAME>

# Check resource availability
kubectl describe nodes

# Check image pull secrets
kubectl get secrets -n MLPipeline

# Verify image availability
docker images | grep mlpipeline
```

### Repository Connection Failed

**Problem**: "Failed to get repository details"

**Solution**:
```bash
# Verify Git credentials
argocd repo list

# Update repository credentials
argocd repo add https://github.com/yourusername/MLPipeline \
  --username <USERNAME> \
  --password <TOKEN> \
  --force

# Test connectivity
argocd repo get https://github.com/yourusername/MLPipeline
```

### Helm Values Not Updating

**Problem**: Changes to values.yaml not reflected

**Solution**:
```bash
# Force refresh
argocd app get mlpipeline --refresh

# Hard sync
argocd app sync mlpipeline --force

# Check rendered Helm chart
argocd app get mlpipeline --helm-values
```

### ArgoCD Server Not Accessible

**Problem**: Cannot connect to ArgoCD UI

**Solution**:
```bash
# Check service status
kubectl get svc -n argocd

# Verify port-forward
kubectl port-forward -n argocd svc/argocd-server 8080:443 &

# Check pod logs
kubectl logs -n argocd deployment/argocd-server

# Verify ingress (if using ingress)
kubectl get ingress -n argocd
```

## Advanced Topics

### Custom Sync Hooks

Run tasks before/after sync:

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: mlpipeline
spec:
  source:
    plugin:
      name: custom-plugin
    path: helm
  syncPolicy:
    syncOptions:
    - Validate=false
```

### Multi-Cluster Deployment

Deploy to multiple clusters:

```yaml
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: mlpipeline-multicluster
spec:
  generators:
  - list:
      elements:
      - cluster: kind-reunion
        region: local
      - cluster: eks-prod
        region: us-east-1
  template:
    spec:
      destination:
        server: '{{.cluster}}'
```

### Notifications Integration

Send sync notifications to Slack:

```bash
# Install notifications controller
helm install argocd-notifications argo/argocd-notifications \
  --namespace argocd

# Configure Slack token
kubectl -n argocd create secret generic slack-token \
  --from-literal=token=<SLACK_BOT_TOKEN>
```

### SSO with Keycloak

Integrate with existing Keycloak realm:

```yaml
configs:
  cm:
    oidc.keycloak.clientID: argocd
    oidc.keycloak.clientSecret: <secret>
    oidc.keycloak.issuer: https://keycloak.mlpipeline.duckdns.org/realms/MLPipeline
    oidc.keycloak.scopes: openid,profile,email
```

### Image Updater

Automatically update container images:

```bash
helm install argocd-image-updater argo/argocd-image-updater \
  --namespace argocd
```

Annotate components:
```yaml
metadata:
  annotations:
    argocd-image-updater.argoproj.io/image-list: mlpipeline-serving
    argocd-image-updater.argoproj.io/mlpipeline-serving.update-strategy: semver
```

## Best Practices

1. **GitOps Principles**
   - All changes through Git commits
   - Use branches for staging/prod environments
   - Code review before merge

2. **Repository Structure**
   ```
   MLPipeline/
   ├── helm/
   │   ├── mlpipeline-airflow/
   │   ├── mlpipeline-serving/
   │   └── mlpipeline-postgres/
   ├── argocd/
   │   ├── mlpipeline-app.yaml
   │   └── values-argocd.yaml
   └── kubernetes/
   ```

3. **Sync Strategies**
   - Enable auto-sync for stability
   - Use prune to clean resources
   - Enable self-heal for drift correction

4. **Monitoring**
   - Monitor application health via UI
   - Set up Slack notifications
   - Review sync history regularly

5. **Security**
   - Use Git credentials for private repos
   - Enable RBAC in ArgoCD
   - Use sealed secrets for sensitive data
   - Rotate personal access tokens regularly

## Resources

- [ArgoCD Documentation](https://argo-cd.readthedocs.io/)
- [ArgoCD GitHub](https://github.com/argoproj/argo-cd)
- [GitOps Best Practices](https://opengitops.dev/)
- [MLPipeline README](../README.md)
- [MLPipeline Deployment Guide](../DEPLOYMENT.md)

## Support

For issues or questions:

1. Check [Troubleshooting](#troubleshooting) section
2. Review ArgoCD logs: `kubectl logs -n argocd deployment/argocd-server`
3. Check MLPipeline issues: GitHub Issues
4. Consult ArgoCD community: Slack, GitHub Discussions
