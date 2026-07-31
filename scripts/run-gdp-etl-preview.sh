#!/bin/bash

#####################################################################
# GDP ETL Preview Notebook Launcher
# Sets up the prerequisites for notebooks/gdp_etl_preview.ipynb and
# opens it in a browser: venv + deps, BEA_API_KEY, a port-forward to
# mlpipeline-postgres, and the POSTGRES_* connection env vars.
#####################################################################

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

NAMESPACE="mlpipeline"
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$( cd "$SCRIPT_DIR/.." && pwd )"

PORT_FORWARD_PID=""
cleanup() {
    if [[ -n "$PORT_FORWARD_PID" ]]; then
        echo -e "\n${YELLOW}Stopping port-forward (pid $PORT_FORWARD_PID)...${NC}"
        kill "$PORT_FORWARD_PID" 2>/dev/null || true
    fi
}
trap cleanup EXIT

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}GDP ETL Preview Notebook Launcher${NC}"
echo -e "${BLUE}========================================${NC}"

#####################################################################
# STEP 1: venv + dependencies
#####################################################################
echo -e "\n${YELLOW}[Step 1] Activating venv and installing dependencies...${NC}"

if [[ ! -d "$PROJECT_ROOT/venv" ]]; then
    echo -e "${RED}ERROR: $PROJECT_ROOT/venv not found. Run: python -m venv venv${NC}"
    exit 1
fi

source "$PROJECT_ROOT/venv/bin/activate"

# Only install what the notebook's ETL code path (src/etl/*, src/utils/config.py)
# and the preview cell (SQLAlchemy engine, to avoid pandas' raw-DBAPI2 warning)
# actually import -- the full requirements.txt pulls in the whole production
# stack (torch, transformers, Airflow + providers) which isn't needed here and,
# on Python >=3.11, isn't even resolvable (numpy==1.24.3 requires Python <3.11).
grep -E '^(pandas|psycopg2-binary|pyyaml|requests|sqlalchemy)==' "$PROJECT_ROOT/requirements.txt" -i \
    | xargs pip install -q
pip install -q jupyter ipykernel
echo -e "${GREEN}✓ venv ready${NC}"

#####################################################################
# STEP 2: kubectl / cluster check
#####################################################################
echo -e "\n${YELLOW}[Step 2] Verifying cluster connection...${NC}"

if ! command -v kubectl &> /dev/null; then
    echo -e "${RED}ERROR: kubectl not found.${NC}"
    exit 1
fi

if ! kubectl get namespace "$NAMESPACE" &> /dev/null; then
    echo -e "${RED}ERROR: Cannot reach namespace '$NAMESPACE'. Check your kubeconfig/cluster.${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Connected, namespace '$NAMESPACE' reachable${NC}"

#####################################################################
# STEP 3: BEA_API_KEY
#####################################################################
echo -e "\n${YELLOW}[Step 3] Setting BEA_API_KEY...${NC}"

if [[ -z "$BEA_API_KEY" ]]; then
    export BEA_API_KEY=$(kubectl get secret bea-api-credentials -n "$NAMESPACE" -o jsonpath='{.data.BEA_API_KEY}' | base64 -d)
    echo -e "${GREEN}✓ BEA_API_KEY pulled from cluster secret${NC}"
else
    echo -e "${GREEN}✓ BEA_API_KEY already set in environment${NC}"
fi

#####################################################################
# STEP 4: Port-forward Postgres + connection env vars
#####################################################################
echo -e "\n${YELLOW}[Step 4] Port-forwarding mlpipeline-postgres...${NC}"

kubectl port-forward -n "$NAMESPACE" svc/mlpipeline-postgres 5432:5432 > /dev/null 2>&1 &
PORT_FORWARD_PID=$!

for i in {1..15}; do
    if (echo > /dev/tcp/localhost/5432) &> /dev/null; then
        break
    fi
    sleep 1
done

if ! (echo > /dev/tcp/localhost/5432) &> /dev/null; then
    echo -e "${RED}ERROR: Port-forward to mlpipeline-postgres did not come up.${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Port-forward up (pid $PORT_FORWARD_PID)${NC}"

export POSTGRES_HOST=localhost
export POSTGRES_PORT=5432
export POSTGRES_USER=$(kubectl get secret mlpipeline-postgres-credentials -n "$NAMESPACE" -o jsonpath='{.data.POSTGRES_USER}' | base64 -d)
export POSTGRES_PASSWORD=$(kubectl get secret mlpipeline-postgres-credentials -n "$NAMESPACE" -o jsonpath='{.data.POSTGRES_PASSWORD}' | base64 -d)
export POSTGRES_DB=$(kubectl get secret mlpipeline-postgres-credentials -n "$NAMESPACE" -o jsonpath='{.data.POSTGRES_DB}' | base64 -d)
echo -e "${GREEN}✓ POSTGRES_* env vars set${NC}"

#####################################################################
# STEP 5: Launch Jupyter
#####################################################################
echo -e "\n${YELLOW}[Step 5] Launching Jupyter Notebook...${NC}"
echo -e "${GREEN}(Ctrl+C here stops both Jupyter and the port-forward)${NC}\n"

cd "$PROJECT_ROOT"
jupyter notebook notebooks/gdp_etl_preview.ipynb
