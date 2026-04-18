"""
Apache Airflow DAG for batch inference pipeline.

This DAG runs inference on new data using the trained model.
"""

from datetime import datetime, timedelta

from airflow import DAG
from airflow.providers.standard.operators.python import PythonOperator
from airflow.providers.cncf.kubernetes.operators.pod import KubernetesPodOperator

# Default arguments
default_args = {
    "owner": "mlpipeline",
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
}

# DAG definition
dag = DAG(
    "mlpipeline_inference",
    default_args=default_args,
    description="Batch inference pipeline for sentiment classification",
    schedule="@daily",  # Run daily
    start_date=datetime(2026, 1, 1),
    catchup=False,
    tags=["ml", "inference", "nlp"],
)

NAMESPACE = "MLPipeline"


def log_inference_start():
    """Log inference pipeline start."""
    print("Starting batch inference pipeline")


# Python task
log_start = PythonOperator(
    task_id="log_inference_start",
    python_callable=log_inference_start,
    dag=dag,
)

# Kubernetes task for batch inference
inference_task = KubernetesPodOperator(
    task_id="run_batch_inference",
    namespace=NAMESPACE,
    image="pytorch/pytorch:2.0-cuda11.8-runtime-ubuntu22.04",
    cmds=["python"],
    arguments=[
        "-c",
        """
import sys
sys.path.insert(0, "/airflow/dags")
from src.models.inference import SentimentPredictor

predictor = SentimentPredictor("/models/trained_model")

# Load batch data from file
test_texts = [
    "This product exceeded all my expectations!",
    "Not recommended, poor quality.",
    "Average product, nothing special."
]

# Run inference
results = predictor.predict_batch(test_texts)

# Save results
import json
with open("/data/processed/predictions.json", "w") as f:
    json.dump(results, f, indent=2)

print(f"Processed {len(results)} predictions")
""",
    ],
    name="inference-pod",
    in_cluster=True,
    get_logs=True,
    dag=dag,
)

log_completion = PythonOperator(
    task_id="log_inference_complete",
    python_callable=lambda: print("Inference pipeline completed"),
    dag=dag,
)

# Task dependencies
log_start >> inference_task >> log_completion
