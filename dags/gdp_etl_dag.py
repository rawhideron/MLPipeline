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

NAMESPACE = "mlpipeline"
# etl/Dockerfile bakes configs/ into the image at /app/configs/ -- this path
# is inside the mlpipeline-etl container, not the git-synced dags repo.
CONFIG_PATH = "/app/configs/etl_config.yaml"

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
    env_vars=[k8s.V1EnvVar(name="POSTGRES_HOST", value="mlpipeline-postgres")],
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
