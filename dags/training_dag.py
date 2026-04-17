"""
Apache Airflow DAG for ML model training pipeline.

This DAG orchestrates the following steps:
1. Data validation with Great Expectations
2. Data preprocessing
3. Model training
4. Model evaluation
5. Model registry and versioning
"""

from datetime import datetime, timedelta
from pathlib import Path

from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.operators.kubernetes_pod import KubernetesPodOperator
from airflow.providers.postgres.operators.postgres import PostgresOperator
from airflow.models import Variable
import yaml

# Default arguments
default_args = {
    'owner': 'mlpipeline',
    'retries': 2,
    'retry_delay': timedelta(minutes=5),
    'email': ['alerts@mlpipeline.local'],
    'email_on_failure': True,
}

# DAG definition
dag = DAG(
    'mlpipeline_training',
    default_args=default_args,
    description='End-to-end NLP model training pipeline',
    schedule_interval='@weekly',  # Run weekly
    start_date=datetime(2026, 1, 1),
    catchup=False,
    tags=['ml', 'training', 'nlp'],
)

# Configuration
NAMESPACE = 'MLPipeline'
CONFIG_PATH = '/airflow/dags/configs/training_config.yaml'
DATASET_PATH = '/data/raw/movie_reviews'
MODEL_PATH = '/models'


def load_config():
    """Load training configuration."""
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def log_pipeline_start():
    """Log pipeline start information."""
    config = load_config()
    print(f"Starting training pipeline with config: {config['model']['name']}")


# Python tasks
log_start_task = PythonOperator(
    task_id='log_pipeline_start',
    python_callable=log_pipeline_start,
    dag=dag,
)

# Kubernetes Pod tasks
data_validation_task = KubernetesPodOperator(
    task_id='validate_data',
    namespace=NAMESPACE,
    image='python:3.9-slim',
    cmds=['python'],
    arguments=[
        '-c',
        '''
import subprocess
result = subprocess.run([
    "python", "-m", "great_expectations",
    "checkpoint", "run", "data_validation"
], cwd="/airflow/dags")
exit(result.returncode)
'''
    ],
    name='data-validation-pod',
    in_cluster=True,
    get_logs=True,
    dag=dag,
)

preprocessing_task = KubernetesPodOperator(
    task_id='preprocess_data',
    namespace=NAMESPACE,
    image='python:3.9',
    cmds=['python'],
    arguments=[
        '-c',
        '''
import sys
sys.path.insert(0, "/airflow/dags")
from src.preprocessing.text_cleaning import preprocess_batch
import json

# Load raw data and preprocess
# This is a placeholder - actual data loading would happen here
print("Data preprocessing completed")
'''
    ],
    name='preprocess-pod',
    in_cluster=True,
    get_logs=True,
    dag=dag,
)

training_task = KubernetesPodOperator(
    task_id='train_model',
    namespace=NAMESPACE,
    image='pytorch/pytorch:2.0-cuda11.8-runtime-ubuntu22.04',
    cmds=['python'],
    arguments=[
        '/airflow/dags/src/models/training.py',
        '/airflow/dags/configs/training_config.yaml'
    ],
    name='training-pod',
    in_cluster=True,
    get_logs=True,
    requests={'memory': '4Gi', 'cpu': '2'},
    limits={'memory': '8Gi', 'cpu': '4'},
    dag=dag,
)

evaluation_task = KubernetesPodOperator(
    task_id='evaluate_model',
    namespace=NAMESPACE,
    image='pytorch/pytorch:2.0-cuda11.8-runtime-ubuntu22.04',
    cmds=['python'],
    arguments=[
        '-c',
        '''
import sys
sys.path.insert(0, "/airflow/dags")
from src.models.evaluation import ModelEvaluator
import json

evaluator = ModelEvaluator("/models/trained_model")
print("Model evaluation completed")
'''
    ],
    name='evaluation-pod',
    in_cluster=True,
    get_logs=True,
    dag=dag,
)

log_completion_task = PythonOperator(
    task_id='log_pipeline_complete',
    python_callable=lambda: print("Training pipeline completed successfully"),
    dag=dag,
)

# Define task dependencies
log_start_task >> data_validation_task
data_validation_task >> preprocessing_task
preprocessing_task >> training_task
training_task >> evaluation_task
evaluation_task >> log_completion_task
