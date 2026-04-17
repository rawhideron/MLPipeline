# Kubernetes Deployment Guide

Complete step-by-step guide for deploying MLPipeline to `kind-reunion` cluster.

## Prerequisites

- **Kubernetes Cluster**: `kind-reunion` (Kind cluster configured)
- **kubectl**: v1.25+ configured to access `kind-reunion`
- **Helm**: v3.10+ installed
- **Docker**: (optional, for building custom images)
- **Keycloak**: Running instance with admin access
- **DNS**: `mlpipeline.duckdns.org` configured and pointing to cluster ingress
- **cert-manager**: Installed in cluster for TLS certificate management

### Verify Prerequisites

```bash
# Check kubectl
kubectl version --client

# Check Helm
helm version

# Check cluster access
kubectl cluster-info

# Check cert-manager
kubectl get pods -n cert-manager

# Check Keycloak access
curl https://keycloak:8080/auth/admin/realms/
```

## Deployment Steps

### 1. Clone Repository

```bash
cd /home/rongoodman/Projects
git clone https://github.com/yourusername/MLPipeline.git
cd MLPipeline
```

### 2. Make Scripts Executable

```bash
chmod +x scripts/deploy.sh
chmod +x scripts/setup-keycloak.sh
chmod +x scripts/cleanup.sh
```

### 3. Configure Secrets

**Important**: Update default credentials before deployment.

Edit `kubernetes/postgres-secret.yaml`:

```bash
# Generate secure passwords
openssl rand -base64 32 > /tmp/db_password.txt
openssl rand -base64 32 > /tmp/oauth_client_secret.txt

# Update the secret file with new passwords
```

### 4. Run Deployment Script

```bash
./scripts/deploy.sh
```

This script will:
- Verify prerequisites and cluster connectivity
- Create `MLPipeline` namespace
- Apply Kubernetes manifests (RBAC, secrets, configmaps)
- Deploy PostgreSQL via Helm
- Deploy Apache Airflow via Helm
- Deploy FastAPI serving via Helm
- Verify all deployments
- Guide through Keycloak setup (optional)

### 5. Configure Keycloak

Run the Keycloak setup script:

```bash
./scripts/setup-keycloak.sh
```

Or follow the manual steps in [KEYCLOAK_SETUP.md](KEYCLOAK_SETUP.md).

### 6. Verify Deployment

```bash
# Check all pods
kubectl get pods -n MLPipeline

# Check services
kubectl get svc -n MLPipeline

# Check ingress
kubectl get ingress -n MLPipeline

# Check persistent volumes
kubectl get pv -n MLPipeline
```

Expected output should show:
- Airflow scheduler, webserver, and worker pods
- FastAPI serving pods (typically 2 replicas)
- PostgreSQL pod
- Services for each component
- Ingress pointing to `mlpipeline.duckdns.org`

### 7. Access Services

Once deployed, you can access services via:

- **Airflow Webserver**: https://mlpipeline.duckdns.org/airflow
- **FastAPI Docs**: https://mlpipeline.duckdns.org/api/docs
- **Health Check**: https://mlpipeline.duckdns.org/api/health

## Port Forwarding (Local Development)

For local testing without exposing to public internet:

```bash
# Airflow (in terminal 1)
kubectl port-forward -n MLPipeline svc/airflow-webserver 8080:8080

# FastAPI (in terminal 2)
kubectl port-forward -n MLPipeline svc/mlpipeline-serving 8000:8000

# PostgreSQL (in terminal 3)
kubectl port-forward -n MLPipeline svc/mlpipeline-postgresql 5432:5432
```

Then access locally:
- Airflow: http://localhost:8080
- FastAPI: http://localhost:8000
- PostgreSQL: localhost:5432

## Troubleshooting

### Pods Not Starting

```bash
# Check pod status
kubectl describe pod -n MLPipeline <pod-name>

# View pod logs
kubectl logs -n MLPipeline <pod-name>

# Check events in namespace
kubectl get events -n MLPipeline --sort-by='.lastTimestamp'
```

### PostgreSQL Connection Issues

```bash
# Test PostgreSQL connectivity
kubectl run -it --rm debug --image=postgres:14 --restart=Never -- \
    psql postgresql://airflow:airflow_secure_password_change_me@mlpipeline-postgresql:5432/airflow

# View PostgreSQL logs
kubectl logs -n MLPipeline -f statefulset/mlpipeline-postgres-postgresql
```

### Airflow Webserver Not Accessible

```bash
# Check webserver pod
kubectl logs -n MLPipeline -f deployment/airflow-webserver

# Check webserver service
kubectl get svc -n MLPipeline airflow-webserver

# Port forward and test locally
kubectl port-forward -n MLPipeline svc/airflow-webserver 8080:8080
curl http://localhost:8080/health
```

### Ingress/TLS Issues

```bash
# Check ingress status
kubectl describe ingress -n MLPipeline mlpipeline-ingress

# Check cert-manager certificate
kubectl get certificate -n MLPipeline

# View cert-manager logs
kubectl logs -n cert-manager -f deployment/cert-manager
```

