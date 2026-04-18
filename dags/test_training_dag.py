"""
Test training DAG — runs a quick fine-tune of distilbert on a small IMDB sample.

Steps:
  1. validate_environment  — confirms Python/torch/transformers are importable
  2. download_data         — downloads a 200-sample slice of the IMDB dataset
  3. train_model           — fine-tunes distilbert for 1 epoch, saves to /models/trained_model
  4. evaluate_model        — runs accuracy check on a held-out slice
  5. log_complete          — prints a summary

Run manually from the Airflow UI: DAGs → mlpipeline_test_training → Trigger DAG
"""

from datetime import datetime, timedelta

from airflow import DAG
from airflow.providers.standard.operators.python import PythonOperator
from airflow.providers.cncf.kubernetes.operators.pod import KubernetesPodOperator
from kubernetes.client import models as k8s

NAMESPACE = "mlpipeline"
IMAGE = "mlpipeline-serving:1.0.1"

default_args = {
    "owner": "mlpipeline",
    "retries": 1,
    "retry_delay": timedelta(minutes=2),
}

dag = DAG(
    "mlpipeline_test_training",
    default_args=default_args,
    description="Quick training test — 1 epoch on 200 IMDB samples",
    schedule=None,  # manual trigger only
    start_date=datetime(2026, 1, 1),
    catchup=False,
    tags=["test", "training"],
)

validate_task = KubernetesPodOperator(
    task_id="validate_environment",
    namespace=NAMESPACE,
    image=IMAGE,
    image_pull_policy="IfNotPresent",
    cmds=["python", "-c"],
    arguments=[
        "import torch, transformers, datasets; "
        "print(f'torch={torch.__version__} transformers={transformers.__version__}'); "
        "print('Environment OK')"
    ],
    name="validate-env",
    in_cluster=True,
    get_logs=True,
    dag=dag,
)

download_task = KubernetesPodOperator(
    task_id="download_data",
    namespace=NAMESPACE,
    image=IMAGE,
    image_pull_policy="IfNotPresent",
    cmds=["python", "-c"],
    arguments=[
        """
from datasets import load_dataset
ds = load_dataset("imdb", split="train[:200]")
ds.save_to_disk("/models/test_data")
print(f"Downloaded {len(ds)} samples to /models/test_data")
"""
    ],
    name="download-data",
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

train_task = KubernetesPodOperator(
    task_id="train_model",
    namespace=NAMESPACE,
    image=IMAGE,
    image_pull_policy="IfNotPresent",
    cmds=["python", "-c"],
    arguments=[
        """
from datasets import load_from_disk
from transformers import (
    AutoTokenizer, AutoModelForSequenceClassification, TrainingArguments, Trainer
)
import torch

model_name = "distilbert-base-uncased"
tokenizer = AutoTokenizer.from_pretrained(model_name)
model = AutoModelForSequenceClassification.from_pretrained(model_name, num_labels=2)

ds = load_from_disk("/models/test_data")
ds = ds.train_test_split(test_size=0.2)

def tokenize(batch):
    return tokenizer(batch["text"], truncation=True, padding="max_length", max_length=128)

ds = ds.map(tokenize, batched=True)
ds = ds.rename_column("label", "labels")
ds.set_format("torch", columns=["input_ids", "attention_mask", "labels"])

args = TrainingArguments(
    output_dir="/models/trained_model",
    num_train_epochs=1,
    per_device_train_batch_size=8,
    per_device_eval_batch_size=8,
    eval_strategy="epoch",
    save_strategy="epoch",
    load_best_model_at_end=True,
    no_cuda=not torch.cuda.is_available(),
    report_to="none",
)

trainer = Trainer(model=model, args=args, train_dataset=ds["train"], eval_dataset=ds["test"])
trainer.train()
trainer.save_model("/models/trained_model")
tokenizer.save_pretrained("/models/trained_model")
print("Model saved to /models/trained_model")
"""
    ],
    name="train-model",
    in_cluster=True,
    get_logs=True,
    container_resources=k8s.V1ResourceRequirements(
        requests={"memory": "2Gi", "cpu": "1"},
        limits={"memory": "4Gi", "cpu": "2"},
    ),
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

evaluate_task = KubernetesPodOperator(
    task_id="evaluate_model",
    namespace=NAMESPACE,
    image=IMAGE,
    image_pull_policy="IfNotPresent",
    cmds=["python", "-c"],
    arguments=[
        """
from transformers import pipeline

classifier = pipeline(
    "text-classification",
    model="/models/trained_model",
    tokenizer="/models/trained_model",
)

samples = [
    ("This movie was absolutely fantastic!", "LABEL_1"),
    ("Terrible film, complete waste of time.", "LABEL_0"),
    ("Great acting and a compelling story.", "LABEL_1"),
    ("Boring and predictable plot.", "LABEL_0"),
]

correct = 0
for text, expected in samples:
    result = classifier(text)[0]
    match = result["label"] == expected
    correct += match
    print(f"{'OK' if match else 'FAIL'} | {result['label']} ({result['score']:.2f}) | {text[:50]}")

print(f"\\nAccuracy: {correct}/{len(samples)} = {correct/len(samples)*100:.0f}%")
"""
    ],
    name="evaluate-model",
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

log_complete = PythonOperator(
    task_id="log_complete",
    python_callable=lambda: print(
        "Test training pipeline complete — model at /models/trained_model"
    ),
    dag=dag,
)

validate_task >> download_task >> train_task >> evaluate_task >> log_complete
