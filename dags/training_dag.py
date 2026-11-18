"""
Apache Airflow DAG for ML model training pipeline.

This DAG orchestrates the following steps:
1. Data validation - verifies IMDB dataset is accessible from HuggingFace Hub
2. Data preprocessing - runs text cleaning on a sample batch to verify the pipeline
3. Model training - fine-tunes distilbert-base-uncased on IMDB sentiment data
   (the ragpipeline Ollama server is scaled to 0 around it to free the GPU)
4. Model evaluation - loads and verifies the trained model
5. Pipeline completion log
"""

import logging
from datetime import UTC, datetime, timedelta

import yaml
from airflow import DAG
from airflow.operators.trigger_dagrun import TriggerDagRunOperator
from airflow.providers.cncf.kubernetes.operators.pod import KubernetesPodOperator
from airflow.providers.standard.operators.python import PythonOperator
from gpu_training import (
    gpu_training_pod_kwargs,
    models_mount,
    models_volume,
    pause_rag_ollama,
    resume_rag_ollama,
)
from kubernetes.client import models as k8s

logger = logging.getLogger(__name__)

default_args = {
    "owner": "mlpipeline",
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
    "email_on_failure": False,
}

dag = DAG(
    "mlpipeline_training",
    default_args=default_args,
    description="End-to-end NLP model training pipeline",
    schedule="@weekly",
    start_date=datetime(2026, 1, 1, tzinfo=UTC),
    catchup=False,
    # Only one physical GPU exists; never let two runs compete for it.
    max_active_runs=1,
    tags=["ml", "training", "nlp"],
)

# git-sync mounts the repo under the dags PVC: /opt/airflow/dags/repo/
NAMESPACE = "mlpipeline"
REPO_PATH = "/opt/airflow/dags/repo"
CONFIG_PATH = f"{REPO_PATH}/configs/training_config.yaml"
MODEL_PATH = "/models/trained_model"

# Custom image built from training/Dockerfile — has torch, transformers, datasets
TRAINING_IMAGE = "kind-registry:5000/mlpipeline-training:1.0.7"

# PVC names match the Helm Release.Name prefix (mlpipeline-airflow)
DAGS_PVC = "mlpipeline-airflow-dags"


def log_pipeline_start():
    with open(CONFIG_PATH) as f:
        config = yaml.safe_load(f)
    logger.info("Starting training pipeline with config: %s", config["model"]["name"])


log_start_task = PythonOperator(
    task_id="log_pipeline_start",
    python_callable=log_pipeline_start,
    dag=dag,
)

# Validate that the IMDB dataset is reachable from HuggingFace Hub before training
data_validation_task = KubernetesPodOperator(
    task_id="validate_data",
    namespace=NAMESPACE,
    image=TRAINING_IMAGE,
    image_pull_policy="IfNotPresent",
    cmds=["python"],
    arguments=[
        "-c",
        (
            "from datasets import load_dataset\n"
            "print('Checking IMDB dataset accessibility...')\n"
            "ds = load_dataset('stanfordnlp/imdb',split='train[:100]')\n"
            "assert 'text' in ds.features, \"Missing 'text' column\"\n"
            "assert 'label' in ds.features, \"Missing 'label' column\"\n"
            "assert len(ds) == 100\n"
            "print(f'Validation passed: {len(ds)} examples, columns: {list(ds.features)}')\n"
        ),
    ],
    name="data-validation-pod",
    in_cluster=True,
    get_logs=True,
    dag=dag,
)

# Run text cleaning on a sample to verify the preprocessing module is functional
preprocessing_task = KubernetesPodOperator(
    task_id="preprocess_data",
    namespace=NAMESPACE,
    image=TRAINING_IMAGE,
    image_pull_policy="IfNotPresent",
    cmds=["python"],
    arguments=[
        "-c",
        (
            "import sys\n"
            "sys.path.insert(0, '/app')\n"
            "from src.preprocessing.text_cleaning import preprocess_batch\n"
            "from datasets import load_dataset\n"
            "print('Loading sample data for preprocessing check...')\n"
            "ds = load_dataset('stanfordnlp/imdb',split='train[:50]')\n"
            "cleaned = preprocess_batch(ds['text'], clean=True)\n"
            "assert len(cleaned) == 50\n"
            "print(f'Preprocessing passed: {len(cleaned)} texts cleaned')\n"
        ),
    ],
    name="preprocess-pod",
    in_cluster=True,
    get_logs=True,
    dag=dag,
)

# Fine-tune distilbert; saves model to /models/trained_model on the shared PVC
training_task = KubernetesPodOperator(
    task_id="train_model",
    namespace=NAMESPACE,
    image=TRAINING_IMAGE,
    image_pull_policy="IfNotPresent",
    cmds=["python"],
    arguments=["/app/src/models/training.py", "/app/configs/training_config.yaml"],
    name="training-pod",
    in_cluster=True,
    get_logs=True,
    env_vars=[
        # mlflow's local filesystem backend ("mlruns", the default here) is in
        # maintenance mode as of mlflow 3.x and refuses to run without this --
        # there's no tracking server/database configured for this pipeline, so
        # opting into the (still-supported) file store preserves prior behavior.
        k8s.V1EnvVar(name="MLFLOW_ALLOW_FILE_STORE", value="true"),
    ],
    **gpu_training_pod_kwargs(),
    dag=dag,
)

# Load the saved model from the shared PVC to verify it was written correctly
evaluation_task = KubernetesPodOperator(
    task_id="evaluate_model",
    namespace=NAMESPACE,
    image=TRAINING_IMAGE,
    image_pull_policy="IfNotPresent",
    cmds=["python"],
    arguments=["/app/src/models/evaluation.py", "/models/trained_model"],
    name="evaluation-pod",
    in_cluster=True,
    get_logs=True,
    volumes=[models_volume()],
    volume_mounts=[models_mount()],
    dag=dag,
)


def log_pipeline_complete():
    logger.info("Training pipeline completed successfully")


pause_rag_ollama_task = PythonOperator(
    task_id="pause_rag_ollama",
    python_callable=pause_rag_ollama,
    # A retry would record the already-paused replica count (0) and resume
    # would then leave Ollama down.
    retries=0,
    dag=dag,
)

# all_done: give the GPU back to Ollama whether or not training succeeded.
resume_rag_ollama_task = PythonOperator(
    task_id="resume_rag_ollama",
    python_callable=resume_rag_ollama,
    trigger_rule="all_done",
    dag=dag,
)

log_completion_task = PythonOperator(
    task_id="log_pipeline_complete",
    python_callable=log_pipeline_complete,
    dag=dag,
)

trigger_inference_task = TriggerDagRunOperator(
    task_id="trigger_inference",
    trigger_dag_id="mlpipeline_inference",
    wait_for_completion=False,
    dag=dag,
)

# Task dependencies
(
    log_start_task
    >> data_validation_task
    >> preprocessing_task
    >> pause_rag_ollama_task
    >> training_task
    >> evaluation_task
    >> log_completion_task
    >> trigger_inference_task
)
training_task >> resume_rag_ollama_task
