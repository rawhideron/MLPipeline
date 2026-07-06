"""
Test inference DAG — calls the live FastAPI serving endpoint with sample texts.

Steps:
  1. health_check    — confirms the serving API is reachable
  2. run_inference   — POSTs sample texts to /api/predict and prints results
  3. log_complete    — prints a summary

Run manually from the Airflow UI: DAGs → mlpipeline_test_inference → Trigger DAG

Requires the serving pod to be running and the model to be loaded
(run mlpipeline_test_training first if model_loaded is false).
"""

import os
from datetime import datetime, timedelta

from airflow import DAG
from airflow.providers.standard.operators.python import PythonOperator
from kubernetes.client import models as k8s

SERVING_URL = os.environ.get("SERVING_URL", "https://mlpipeline.duckdns.org")
KEYCLOAK_REALM_URL = os.environ.get(
    "KEYCLOAK_REALM_URL",
    "https://goodmanreunion.duckdns.org/keycloak/realms/MLPipeline",
)
OAUTH_CLIENT_ID = os.environ.get("OAUTH_CLIENT_ID", "mlpipeline-serving")

default_args = {
    "owner": "mlpipeline",
    "retries": 1,
    "retry_delay": timedelta(minutes=1),
}

dag = DAG(
    "mlpipeline_test_inference",
    default_args=default_args,
    description="Test inference by calling the live FastAPI serving endpoint",
    schedule=None,  # manual trigger only
    start_date=datetime(2026, 1, 1),
    catchup=False,
    tags=["test", "inference"],
)

SAMPLE_TEXTS = [
    "This movie was absolutely fantastic, I loved every minute of it!",
    "Terrible film, complete waste of time and money.",
    "Great acting but the plot was a bit slow in the middle.",
    "One of the best films I have seen in years.",
    "I fell asleep halfway through, very boring.",
]


def health_check():
    import requests

    resp = requests.get(f"{SERVING_URL}/health", timeout=10)
    resp.raise_for_status()
    data = resp.json()
    print(f"Status:       {data['status']}")
    print(f"Model loaded: {data['model_loaded']}")
    print(f"Version:      {data['version']}")
    if not data["model_loaded"]:
        raise ValueError("Model is not loaded — run mlpipeline_test_training first")


def _get_access_token():
    import requests

    resp = requests.post(
        f"{KEYCLOAK_REALM_URL}/protocol/openid-connect/token",
        data={
            "grant_type": "client_credentials",
            "client_id": OAUTH_CLIENT_ID,
            "client_secret": os.environ["OAUTH_CLIENT_SECRET"],
        },
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def run_inference():
    import requests

    headers = {"Authorization": f"Bearer {_get_access_token()}"}
    results = []
    for text in SAMPLE_TEXTS:
        resp = requests.post(
            f"{SERVING_URL}/api/predict",
            json={"text": text},
            headers=headers,
            timeout=30,
        )
        if resp.status_code == 200:
            r = resp.json()
            results.append(r)
            print(f"{r['label']} ({r['confidence']:.2f}) | {text[:60]}")
        else:
            print(f"ERROR {resp.status_code}: {resp.text[:100]} | {text[:60]}")

    print(f"\nCompleted {len(results)}/{len(SAMPLE_TEXTS)} predictions")
    pos = sum(1 for r in results if r["label"] == "POSITIVE")
    neg = sum(1 for r in results if r["label"] == "NEGATIVE")
    print(f"POSITIVE: {pos}  NEGATIVE: {neg}")


health_task = PythonOperator(
    task_id="health_check",
    python_callable=health_check,
    dag=dag,
)

inference_task = PythonOperator(
    task_id="run_inference",
    python_callable=run_inference,
    executor_config={
        "pod_override": k8s.V1Pod(
            spec=k8s.V1PodSpec(
                containers=[
                    k8s.V1Container(
                        name="base",
                        env=[
                            k8s.V1EnvVar(
                                name="OAUTH_CLIENT_SECRET",
                                value_from=k8s.V1EnvVarSource(
                                    secret_key_ref=k8s.V1SecretKeySelector(
                                        name="keycloak-serving-secret",
                                        key="client-secret",
                                    )
                                ),
                            )
                        ],
                    )
                ]
            )
        )
    },
    dag=dag,
)

log_complete = PythonOperator(
    task_id="log_complete",
    python_callable=lambda: print("Test inference pipeline complete"),
    dag=dag,
)

health_task >> inference_task >> log_complete
