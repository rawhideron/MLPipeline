# GDP ETL Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a standalone `gdp_etl` Airflow DAG that extracts US GDP (NIPA) data from the BEA API, reshapes it with pandas, and upserts it into the existing (currently idle) `mlpipeline-postgres` Postgres instance.

**Architecture:** One DAG (`dags/gdp_etl_dag.py`) with three `KubernetesPodOperator` tasks (`extract_gdp_data >> transform_gdp_data >> load_gdp_data`), each running a script from a new `src/etl/` package inside a new `mlpipeline-etl` image. Tasks hand data off via a shared PVC, mirroring the pattern `training_dag.py` uses for its model PVC.

**Tech Stack:** Python 3.11, `requests`, `pandas`, `psycopg2-binary`, Apache Airflow (`KubernetesPodOperator`), existing `mlpipeline-postgres` Postgres 15 instance.

## Global Constraints

- Schedule: `@weekly`, matching `training_dag.py`'s cadence.
- Load semantics: upsert (`INSERT ... ON CONFLICT DO UPDATE`) keyed on `(period, series_code)` — BEA revises historical figures, so reruns must overwrite rather than duplicate.
- Transform tool: pandas only (not Spark, not dbt) — dataset is small.
- Load implementation: a plain Python script using `psycopg2`, run as a `KubernetesPodOperator` pod — not Airflow's `PostgresOperator`, to match this repo's existing convention of running `src/*.py` scripts as pods.
- Data handoff between tasks: a shared PVC (new `mlpipeline-etl-data`), not XCom — mirrors `training_dag.py`'s `_models_volume()`/`_models_mount()` pattern.
- Postgres target: the existing `mlpipeline-postgres` instance's existing `mlpipeline` database (confirmed live and currently unused in the cluster — see `docs/superpowers/specs/2026-07-08-gdp-etl-pipeline-design.md`). No new database, no new Postgres Secret — reuse the existing `mlpipeline-postgres-credentials` Secret's `POSTGRES_USER`/`POSTGRES_PASSWORD`/`POSTGRES_DB` keys.
- DAG structure: one DAG, not three chained via `TriggerDagRunOperator` — extract/transform/load always run together.
- Never run `kubectl apply` or `helm upgrade` against the live cluster — new K8s manifests are added to `kubernetes/` and left for ArgoCD to sync after merge, per this repo's workflow.

---

### Task 1: Extract module (`src/etl/extract.py`)

**Files:**
- Create: `src/etl/__init__.py` (empty)
- Create: `src/etl/extract.py`
- Modify: `requirements-ci.txt` (add `requests==2.33.0` — CI installs this file, and `src/etl/extract.py` needs `requests` importable for tests to collect)
- Test: `tests/test_etl.py`

