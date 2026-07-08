# GDP ETL Pipeline — Design

**Date**: 2026-07-08
**Status**: Approved
**Related issues**: #103 (Create an extract process), #104 (Transform into various formats), #105 (Load into postgres)

## Purpose

Add a standalone ETL pipeline to this repo, separate from the existing sentiment
training/inference pipeline, that pulls US GDP data from the Bureau of Economic
Analysis (BEA) API, reshapes it, and loads it into Postgres. This is a second,
independent demonstration pipeline within the same Airflow/Kubernetes deployment —
it does not feed or depend on `training_dag.py` / `inference_dag.py`.

## Architecture

One new DAG, `gdp_etl`, scheduled `@weekly` (matching the existing `training_dag.py`
cadence), with three `KubernetesPodOperator` tasks chained linearly:

```
extract_gdp_data >> transform_gdp_data >> load_gdp_data
```

This mirrors the task-per-pod structure of `training_dag.py` but is a fully
independent DAG — no `TriggerDagRunOperator` links to or from the training/inference
DAGs.

Extract → transform → load are tightly coupled (there's no case for running one step
without the others), so they live in a single DAG rather than three DAGs chained via
`TriggerDagRunOperator`.

## Data source

**Bureau of Economic Analysis (BEA) API**, NIPA dataset (National Income and Product
Accounts — GDP and its components). Requires a free registered `UserID` API key,
which the user already has.

BEA revises historical figures periodically even though headline data is quarterly;
a weekly schedule catches revisions without being excessive.

## Components

- **`src/etl/extract.py`** — calls the BEA API (NIPA dataset) using a `UserID` API
  key read from an environment variable (sourced from a K8s Secret), writes the raw
  JSON response to a shared PVC.
- **`src/etl/transform.py`** — reads the raw JSON with pandas, reshapes BEA's nested
  table response into a tidy/long format (e.g. `period`, `series_code`, `series_name`,
  `value`), writes the result back to the PVC as an intermediate file. No export to
  multiple external file formats — the only consumer is the load step.
- **`src/etl/load.py`** — reads the transformed file and upserts it into Postgres via
  `psycopg2`: `INSERT ... ON CONFLICT (period, series_code) DO UPDATE`. This makes
  re-runs idempotent and handles BEA's historical revisions by overwriting prior
  values rather than duplicating rows.
- **`dags/gdp_etl_dag.py`** — the DAG wiring the three tasks together, following the
  same `KubernetesPodOperator` + shared-PVC pattern used in `training_dag.py`
  (see `_models_volume()` / `_models_mount()` there for the precedent).
- **`etl/Dockerfile`** — new custom image (`mlpipeline-etl`), analogous to
  `training/Dockerfile` and `serving/Dockerfile`. Needs `requests`, `pandas`,
  `psycopg2-binary`.
- **New PVC** (e.g. `mlpipeline-etl-data`) — shared scratch volume mounted into all
  three task pods, playing the same role as `mlpipeline-serving-models` does for the
  training DAG's model artifact.
- **Existing `mlpipeline-postgres` Postgres instance** (the standalone
  `helm/mlpipeline-postgres` chart/StatefulSet — confirmed live in the cluster but
  currently unused by any application; this is distinct from the separate Postgres
  StatefulSet embedded in `helm/mlpipeline-airflow` that hosts Airflow's own metadata
  DB). The `gdp` table is created in this instance's existing `mlpipeline` database.
  No new database, initdb script, or Secret is needed — the load step reuses the
  existing `mlpipeline-postgres-credentials` Secret (`POSTGRES_USER`,
  `POSTGRES_PASSWORD`, `POSTGRES_DB`, all `mlpipeline`) that the
  `helm/mlpipeline-postgres` chart already creates.
- **New Secret** holding the BEA API `UserID` key, mounted as an env var into the
  `extract_gdp_data` pod.

## Data flow

```
BEA NIPA API
  → raw JSON (written to PVC by extract_gdp_data)
  → pandas reshape (transform_gdp_data reads PVC, writes tidy file to PVC)
  → psycopg2 upsert into Postgres `gdp` table (load_gdp_data reads PVC)
```

## Error handling

Uses the same `default_args` retry policy as the other DAGs in this repo (1 retry,
5 minute delay). No custom cleanup/rollback logic is needed on partial failure: the
load step's upsert makes reruns of the whole DAG safe, and each task only writes to
the PVC on success, so a failed extract or transform simply leaves stale/no
intermediate file and the next scheduled run overwrites it.

## Testing

`tests/test_etl.py`, following the existing convention of one test file per `src/`
module (see `tests/test_preprocessing.py`):

- **Transform**: given a sample BEA-shaped JSON fixture, assert the tidy DataFrame
  output has the expected columns/rows.
- **Load**: mock `psycopg2`, assert the upsert is called with the correct SQL and
  parameters for a given tidy DataFrame.
- **Extract**: mock `requests`, assert the correct URL/params are used and the raw
  response is written to the expected path.

## Out of scope

- Spark and dbt (considered in issue #104, not chosen — dataset is small enough that
  pandas suffices without adding new infrastructure).
- Schema discovery / data catalog tooling (Apache Atlas, Amundsen, Great
  Expectations — considered in issue #103, not part of this pipeline).
- Exporting transformed data to multiple external file formats (CSV/Parquet/etc.) —
  the only downstream consumer is the Postgres load step.
- Feeding this data into the sentiment training/inference pipeline — the two
  pipelines are independent.
