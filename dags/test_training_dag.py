"""
Test training DAG — runs a quick fine-tune of distilbert on a small IMDB sample.

Steps:
  1. validate_environment  — confirms Python/torch/transformers are importable
  2. download_data         — downloads a 200-sample slice of the IMDB dataset
  3. pause_rag_ollama      — scales the ragpipeline Ollama server to 0 to free the GPU
  4. train_model           — fine-tunes distilbert for 1 epoch on the GPU,
                             saves to /models/test_trained_model
  5. resume_rag_ollama     — restores Ollama whether or not training succeeded
  6. evaluate_model        — runs accuracy check on a held-out slice
  7. log_complete          — prints a summary
  8. trigger_test_inference — triggers mlpipeline_test_inference

The training script and data size stay small, but the image, GPU scheduling, Ollama
hand-off, retries and pod settings are the ones dags/training_dag.py (mlpipeline_training)
uses, shared through dags/gpu_training.py.

Run manually from the Airflow UI: DAGs → mlpipeline_test_training → Trigger DAG
"""

import logging
from datetime import UTC, datetime, timedelta

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

logger = logging.getLogger(__name__)

NAMESPACE = "mlpipeline"
# Same image as mlpipeline_training (dags/training_dag.py TRAINING_IMAGE)
IMAGE = "kind-registry:5000/mlpipeline-training:1.0.7"

default_args = {
    "owner": "mlpipeline",
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
    "email_on_failure": False,
}

dag = DAG(
    "mlpipeline_test_training",
    default_args=default_args,
    description="Quick training test — 1 epoch on 200 IMDB samples",
    schedule=None,  # manual trigger only
    start_date=datetime(2026, 1, 1, tzinfo=UTC),
    catchup=False,
    # Only one physical GPU exists; never let two runs compete for it.
    max_active_runs=1,
    tags=["test", "training"],
)


validate_task = KubernetesPodOperator(
    task_id="validate_environment",
    namespace=NAMESPACE,
    image=IMAGE,
    image_pull_policy="IfNotPresent",
    cmds=["python", "-c"],
    arguments=[
        (
            "import torch, transformers, datasets; "
            "print(f'torch={torch.__version__} transformers={transformers.__version__}'); "
            "print('Environment OK')"
        )
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
ds = load_dataset("stanfordnlp/imdb", split="train[:200]")
ds.save_to_disk("/models/test_data")
print(f"Downloaded {len(ds)} samples to /models/test_data")
"""
    ],
    name="download-data",
    in_cluster=True,
    get_logs=True,
    volumes=[models_volume()],
    volume_mounts=[models_mount()],
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
    output_dir="/models/test_trained_model",
    num_train_epochs=1,
    per_device_train_batch_size=8,
    per_device_eval_batch_size=8,
    eval_strategy="epoch",
    save_strategy="epoch",
    load_best_model_at_end=True,
    use_cpu=not torch.cuda.is_available(),
    report_to="none",
)

trainer = Trainer(model=model, args=args, train_dataset=ds["train"], eval_dataset=ds["test"])
trainer.train()
trainer.save_model("/models/test_trained_model")
tokenizer.save_pretrained("/models/test_trained_model")
print("Model saved to /models/test_trained_model")
"""
    ],
    name="train-model",
    in_cluster=True,
    get_logs=True,
    **gpu_training_pod_kwargs(),
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
    model="/models/test_trained_model",
    tokenizer="/models/test_trained_model",
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
    volumes=[models_volume()],
    volume_mounts=[models_mount()],
    dag=dag,
)

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

log_complete = PythonOperator(
    task_id="log_complete",
    python_callable=lambda: print(
        "Test training pipeline complete — model at /models/test_trained_model"
    ),
    dag=dag,
)

trigger_test_inference = TriggerDagRunOperator(
    task_id="trigger_test_inference",
    trigger_dag_id="mlpipeline_test_inference",
    conf={"training_run_id": "{{ run_id }}"},
    wait_for_completion=False,
    dag=dag,
)

(
    validate_task
    >> download_task
    >> pause_rag_ollama_task
    >> train_task
    >> evaluate_task
    >> log_complete
    >> trigger_test_inference
)
train_task >> resume_rag_ollama_task