**Interfaces:**
- Produces: `fetch_nipa_data(user_id: str, table_name: str, frequency: str, year: str) -> dict` — calls the BEA API, returns the parsed JSON response.
- Produces: `save_raw_data(data: dict, output_path: str) -> None` — writes `data` as JSON to `output_path`, creating parent directories as needed.
- Produces: `main(config_path: str) -> None` — reads `BEA_API_KEY` from the environment and BEA params from the config at `config_path` (see Task 4 for `configs/etl_config.yaml`'s shape), calls the two functions above.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_etl.py`:

```python
"""Unit tests for the GDP ETL pipeline (extract, transform, load)."""

import json
from unittest.mock import MagicMock, patch

import pandas as pd


class TestExtract:
    @patch("requests.get")
    def test_fetch_nipa_data_builds_correct_request(self, mock_get):
        mock_response = MagicMock()
        mock_response.json.return_value = {"BEAAPI": {"Results": {"Data": []}}}
        mock_get.return_value = mock_response

        from src.etl.extract import fetch_nipa_data

        result = fetch_nipa_data(
            user_id="test-key", table_name="T10101", frequency="Q", year="X"
        )

        mock_get.assert_called_once()
        _, kwargs = mock_get.call_args
        assert kwargs["params"]["UserID"] == "test-key"
        assert kwargs["params"]["TableName"] == "T10101"
        assert kwargs["params"]["DataSetName"] == "NIPA"
        assert kwargs["params"]["Frequency"] == "Q"
        assert kwargs["params"]["Year"] == "X"
        assert result == {"BEAAPI": {"Results": {"Data": []}}}

    def test_save_raw_data_writes_json(self, tmp_path):
        from src.etl.extract import save_raw_data

        output_path = tmp_path / "nested" / "raw.json"
        save_raw_data({"a": 1}, str(output_path))

        assert json.loads(output_path.read_text()) == {"a": 1}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_etl.py -v`
Expected: `ModuleNotFoundError: No module named 'src.etl'` (both tests in `TestExtract` fail/error)

- [ ] **Step 3: Create the package and implementation**

Create `src/etl/__init__.py` (empty file).

Create `src/etl/extract.py`:

```python
"""Extract GDP (NIPA) data from the BEA (Bureau of Economic Analysis) API."""

import json
import os
import sys

import requests

from src.utils.config import load_config

BEA_API_URL = "https://apps.bea.gov/api/data/"


def fetch_nipa_data(user_id: str, table_name: str, frequency: str, year: str) -> dict:
    """Fetch NIPA data from the BEA API and return the parsed JSON response."""
    params = {
        "UserID": user_id,
        "method": "GetData",
        "DataSetName": "NIPA",
        "TableName": table_name,
        "Frequency": frequency,
        "Year": year,
        "ResultFormat": "JSON",
    }
    response = requests.get(BEA_API_URL, params=params, timeout=30)
    response.raise_for_status()
    return response.json()


def save_raw_data(data: dict, output_path: str) -> None:
    """Write the raw BEA API response to disk as JSON."""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(data, f)


def main(config_path: str) -> None:
    config = load_config(config_path)
    user_id = os.environ["BEA_API_KEY"]
    bea_config = config["bea"]

    data = fetch_nipa_data(
        user_id=user_id,
        table_name=bea_config["table_name"],
        frequency=bea_config["frequency"],
        year=bea_config["year"],
    )
    output_path = config["output"]["raw_data_path"]
    save_raw_data(data, output_path)
    print(f"Saved raw GDP data to {output_path}")


if __name__ == "__main__":
    main(sys.argv[1])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_etl.py -v`
Expected: `TestExtract::test_fetch_nipa_data_builds_correct_request PASSED`, `TestExtract::test_save_raw_data_writes_json PASSED`

- [ ] **Step 5: Add `requests` to `requirements-ci.txt`**

In `requirements-ci.txt`, add a line `requests==2.33.0` in the "Utilities" section (it already has `pyyaml==6.0.1` and `python-dotenv==1.2.2` there).

- [ ] **Step 6: Commit**

```bash
git add src/etl/__init__.py src/etl/extract.py tests/test_etl.py requirements-ci.txt
git commit -m "Add BEA GDP extract module"
```

---

### Task 2: Transform module (`src/etl/transform.py`)

**Files:**
- Create: `src/etl/transform.py`
- Modify: `tests/test_etl.py` (append `TestTransform`)

**Interfaces:**
- Consumes: nothing from Task 1's functions directly, only agrees on the raw JSON shape `fetch_nipa_data` returns (BEA's `{"BEAAPI": {"Results": {"Data": [...]}}}` envelope) and the `output.raw_data_path` / `output.transformed_data_path` config keys defined in Task 4.
- Produces: `parse_nipa_response(raw: dict) -> pd.DataFrame` — returns a DataFrame with columns `["period", "series_code", "series_name", "table_name", "value"]`. This is what Task 3's `load` module consumes (via the CSV it's written to).
- Produces: `main(config_path: str) -> None` — reads the raw JSON from `config["output"]["raw_data_path"]`, writes the tidy DataFrame as CSV to `config["output"]["transformed_data_path"]`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_etl.py`:

```python
class TestTransform:
    def test_parse_nipa_response_produces_tidy_dataframe(self):
        from src.etl.transform import parse_nipa_response

        raw = {
            "BEAAPI": {
                "Results": {
                    "Data": [
                        {
                            "TableName": "T10101",
                            "SeriesCode": "A191RL",
                            "LineDescription": "Gross domestic product",
                            "TimePeriod": "2023Q1",
                            "DataValue": "3.2",
                        },
                        {
                            "TableName": "T10101",
                            "SeriesCode": "A191RL",
                            "LineDescription": "Gross domestic product",
                            "TimePeriod": "2023Q2",
                            "DataValue": "1,234.5",
                        },
                    ]
                }
            }
        }

        df = parse_nipa_response(raw)

        assert list(df.columns) == [
            "period",
            "series_code",
            "series_name",
            "table_name",
            "value",
        ]
        assert len(df) == 2
        assert df.iloc[0]["period"] == "2023Q1"
        assert df.iloc[0]["value"] == 3.2
        assert df.iloc[1]["value"] == 1234.5  # comma thousands separator stripped
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_etl.py::TestTransform -v`
Expected: `ModuleNotFoundError: No module named 'src.etl.transform'`

- [ ] **Step 3: Write the implementation**

Create `src/etl/transform.py`:

```python
"""Transform raw BEA NIPA JSON into a tidy DataFrame for loading into Postgres."""

