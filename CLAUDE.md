# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Common Commands

```bash
# Setup
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Tests
pytest tests/ -v
pytest tests/ --cov=src --cov-report=html
pytest tests/test_models.py -v          # single file
pytest tests/ -k "test_clean_text"      # single test

# Local development (without Kubernetes)
python src/preprocessing/text_cleaning.py
python src/models/training.py configs/training_config.yaml
cd serving && uvicorn app:app --reload   # runs on :8000

# Kubernetes
kubectl get pods -n MLPipeline
kubectl logs -n MLPipeline -f deployment/airflow-scheduler
kubectl port-forward -n MLPipeline svc/airflow-webserver 8080:8080
```

## Architecture

This is an end-to-end NLP sentiment classification pipeline deployed on a `kind-reunion` Kubernetes cluster.

**Data flow**: Raw text → `src/preprocessing/text_cleaning.py` → HuggingFace `datasets` → `src/models/training.py` (fine-tunes `distilbert-base-uncased`) → `/models/trained_model` (PV) → `serving/app.py` (FastAPI)

**Orchestration**: Airflow (`dags/training_dag.py`) runs the pipeline weekly via `KubernetesPodOperator` — each step (validate → preprocess → train → evaluate → log) runs as a separate K8s pod in the `MLPipeline` namespace.

**Authentication**: All endpoints except `/health` require a Keycloak JWT. `serving/oauth_middleware.py` fetches the JWKS from Keycloak, verifies RS256 tokens, and exposes a `verify_token` FastAPI dependency. Environment variables `KEYCLOAK_REALM_URL`, `OAUTH_CLIENT_ID`, `OAUTH_CLIENT_SECRET` configure the connection.

**Deployment**: Helm charts under `helm/` deploy Airflow, FastAPI serving, and PostgreSQL. ArgoCD (`argocd/mlpipeline-app.yaml`) auto-syncs from this repo to the cluster. The ingress at `mlpipeline.duckdns.org` uses nginx + cert-manager for TLS and oauth2-proxy for route-level auth.

**Config**: `configs/training_config.yaml` controls model name, epochs, batch size, learning rate, and dataset paths. `configs/inference_config.yaml` controls serving parameters. These are mounted into pods via ConfigMap.

## Key Relationships

- `serving/app.py` imports `oauth_middleware.py` and `inference_handler.py` — the serving directory is its own Python package deployed in a separate container.
- `src/models/training.py` loads data from HuggingFace Hub (`imdb` dataset) and saves to the path in `output.model_path` from the config.
- `src/models/inference.py` (`SentimentPredictor`) reads from the same path that training writes to — they share the `/models/trained_model` persistent volume in-cluster.
- DAG tasks use `KubernetesPodOperator` with `in_cluster=True`, so they rely on the service account RBAC defined in `kubernetes/service-accounts.yaml`.

## Infrastructure Notes

- Cluster: `reunion` (local Kind — `kind-reunion` in some older docs refers to the same cluster)
- Keycloak realm: `MLPipeline` — must be pre-configured before deploying (see `KEYCLOAK_SETUP.md`)
- DNS: `mlpipeline.duckdns.org` — requires a duckdns.org account
- For local LLM features: use [Ollama](https://ollama.com) with Mistral, Llama 3, or Phi-3 (no paid API required)
- DVC S3 backend (`dvc-s3`) is optional — omit if not using remote artifact storage

## GitHub Actions

Two workflows run automatically:

- **CI** (`.github/workflows/ci.yml`) — triggers on every PR and push to `main`/`dev`: runs `pytest` with coverage, SonarCloud scan, and `ruff` lint/format check.
- **CD** (`.github/workflows/cd.yml`) — triggers on merge to `main`: calls `argocd app sync` for the manifests app and all three Helm component apps in wave order (postgres → airflow → serving).

**Required GitHub Secrets:**

| Secret | Description |
| ------ | ----------- |
| `SONAR_TOKEN` | From the self-hosted SonarQube at `goodmanreunion.duckdns.org/sonarqube` (same instance as goodman_reunion) |
| `ARGOCD_SERVER` | Hostname of ArgoCD server (e.g. `argocd.mlpipeline.duckdns.org`) |
| `ARGOCD_USERNAME` | ArgoCD username (default: `admin`) |
| `ARGOCD_PASSWORD` | ArgoCD admin password |

## ArgoCD

Apply both manifests to register the apps with ArgoCD:

```bash
# Register the AppProject and main manifests app
kubectl apply -f argocd/mlpipeline-app.yaml

# Register the Helm component ApplicationSet (postgres, airflow, serving)
kubectl apply -f argocd/mlpipeline-appset.yaml

# Trigger an immediate sync
argocd app sync mlpipeline
```

The `mlpipeline` app syncs `kubernetes/` (raw manifests). The `mlpipeline-components` ApplicationSet creates three apps from `helm/mlpipeline-{postgres,airflow,serving}` in sync-wave order.

## Branch & PR Workflow

All changes follow a three-tier flow: feature/fix branch → `dev` → `main`. ArgoCD watches `main` and syncs automatically to the cluster on every merge.

1. Create a branch off `dev`: `feature/<name>` for new work, `fix/<name>` for bug fixes
2. Open a PR targeting `dev` with `--auto` flag — it merges automatically once CI passes
3. Open a PR from `dev` → `main` with `--auto` flag — same auto-merge on green CI
4. ArgoCD detects the `main` change and syncs to the cluster automatically

```bash
# Standard PR flow
gh pr create --base dev --title "..." --body "..."
gh pr merge <number> --merge --auto

# After it merges to dev, promote to main
gh pr create --base main --head dev --title "Promote dev → main: ..." --body "..."
gh pr merge <number> --merge --auto
```

**Never commit directly to `main` or `dev`.**

**Never run `helm upgrade` or `kubectl apply` to modify cluster state directly** — ArgoCD owns all cluster resources. Make changes in the repo and let ArgoCD sync them.

Branch protection is enabled on `dev` and `main` (CI must pass). Auto-merge is enabled in repo settings.
