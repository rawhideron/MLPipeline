"""
Apache Airflow DAG for ML model training pipeline.

This DAG orchestrates the following steps:
1. Data validation - verifies IMDB dataset is accessible from HuggingFace Hub
2. Data preprocessing - runs text cleaning on a sample batch to verify the pipeline
3. Model training - fine-tunes distilbert-base-uncased on IMDB sentiment data
4. Model evaluation - loads and verifies the trained model
5. Pipeline completion log
"""

from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.trigger_dagrun import TriggerDagRunOperator
from airflow.providers.cncf.kubernetes.operators.pod import KubernetesPodOperator
from airflow.providers.standard.operators.python import PythonOperator
from kubernetes.client import models as k8s
import yaml

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
    start_date=datetime(2026, 1, 1),
    catchup=False,
    tags=["ml", "training", "nlp"],
)

# git-sync mounts the repo under the dags PVC: /opt/airflow/dags/repo/
NAMESPACE = "mlpipeline"
REPO_PATH = "/opt/airflow/dags/repo"
CONFIG_PATH = f"{REPO_PATH}/configs/training_config.yaml"
MODEL_PATH = "/models/trained_model"

# Custom image built from training/Dockerfile — has torch, transformers, datasets
TRAINING_IMAGE = "mlpipeline-training:1.0.3"

# PVC names match the Helm Release.Name prefix (mlpipeline-airflow)
DAGS_PVC = "mlpipeline-airflow-dags"
MODELS_PVC = "mlpipeline-serving-models"


def _models_volume():
    return k8s.V1Volume(
        name="models",
        persistent_volume_claim=k8s.V1PersistentVolumeClaimVolumeSource(
            claim_name=MODELS_PVC
        ),
    )


def _models_mount():
    return k8s.V1VolumeMount(name="models", mount_path="/models")


def log_pipeline_start():
    with open(CONFIG_PATH) as f:
        config = yaml.safe_load(f)
    print(f"Starting training pipeline with config: {config['model']['name']}")


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
            "ds = load_dataset('imdb', split='train[:100]')\n"
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
            "ds = load_dataset('imdb', split='train[:50]')\n"
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
    container_resources=k8s.V1ResourceRequirements(
        requests={"memory": "4Gi", "cpu": "2"},
        limits={"memory": "8Gi", "cpu": "4"},
    ),
    volumes=[_models_volume()],
    volume_mounts=[_models_mount()],
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
    volumes=[_models_volume()],
    volume_mounts=[_models_mount()],
    dag=dag,
)

log_completion_task = PythonOperator(
    task_id="log_pipeline_complete",
    python_callable=lambda: print("Training pipeline completed successfully"),
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
    >> training_task
    >> evaluation_task
    >> log_completion_task
    >> trigger_inference_task
)