import json
import sys

import pandas as pd

from src.utils.config import load_config

TIDY_COLUMNS = ["period", "series_code", "series_name", "table_name", "value"]


def parse_nipa_response(raw: dict) -> pd.DataFrame:
    """Reshape a raw BEA NIPA API response into a tidy DataFrame."""
    records = raw["BEAAPI"]["Results"]["Data"]
    rows = [
        {
            "period": record["TimePeriod"],
            "series_code": record["SeriesCode"],
            "series_name": record["LineDescription"],
            "table_name": record["TableName"],
            "value": float(record["DataValue"].replace(",", "")),
        }
        for record in records
    ]
    return pd.DataFrame(rows, columns=TIDY_COLUMNS)


def main(config_path: str) -> None:
    config = load_config(config_path)
    with open(config["output"]["raw_data_path"]) as f:
        raw = json.load(f)

    df = parse_nipa_response(raw)
    output_path = config["output"]["transformed_data_path"]
    df.to_csv(output_path, index=False)
    print(f"Wrote {len(df)} rows to {output_path}")


if __name__ == "__main__":
    main(sys.argv[1])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_etl.py::TestTransform -v`
Expected: `TestTransform::test_parse_nipa_response_produces_tidy_dataframe PASSED`

- [ ] **Step 5: Commit**

```bash
git add src/etl/transform.py tests/test_etl.py
git commit -m "Add GDP transform module"
```

---

### Task 3: Load module (`src/etl/load.py`)

**Files:**
- Create: `src/etl/load.py`
- Modify: `tests/test_etl.py` (append `TestLoad`)
- Modify: `requirements-ci.txt` (add `psycopg2-binary==2.9.9`)

**Interfaces:**
- Consumes: a `pd.DataFrame` with columns `["period", "series_code", "series_name", "table_name", "value"]`, as produced by `parse_nipa_response` in Task 2 (via the CSV `transform.py` writes).
- Produces: `get_connection() -> psycopg2 connection` — reads `POSTGRES_HOST`, `POSTGRES_PORT` (optional, default `"5432"`), `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` from the environment.
- Produces: `ensure_table(conn, table: str) -> None` — creates the target table if it doesn't exist.
- Produces: `upsert_gdp_data(conn, df: pd.DataFrame, table: str) -> None` — upserts each row on conflict `(period, series_code)`.
- Produces: `main(config_path: str) -> None` — reads `config["database"]["table_name"]` and `config["output"]["transformed_data_path"]`, wires the above together.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_etl.py`:

```python
class TestLoad:
    def test_ensure_table_executes_create_table(self):
        from src.etl.load import ensure_table

        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value.__enter__.return_value = cursor

        ensure_table(conn, "gdp")

        cursor.execute.assert_called_once()
        assert "CREATE TABLE IF NOT EXISTS gdp" in cursor.execute.call_args[0][0]
        conn.commit.assert_called_once()

    def test_upsert_gdp_data_executes_one_upsert_per_row(self):
        from src.etl.load import upsert_gdp_data

        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value.__enter__.return_value = cursor

        df = pd.DataFrame(
            [
                {
                    "period": "2023Q1",
                    "series_code": "A191RL",
                    "series_name": "Gross domestic product",
                    "table_name": "T10101",
                    "value": 3.2,
                }
            ]
        )

        upsert_gdp_data(conn, df, "gdp")

        assert cursor.execute.call_count == 1
        sql, params = cursor.execute.call_args[0]
        assert "ON CONFLICT (period, series_code)" in sql
        assert params == ("2023Q1", "A191RL", "Gross domestic product", "T10101", 3.2)
        conn.commit.assert_called_once()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_etl.py::TestLoad -v`
Expected: `ModuleNotFoundError: No module named 'src.etl.load'`

- [ ] **Step 3: Write the implementation**

Create `src/etl/load.py`:

```python
"""Load tidy GDP data into Postgres."""

import os
import sys

import pandas as pd
import psycopg2

from src.utils.config import load_config

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS {table} (
    period TEXT NOT NULL,
    series_code TEXT NOT NULL,
    series_name TEXT,
    table_name TEXT,
    value NUMERIC,
    loaded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (period, series_code)
);
"""

UPSERT_SQL = """
INSERT INTO {table} (period, series_code, series_name, table_name, value)
VALUES (%s, %s, %s, %s, %s)
ON CONFLICT (period, series_code) DO UPDATE SET
    series_name = EXCLUDED.series_name,
    table_name = EXCLUDED.table_name,
    value = EXCLUDED.value,
    loaded_at = now();
"""


def get_connection():
    return psycopg2.connect(
        host=os.environ["POSTGRES_HOST"],
        port=os.environ.get("POSTGRES_PORT", "5432"),
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
        dbname=os.environ["POSTGRES_DB"],
    )


def ensure_table(conn, table: str) -> None:
    with conn.cursor() as cur:
        cur.execute(CREATE_TABLE_SQL.format(table=table))
    conn.commit()


def upsert_gdp_data(conn, df: pd.DataFrame, table: str) -> None:
    with conn.cursor() as cur:
        for row in df.itertuples(index=False):
            cur.execute(
                UPSERT_SQL.format(table=table),
                (row.period, row.series_code, row.series_name, row.table_name, row.value),
            )
    conn.commit()


def main(config_path: str) -> None:
    config = load_config(config_path)
    table = config["database"]["table_name"]
    df = pd.read_csv(config["output"]["transformed_data_path"])

    conn = get_connection()
    try:
        ensure_table(conn, table)
        upsert_gdp_data(conn, df, table)
    finally:
        conn.close()
    print(f"Loaded {len(df)} rows into {table}")


if __name__ == "__main__":
    main(sys.argv[1])
```

Note: `table` is interpolated via `.format()` rather than a `%s` placeholder because psycopg2 cannot parameterize identifiers (table names) — this is safe here because `table` comes only from the repo's own `configs/etl_config.yaml`, never from external input.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_etl.py::TestLoad -v`
Expected: `TestLoad::test_ensure_table_executes_create_table PASSED`, `TestLoad::test_upsert_gdp_data_executes_one_upsert_per_row PASSED`

- [ ] **Step 5: Add `psycopg2-binary` to `requirements-ci.txt`**

