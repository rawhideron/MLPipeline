"""
Apache Airflow DAG for batch inference pipeline.

This DAG runs inference on new data using the trained model.
"""

from datetime import datetime, timedelta

from airflow import DAG
from airflow.providers.standard.operators.python import PythonOperator
from airflow.providers.cncf.kubernetes.operators.pod import KubernetesPodOperator
from kubernetes.client import models as k8s

default_args = {
    "owner": "mlpipeline",
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
}

dag = DAG(
    "mlpipeline_inference",
    default_args=default_args,
    description="Batch inference pipeline for sentiment classification",
    schedule="@daily",
    start_date=datetime(2026, 1, 1),
    catchup=False,
    tags=["ml", "inference", "nlp"],
)

NAMESPACE = "mlpipeline"
IMAGE = "mlpipeline-training:1.0.4"

log_start = PythonOperator(
    task_id="log_inference_start",
    python_callable=lambda: print("Starting batch inference pipeline"),
    dag=dag,
)

inference_task = KubernetesPodOperator(
    task_id="run_batch_inference",
    namespace=NAMESPACE,
    image=IMAGE,
    image_pull_policy="IfNotPresent",
    cmds=["python", "-c"],
    arguments=[
        """
import sys
sys.path.insert(0, "/app")
from src.models.inference import SentimentPredictor

predictor = SentimentPredictor("/models/trained_model")

test_texts = [
    "This product exceeded all my expectations!",
    "Not recommended, poor quality.",
    "Average product, nothing special.",
]

results = predictor.predict_batch(test_texts)

import json
output_path = "/models/predictions.json"
with open(output_path, "w") as f:
    json.dump(results, f, indent=2)

print(f"Processed {len(results)} predictions — saved to {output_path}")
for text, result in zip(test_texts, results):
    print(f"{result['label']} ({result['confidence']:.2f}) | {text[:60]}")
"""
    ],
    name="inference-pod",
    in_cluster=True,
    get_logs=True,
    volume_mounts=[k8s.V1VolumeMount(name="models", mount_path="/models")],
    volumes=[
        k8s.V1Volume(
            name="models",
            persistent_volume_claim=k8s.V1PersistentVolumeClaimVolumeSource(
                claim_name="mlpipeline-serving-models"
            ),
        )
    ],
    dag=dag,
)

log_completion = PythonOperator(
    task_id="log_inference_complete",
    python_callable=lambda: print("Inference pipeline completed"),
    dag=dag,
)

log_start >> inference_task >> log_completion
