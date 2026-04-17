# ArgoCD GitOps for MLPipeline

This directory contains ArgoCD configurations for deploying and managing MLPipeline on Kubernetes using GitOps principles.

## Quick Start

### 1. Install ArgoCD

```bash
cd /home/rongoodman/Projects/MLPipeline
chmod +x argocd/install-argocd.sh
./argocd/install-argocd.sh
```

### 2. Deploy MLPipeline

```bash
# Deploy entire pipeline
kubectl apply -f argocd/mlpipeline-app.yaml

# Or deploy components individually
kubectl apply -f argocd/mlpipeline-appset.yaml
```

### 3. Monitor Deployment

```bash
# Get application status
argocd app get mlpipeline

# Watch sync progress
argocd app watch mlpipeline

# Access UI
kubectl port-forward -n argocd svc/argocd-server 8080:443
# Visit: https://localhost:8080
```

## Files Overview

| File | Purpose |
|------|---------|
| `mlpipeline-app.yaml` | Main ArgoCD Application managing all components |
| `mlpipeline-appset.yaml` | ApplicationSet for per-component control |
| `values-argocd.yaml` | Helm values for ArgoCD installation |
| `install-argocd.sh` | Automated installation script |
| `ARGOCD_SETUP.md` | Complete setup and operations guide |

## Architecture

```
┌─────────────────────────────────────┐
│     Git Repository (MLPipeline)     │
│  - Helm charts                      │
│  - Kubernetes manifests             │
│  - ArgoCD configs                   │
└──────────────┬──────────────────────┘
               │
               ├──→ mlpipeline-app.yaml
               │    (Single App)
               │
               ├──→ mlpipeline-appset.yaml
               │    (Multiple Apps per component)
               │
               v
       ┌───────────────┐
       │    ArgoCD     │
       │   Controller  │
       └───────┬───────┘
               │
               v
   ┌───────────────────────────┐
   │   Kubernetes Cluster      │
   │   (kind-reunion)          │
   │                           │
   │  ┌─────────────────────┐  │
   │  │  MLPipeline         │  │
   │  │  Namespace          │  │
   │  │                     │  │
   │  │  ├─ Airflow         │  │
   │  │  ├─ FastAPI         │  │
   │  │  ├─ PostgreSQL      │  │
   │  │  ├─ Ingress         │  │
   │  │  └─ RBAC            │  │
   │  └─────────────────────┘  │
   │                           │
   └───────────────────────────┘
```

## Deployment Strategies

### Strategy 1: Single Application (Recommended)

Deploy everything as one application:

```bash
kubectl apply -f argocd/mlpipeline-app.yaml
argocd app sync mlpipeline
```

**Pros:**
- Simple management
- Single sync point
- Easy status overview

**Cons:**
- All-or-nothing deployment
- Harder to manage individual components

### Strategy 2: ApplicationSet (Fine-grained)

Deploy each component as a separate application:

```bash
kubectl apply -f argocd/mlpipeline-appset.yaml
argocd app list | grep mlpipeline
```

Applications created:
- `mlpipeline-postgres` (syncWave: 0)
- `mlpipeline-manifests` (syncWave: 1)
- `mlpipeline-airflow` (syncWave: 1)
- `mlpipeline-fastapi` (syncWave: 2)

**Pros:**
- Component-level control
- Ordered deployment (syncWaves)
- Independent rollbacks

**Cons:**
- More complex management
- Multiple sync operations

## Key Features

### Automatic Sync

Applications automatically sync when Git changes:

```yaml
syncPolicy:
  automated:
    prune: true      # Delete resources not in Git
    selfHeal: true   # Fix drift
```

Disable auto-sync:
```bash
argocd app set mlpipeline --sync-policy none
```

### Health Monitoring

ArgoCD monitors component health:

- ✅ Healthy: All resources in desired state
- ⚠️ Degraded: Some resources not healthy
- 🔄 Progressing: Deployment in progress
- ❌ Unknown: Cannot determine health

### Automated Rollback

Rollback to previous deployment:

```bash
argocd app history mlpipeline
argocd app rollback mlpipeline <REVISION>
argocd app sync mlpipeline
```

### Manual Sync

```bash
# Sync from Git
argocd app sync mlpipeline

# Force full resync
argocd app sync mlpipeline --force

# Sync with prune
argocd app sync mlpipeline --prune
```

## Configuration Management

### Helm Values

Helm chart values in `mlpipeline-app.yaml`:

```yaml
source:
  helm:
    values: |
      global:
        domain: mlpipeline.duckdns.org
        namespace: MLPipeline
```

Update values:
1. Edit Git repository
2. Commit and push
3. ArgoCD automatically syncs (if auto-sync enabled)

### ConfigMaps & Secrets

Store in Kubernetes (referenced in Helm):

```bash
# Update Airflow configuration
kubectl edit configmap airflow-logs-config -n MLPipeline

# Update Keycloak secrets
kubectl edit secret keycloak-serving-secret -n MLPipeline
```

## Monitoring & Debugging

### Check Application Status