In `requirements-ci.txt`, add `psycopg2-binary==2.9.9` (there isn't a dedicated "Database" section like in `requirements.txt` — add it near `requests` in the Utilities section).

- [ ] **Step 6: Run the full test suite**

Run: `pytest tests/test_etl.py -v`
Expected: all 5 tests pass (`TestExtract` x2, `TestTransform` x1, `TestLoad` x2)

- [ ] **Step 7: Commit**

```bash
git add src/etl/load.py tests/test_etl.py requirements-ci.txt
git commit -m "Add GDP load module"
```

---

### Task 4: ETL config, Dockerfile, and requirements

**Files:**
- Create: `configs/etl_config.yaml`
- Create: `etl/requirements.txt`
- Create: `etl/Dockerfile`

**Interfaces:**
- Produces: `configs/etl_config.yaml`, whose keys (`bea.table_name`, `bea.frequency`, `bea.year`, `output.raw_data_path`, `output.transformed_data_path`, `database.table_name`) are exactly what `src/etl/extract.py`, `src/etl/transform.py`, and `src/etl/load.py` (Tasks 1-3) read via `load_config()`.
- Produces: the `mlpipeline-etl:1.0.0` Docker image, referenced by `dags/gdp_etl_dag.py` in Task 5.

- [ ] **Step 1: Create the ETL config**

Create `configs/etl_config.yaml`:

```yaml
bea:
  dataset_name: "NIPA"
  table_name: "T10101"
  frequency: "Q"
  year: "X"  # "X" requests all available years, per the BEA API convention

output:
  raw_data_path: "/data/etl/raw_gdp.json"
  transformed_data_path: "/data/etl/gdp_tidy.csv"

database:
  table_name: "gdp"
```

- [ ] **Step 2: Create the ETL image's requirements file**

Create `etl/requirements.txt`:

```
requests==2.33.0
pandas==2.1.4
psycopg2-binary==2.9.9
pyyaml==6.0.1
```

- [ ] **Step 3: Create the Dockerfile**

Create `etl/Dockerfile`:

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY etl/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ /app/src/
COPY configs/ /app/configs/

RUN groupadd -r appuser && useradd -r -g appuser appuser \
    && chown -R appuser:appuser /app

USER appuser
```

- [ ] **Step 4: Verify the image builds**

Run (from repo root): `docker build -t mlpipeline-etl:1.0.0 -f etl/Dockerfile .`
Expected: build completes with `Successfully tagged mlpipeline-etl:1.0.0` (or the final "naming to docker.io/library/mlpipeline-etl:1.0.0" line on newer Docker), no errors.

- [ ] **Step 5: Commit**

```bash
git add configs/etl_config.yaml etl/requirements.txt etl/Dockerfile
git commit -m "Add GDP ETL config, Dockerfile, and requirements"
```

---

### Task 5: The `gdp_etl` DAG

**Files:**
- Create: `dags/gdp_etl_dag.py`

**Interfaces:**
- Consumes: `mlpipeline-etl:1.0.0` image (Task 4), `configs/etl_config.yaml` (Task 4), `src/etl/{extract,transform,load}.py` entry points (Tasks 1-3), the `mlpipeline-etl-data` PVC and `bea-api-credentials` Secret (Task 6), and the existing `mlpipeline-postgres-credentials` Secret already deployed in the cluster.

- [ ] **Step 1: Write the DAG**

Create `dags/gdp_etl_dag.py`:

```python
"""
Apache Airflow DAG for the GDP ETL pipeline.

Extracts US GDP (NIPA) data from the BEA API, transforms it into a tidy
format with pandas, and loads it into the mlpipeline-postgres database.
Independent of the sentiment training/inference pipeline.
"""

from datetime import datetime, timedelta

from airflow import DAG
from airflow.providers.cncf.kubernetes.operators.pod import KubernetesPodOperator
from kubernetes.client import models as k8s

default_args = {
    "owner": "mlpipeline",
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
    "email_on_failure": False,
}

dag = DAG(
    "gdp_etl",
    default_args=default_args,
    description="Extract, transform, and load GDP data from the BEA API into Postgres",
    schedule="@weekly",
    start_date=datetime(2026, 1, 1),
    catchup=False,
    tags=["etl", "gdp", "postgres"],
)

# git-sync mounts the repo under the dags PVC: /opt/airflow/dags/repo/
NAMESPACE = "mlpipeline"
REPO_PATH = "/opt/airflow/dags/repo"
CONFIG_PATH = f"{REPO_PATH}/configs/etl_config.yaml"

ETL_IMAGE = "mlpipeline-etl:1.0.0"
ETL_DATA_PVC = "mlpipeline-etl-data"


def _etl_data_volume():
    return k8s.V1Volume(
        name="etl-data",
        persistent_volume_claim=k8s.V1PersistentVolumeClaimVolumeSource(
            claim_name=ETL_DATA_PVC
        ),
    )


def _etl_data_mount():
    return k8s.V1VolumeMount(name="etl-data", mount_path="/data/etl")


extract_task = KubernetesPodOperator(
    task_id="extract_gdp_data",
    namespace=NAMESPACE,
    image=ETL_IMAGE,
    image_pull_policy="IfNotPresent",
    cmds=["python"],
    arguments=["/app/src/etl/extract.py", CONFIG_PATH],
    env_from=[
        k8s.V1EnvFromSource(
            secret_ref=k8s.V1SecretEnvSource(name="bea-api-credentials")
        )
    ],
    name="extract-gdp-data-pod",
    in_cluster=True,
    get_logs=True,
    volumes=[_etl_data_volume()],
    volume_mounts=[_etl_data_mount()],
    dag=dag,
)

transform_task = KubernetesPodOperator(
    task_id="transform_gdp_data",
    namespace=NAMESPACE,
    image=ETL_IMAGE,
    image_pull_policy="IfNotPresent",
    cmds=["python"],
    arguments=["/app/src/etl/transform.py", CONFIG_PATH],
    name="transform-gdp-data-pod",
    in_cluster=True,
    get_logs=True,
    volumes=[_etl_data_volume()],
    volume_mounts=[_etl_data_mount()],
    dag=dag,
)

load_task = KubernetesPodOperator(
    task_id="load_gdp_data",
    namespace=NAMESPACE,
    image=ETL_IMAGE,
    image_pull_policy="IfNotPresent",
    cmds=["python"],
    arguments=["/app/src/etl/load.py", CONFIG_PATH],
    env=[k8s.V1EnvVar(name="POSTGRES_HOST", value="mlpipeline-postgres")],
    env_from=[
        k8s.V1EnvFromSource(
            secret_ref=k8s.V1SecretEnvSource(name="mlpipeline-postgres-credentials")
        )
    ],
    name="load-gdp-data-pod",
    in_cluster=True,
    get_logs=True,
    volumes=[_etl_data_volume()],
    volume_mounts=[_etl_data_mount()],
    dag=dag,
)

extract_task >> transform_task >> load_task
```

- [ ] **Step 2: Verify the DAG parses without import errors**

This mirrors the `validate-dags` job in `.github/workflows/ci.yml`. Run:

```bash
python -m venv /tmp/dag-check-venv
source /tmp/dag-check-venv/bin/activate
pip install \
  "apache-airflow==3.0.0" \
  "apache-airflow-providers-cncf-kubernetes" \
  "apache-airflow-providers-standard" \
  --constraint "https://raw.githubusercontent.com/apache/airflow/constraints-3.0.0/constraints-3.11.txt"
export AIRFLOW__CORE__DAGS_FOLDER="$(pwd)/dags"
export AIRFLOW__DATABASE__SQL_ALCHEMY_CONN="sqlite:////tmp/airflow-dag-check.db"
airflow db migrate
airflow dags list-import-errors
deactivate
rm -rf /tmp/dag-check-venv /tmp/airflow-dag-check.db
```

Expected: `airflow dags list-import-errors` prints no errors for `gdp_etl_dag.py` (empty table or a table without a `gdp_etl_dag.py` row).

- [ ] **Step 3: Commit**

```bash
git add dags/gdp_etl_dag.py
git commit -m "Add gdp_etl DAG"
```

---

### Task 6: Kubernetes manifests (PVC + BEA API key Secret)

**Files:**
- Create: `kubernetes/etl-pvc.yaml`
- Create: `kubernetes/etl-secret.yaml`

**Interfaces:**
- Produces: the `mlpipeline-etl-data` PVC and `bea-api-credentials` Secret that `dags/gdp_etl_dag.py` (Task 5) references by name.

- [ ] **Step 1: Create the PVC manifest**

Create `kubernetes/etl-pvc.yaml`:

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: mlpipeline-etl-data
  namespace: mlpipeline
  labels:
    app.kubernetes.io/name: mlpipeline
    app.kubernetes.io/component: etl
spec:
  accessModes:
    - ReadWriteOnce
  storageClassName: standard
  resources:
    requests:
      storage: 1Gi
```

- [ ] **Step 2: Create the Secret manifest**

Create `kubernetes/etl-secret.yaml`:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: bea-api-credentials
  namespace: mlpipeline
  labels:
    app.kubernetes.io/name: mlpipeline
    app.kubernetes.io/component: etl
type: Opaque
stringData:
  BEA_API_KEY: "REPLACE_WITH_YOUR_BEA_USERID_KEY"
```

**Before this file is merged to `main`**, replace `REPLACE_WITH_YOUR_BEA_USERID_KEY` with your real BEA `UserID` API key — the same convention this repo already uses for other secrets in `kubernetes/postgres-secret.yaml` (e.g. `airflow_client_secret_change_me`).

- [ ] **Step 3: Validate the manifests client-side**

Run: `kubectl apply --dry-run=client -f kubernetes/etl-pvc.yaml -f kubernetes/etl-secret.yaml`
Expected: `persistentvolumeclaim/mlpipeline-etl-data created (dry run)` and `secret/bea-api-credentials created (dry run)` — this only validates against the client's schema, it does not touch the live cluster (per this repo's rule that ArgoCD, not `kubectl apply`, owns cluster state).

- [ ] **Step 4: Commit**

```bash
git add kubernetes/etl-pvc.yaml kubernetes/etl-secret.yaml
git commit -m "Add PVC and BEA API key Secret for GDP ETL pipeline"
```

---

### Task 7: Full verification and PR

**Files:** none (verification only)

- [ ] **Step 1: Run the full test suite with coverage**

Run: `pytest tests/ --cov=src --cov=serving -v`
Expected: all tests pass, including the 5 new tests in `tests/test_etl.py`

- [ ] **Step 2: Run lint**

Run: `ruff check src/ serving/ dags/ tests/ && ruff format --check src/ serving/ dags/ tests/`
Expected: no errors

- [ ] **Step 3: Push the branch and open a PR into `dev`**

Per this repo's branch workflow (`feature/<name>` → `dev` → `main`, both with `--auto`):

```bash
git push -u origin feature/gdp-etl-pipeline
gh pr create --base dev --title "Add GDP ETL pipeline (BEA NIPA -> Postgres)" --body "Implements the design in docs/superpowers/specs/2026-07-08-gdp-etl-pipeline-design.md. Adds a standalone gdp_etl DAG: extract (BEA NIPA API) -> transform (pandas) -> load (upsert into the existing mlpipeline-postgres instance)."
gh pr merge <number> --merge --auto
```

Remember to replace the `BEA_API_KEY` placeholder in `kubernetes/etl-secret.yaml` (Task 6) with a real key before this PR is merged to `main` and ArgoCD syncs it — otherwise `extract_gdp_data` will fail with a BEA API authentication error the first time the DAG runs.