### OAuth Not Working

```bash
# Check OAuth proxy logs
kubectl logs -n MLPipeline -f deployment/oauth2-proxy

# Verify Keycloak connectivity
kubectl exec -it -n MLPipeline <airflow-webserver-pod> -- \
    curl https://keycloak:8080/realms/MLPipeline

# Check Keycloak realm configuration
# Use scripts/setup-keycloak.sh for re-configuration
```

## Updating Deployments

### Update Helm Chart Values

Edit the appropriate values file:
- `helm/mlpipeline-airflow/values.yaml`
- `helm/mlpipeline-serving/values.yaml`

Then upgrade:

```bash
# Upgrade Airflow
helm upgrade mlpipeline-airflow apache-airflow/airflow \
    -f helm/mlpipeline-airflow/values.yaml \
    -n MLPipeline

# Upgrade Serving
helm upgrade mlpipeline-serving helm/mlpipeline-serving \
    -n MLPipeline

# Check rollout status
kubectl rollout status deployment/airflow-webserver -n MLPipeline
kubectl rollout status deployment/mlpipeline-serving -n MLPipeline
```

### Update Configuration

Edit Kubernetes ConfigMaps:

```bash
kubectl edit configmap mlpipeline-config -n MLPipeline
```

Changes will require pod restarts:

```bash
# Restart Airflow
kubectl rollout restart deployment/airflow-webserver -n MLPipeline
kubectl rollout restart deployment/airflow-scheduler -n MLPipeline

# Restart FastAPI
kubectl rollout restart deployment/mlpipeline-serving -n MLPipeline
```

## Cleanup

To remove all MLPipeline resources:

```bash
./scripts/cleanup.sh
```

This will:
- Uninstall all Helm releases
- Delete all Kubernetes resources
- Delete the `MLPipeline` namespace
- Remove persistent volume claims

**Note**: Persistent volumes may need manual deletion depending on cluster configuration.

## Performance Tuning

### Resource Limits

Adjust resource requests/limits in:
- `helm/mlpipeline-airflow/values.yaml`
- `helm/mlpipeline-serving/values.yaml`

```yaml
resources:
  requests:
    memory: "2Gi"
    cpu: "1000m"
  limits:
    memory: "4Gi"
    cpu: "2000m"
```

### Autoscaling

Enable Horizontal Pod Autoscaling (HPA):

```bash
kubectl autoscale deployment mlpipeline-serving \
    --min=2 --max=5 \
    -n MLPipeline
```

### Database Optimization

Configure PostgreSQL performance:

```bash
# Edit PostgreSQL ConfigMap
kubectl edit configmap mlpipeline-postgres-config -n MLPipeline

# Common settings:
# shared_buffers = 256MB
# effective_cache_size = 1GB
# work_mem = 16MB
# maintenance_work_mem = 64MB
```

## Monitoring & Logging

### View Logs

```bash
# Tail Airflow scheduler logs
kubectl logs -n MLPipeline -f deployment/airflow-scheduler

# Tail FastAPI logs
kubectl logs -n MLPipeline -f deployment/mlpipeline-serving

# Previous logs (if pod crashed)
kubectl logs -n MLPipeline <pod-name> --previous
```

### Access Pod Shells

```bash
# Airflow webserver
kubectl exec -it -n MLPipeline deployment/airflow-webserver -- /bin/bash

# FastAPI serving
kubectl exec -it -n MLPipeline deployment/mlpipeline-serving -- /bin/bash

# PostgreSQL
kubectl exec -it -n MLPipeline statefulset/mlpipeline-postgres-postgresql -- /bin/bash
```

### Monitor Resources

```bash
# Real-time resource usage
kubectl top nodes
kubectl top pods -n MLPipeline

# Monitor pod events
kubectl get events -n MLPipeline --watch
```

## Backup & Restore

### Backup Database

```bash
kubectl exec -it -n MLPipeline statefulset/mlpipeline-postgres-postgresql -- \
    pg_dump -U airflow airflow > airflow_backup.sql
```

### Restore Database

```bash
kubectl exec -it -n MLPipeline statefulset/mlpipeline-postgres-postgresql -- \
    psql -U airflow airflow < airflow_backup.sql
```

### Backup Persistent Volumes

```bash
# Copy data from volume
kubectl exec -it -n MLPipeline <pod-name> -- \
    tar czf /tmp/backup.tar.gz /data

kubectl cp MLPipeline/<pod-name>:/tmp/backup.tar.gz ./backup.tar.gz
```

## Support

For issues or questions:

1. Check [Troubleshooting](#troubleshooting) section
2. Review [KEYCLOAK_SETUP.md](KEYCLOAK_SETUP.md) for OAuth issues
3. Check pod logs with `kubectl logs`
4. Review cluster events: `kubectl get events -n MLPipeline`

---

**Last Updated**: April 2026  
**Status**: Stable