```bash
# Get overview
argocd app get mlpipeline

# Watch real-time status
argocd app watch mlpipeline

# Compare with Git
argocd app diff mlpipeline
```

### Check Component Status

```bash
# All pods
kubectl get pods -n MLPipeline

# Specific deployment
kubectl get deployment -n MLPipeline

# Pod events and logs
kubectl describe pod <POD_NAME> -n MLPipeline
kubectl logs <POD_NAME> -n MLPipeline
```

### View Sync History

```bash
# Application sync history
argocd app history mlpipeline

# Detailed sync info
argocd app get mlpipeline --refresh
```

## Troubleshooting

### Out of Sync

```bash
# Check differences
argocd app diff mlpipeline

# Manual sync
argocd app sync mlpipeline --force
```

### Failed Deployment

```bash
# Check application events
kubectl describe app mlpipeline -n argocd

# Check controller logs
kubectl logs -n argocd deployment/argocd-application-controller

# Check repo server logs
kubectl logs -n argocd deployment/argocd-repo-server
```

### Repository Connection Issues

```bash
# List configured repos
argocd repo list

# Update repo credentials
argocd repo add https://github.com/yourusername/MLPipeline \
  --username <USERNAME> \
  --password <TOKEN> \
  --force

# Test connectivity
argocd repo get https://github.com/yourusername/MLPipeline
```

For more details, see [ARGOCD_SETUP.md](ARGOCD_SETUP.md#troubleshooting).

## Advanced Topics

### Multi-Environment Setup

Deploy to dev, staging, prod:

```
Git Branches:
  main → prod
  staging → staging
  dev → dev

ArgoCD Projects:
  mlpipeline-prod
  mlpipeline-staging
  mlpipeline-dev
```

### Notifications

Enable Slack notifications:

```bash
# Install notifications controller
helm upgrade argocd argo/argo-cd \
  -n argocd \
  --set notifications.enabled=true

# Configure Slack token
kubectl -n argocd create secret generic slack-token \
  --from-literal=token=<BOT_TOKEN>
```

### Image Updates

Auto-update container images:

```bash
# Install image updater
helm install argocd-image-updater argo/argocd-image-updater \
  -n argocd

# Add annotations to deployments
metadata:
  annotations:
    argocd-image-updater.argoproj.io/image-list: mlpipeline-serving
```

### SSO with Keycloak

Integrate existing Keycloak realm for ArgoCD login:

See [ARGOCD_SETUP.md](ARGOCD_SETUP.md#sso-with-keycloak).

## Best Practices

1. **Version Control**
   - All changes through Git
   - Use branches and PRs
   - Review all changes before merge

2. **Repository Structure**
   ```
   MLPipeline/
   ├── helm/          # Helm charts
   ├── kubernetes/    # Raw manifests
   ├── argocd/        # ArgoCD configs
   └── docs/          # Documentation
   ```

3. **Sync Strategies**
   - Enable auto-sync for production
   - Use pruning to remove orphaned resources
   - Enable self-heal for automatic remediation

4. **Security**
   - Use personal access tokens (not passwords)
   - Rotate tokens regularly
   - Use RBAC to limit user access
   - Store secrets in sealed-secrets

5. **Monitoring**
   - Set up notifications (Slack, email)
   - Review sync history regularly
   - Monitor application health
   - Alert on sync failures

## Useful Commands

```bash
# Application management
argocd app list
argocd app get mlpipeline
argocd app sync mlpipeline
argocd app rollback mlpipeline <REVISION>
argocd app delete mlpipeline

# Repository management
argocd repo list
argocd repo add <URL> --username <USER> --password <TOKEN>
argocd repo get <URL>
argocd repo remove <URL>

# Port-forward
kubectl port-forward -n argocd svc/argocd-server 8080:443

# Logs
kubectl logs -n argocd deployment/argocd-server -f
kubectl logs -n argocd deployment/argocd-repo-server -f
kubectl logs -n argocd deployment/argocd-application-controller -f
```

## References

- [ArgoCD Documentation](https://argo-cd.readthedocs.io/)
- [GitOps Best Practices](https://opengitops.dev/)
- [MLPipeline README](../README.md)
- [MLPipeline Deployment Guide](../DEPLOYMENT.md)
- [Keycloak Setup](../KEYCLOAK_SETUP.md)

## Next Steps

1. **Install ArgoCD**: Run `./install-argocd.sh`
2. **Deploy MLPipeline**: Apply `mlpipeline-app.yaml`
3. **Monitor Status**: Use `argocd app watch mlpipeline`
4. **Access Services**:
   - Airflow: `kubectl port-forward -n MLPipeline svc/airflow-webserver 8080:8080`
   - FastAPI: `kubectl port-forward -n MLPipeline svc/mlpipeline-serving 8000:8000`
   - ArgoCD: `kubectl port-forward -n argocd svc/argocd-server 8080:443`

## Support

For issues:
1. Check [Troubleshooting](#troubleshooting) section
2. Review logs: `kubectl logs -n argocd <POD>`
3. Consult [ARGOCD_SETUP.md](ARGOCD_SETUP.md)
4. Visit [ArgoCD Community](https://github.com/argoproj/argo-cd/discussions)
