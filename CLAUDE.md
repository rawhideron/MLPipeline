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

# Kubernetes (backend runs on the Zephyrus kind cluster, 192.168.1.178)
ssh ron-goodman@192.168.1.178 'kubectl get pods -n mlpipeline'
ssh ron-goodman@192.168.1.178 'kubectl logs -n mlpipeline -f deploy/mlpipeline-airflow-scheduler -c scheduler'
kubectl get pods -n mlpipeline            # reunion: edge only (oauth2-proxy)
```

## Architecture

This is an end-to-end NLP sentiment classification pipeline split across two kind clusters, both named `reunion`:

- **reunion on pop-os (192.168.1.230)** — the public edge: `mlpipeline.duckdns.org` ingress, TLS, oauth2-proxy, Keycloak, and the ArgoCD instance that manages both clusters.
- **reunion on Zephyrus (192.168.1.178 / .176)** — the backend: Airflow, serving, both PostgreSQL databases and all PVCs. Registered in ArgoCD as `https://192.168.1.176:16443`.

The edge ingress routes `/api`, `/airflow` and `/health` to the selector-less Service `mlpipeline-backend-178` (Endpoints `192.168.1.178:18000`). On Zephyrus, the `rag-forward` systemd relay forwards `:18000` to the kind ingress NodePort and `:16443` to the kind API (port 80/443 there are taken by k3s Traefik).

**Data flow**: Raw text → `src/preprocessing/text_cleaning.py` → HuggingFace `datasets` → `src/models/training.py` (fine-tunes `distilbert-base-uncased`) → `/models/trained_model` (PV) → `serving/app.py` (FastAPI)

**Orchestration**: Airflow (`dags/training_dag.py`) runs the pipeline weekly via `KubernetesPodOperator` — each step (validate → preprocess → train → evaluate → log) runs as a separate K8s pod in the `mlpipeline` namespace on Zephyrus.

**Authentication**: All endpoints except `/health` require a Keycloak JWT. `serving/oauth_middleware.py` fetches the JWKS from Keycloak, verifies RS256 tokens, and exposes a `verify_token` FastAPI dependency. Environment variables `KEYCLOAK_REALM_URL`, `OAUTH_CLIENT_ID`, `OAUTH_CLIENT_SECRET` configure the connection.

**Deployment**: Helm charts under `helm/` deploy Airflow, FastAPI serving, and PostgreSQL to Zephyrus via `argocd/mlpipeline-178.yaml`; reunion runs only oauth2-proxy and the edge manifests (`argocd/mlpipeline-app.yaml`, `argocd/mlpipeline-appset.yaml`). The ingress at `mlpipeline.duckdns.org` uses nginx + cert-manager for TLS and oauth2-proxy for route-level auth.

**Config**: `configs/training_config.yaml` controls model name, epochs, batch size, learning rate, and dataset paths. `configs/inference_config.yaml` controls serving parameters. These are mounted into pods via ConfigMap.

## Key Relationships

- `serving/app.py` imports `oauth_middleware.py` and `inference_handler.py` — the serving directory is its own Python package deployed in a separate container.
- `src/models/training.py` loads data from HuggingFace Hub (`imdb` dataset) and saves to the path in `output.model_path` from the config.
- `src/models/inference.py` (`SentimentPredictor`) reads from the same path that training writes to — they share the `/models/trained_model` persistent volume in-cluster.
- DAG tasks use `KubernetesPodOperator` with `in_cluster=True`, so they rely on the service account RBAC defined in `kubernetes/service-accounts.yaml`.

## Airflow Reference

When investigating or changing any Airflow configuration, consult the official docs first:

- **Configuration reference**: [configurations-ref](https://airflow.apache.org/docs/apache-airflow/stable/configurations-ref.html)
  - Section names and env var names change between major versions — always verify against the running version
  - Key sections for this deployment: `[core]`, `[api]`, `[api_auth]`, `[execution_api]`, `[kubernetes_executor]`
- **Main docs root**: [airflow.apache.org/docs](https://airflow.apache.org/docs/)

## Infrastructure Notes

- Clusters: see Architecture. Older docs that say everything runs on `kind-reunion` predate the backend move to Zephyrus.
- Custom images (`mlpipeline-serving`, `-training`, `-etl`) are pulled from `kind-registry:5000` on Zephyrus. Push with `docker push localhost:5001/<name>:<tag>` on that host. Do not `kind load` them there — fanning a multi-GB image out to all five nodes has hard-reset the laptop.
- Keycloak realm: `MLPipeline` — must be pre-configured before deploying (see `KEYCLOAK_SETUP.md`)
- DNS: `mlpipeline.duckdns.org` — requires a duckdns.org account
- For local LLM features: use [Ollama](https://ollama.com) with Mistral, Llama 3, or Phi-3 (no paid API required)
- DVC S3 backend (`dvc-s3`) is optional — omit if not using remote artifact storage

## GitHub Actions

Two workflows run automatically:

- **CI** (`.github/workflows/ci.yml`) — triggers on every PR targeting `main` or `dev`. `pytest` with coverage and the SonarCloud scan only run on PRs targeting `dev` (feature/fix → dev); the `dev` → `main` promotion PR only runs DAG validation and `ruff` lint/format check, since that code was already tested on `dev`.
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
# Reunion: AppProject, edge manifests app, oauth2-proxy ApplicationSet
# (apply together, appset first: both files carry an argocd-notifications-cm)
kubectl apply -f argocd/mlpipeline-appset.yaml -f argocd/mlpipeline-app.yaml

# Zephyrus backend: postgres, airflow, serving + backend manifests
kubectl apply -f argocd/mlpipeline-178.yaml

# Trigger an immediate sync
argocd app sync mlpipeline
```

The `mlpipeline` app syncs only `kubernetes/ingress.yaml` and `namespace.yaml` to reunion. `mlpipeline-backend-178` syncs the rest of `kubernetes/` (plus `kubernetes/zephyrus/`) to Zephyrus. `mlpipeline-components` (reunion) has only oauth2proxy; `mlpipeline-components-178` deploys `helm/mlpipeline-{postgres,airflow,serving}` to Zephyrus. Files under `argocd/` are applied manually — merging them changes nothing until applied.

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
