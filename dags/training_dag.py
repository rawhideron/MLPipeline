"""
Apache Airflow DAG for ML model training pipeline.

This DAG orchestrates the following steps:
1. Data validation - verifies IMDB dataset is accessible from HuggingFace Hub
2. Data preprocessing - runs text cleaning on a sample batch to verify the pipeline
3. Model training - fine-tunes distilbert-base-uncased on IMDB sentiment data
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
TRAINING_IMAGE = "kind-registry:5000/mlpipeline-training:1.0.6"

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


# The single RTX 3070 is exposed through two kind nodes: reunion-worker
# (primary) and reunion-worker2 (secondary), both labelled with GPU_POOL_LABEL.
# The ops/zephyrus/gpu-exclusive-policy.yaml admission policy rejects any GPU
# pod that lacks the label and affinity below.
GPU_EXCLUSIVE_LABEL = "mlpipeline.io/gpu-exclusive"
GPU_POOL_LABEL = "mlpipeline.io/gpu-pool"
GPU_ROLE_LABEL = "mlpipeline.io/gpu-role"


def _gpu_affinity():
    return k8s.V1Affinity(
        # Must land on a GPU-pool node; prefer the primary so the secondary is
        # only used when the primary is down or cordoned.
        node_affinity=k8s.V1NodeAffinity(
            required_during_scheduling_ignored_during_execution=k8s.V1NodeSelector(
                node_selector_terms=[
                    k8s.V1NodeSelectorTerm(
                        match_expressions=[
                            k8s.V1NodeSelectorRequirement(
                                key=GPU_POOL_LABEL, operator="Exists"
                            )
                        ]
                    )
                ]
            ),
            preferred_during_scheduling_ignored_during_execution=[
                k8s.V1PreferredSchedulingTerm(
                    weight=100,
                    preference=k8s.V1NodeSelectorTerm(
                        match_expressions=[
                            k8s.V1NodeSelectorRequirement(
                                key=GPU_ROLE_LABEL, operator="In", values=["primary"]
                            )
                        ]
                    ),
                )
            ],
        ),
        # Every pool node shares the same GPU_POOL_LABEL value, so this keeps a
        # second GPU pod Pending anywhere in the pool while one is running.
        pod_anti_affinity=k8s.V1PodAntiAffinity(
            required_during_scheduling_ignored_during_execution=[
                k8s.V1PodAffinityTerm(
                    label_selector=k8s.V1LabelSelector(
                        match_labels={GPU_EXCLUSIVE_LABEL: "true"}
                    ),
                    topology_key=GPU_POOL_LABEL,
                    namespace_selector=k8s.V1LabelSelector(),
                )
            ]
        ),
    )


def _gpu_tolerations():
    # Evict from a dead node after 30s (default 300s) so a rerun can fail over.
    return [
        k8s.V1Toleration(
            key=key, operator="Exists", effect="NoExecute", toleration_seconds=30
        )
        for key in ("node.kubernetes.io/not-ready", "node.kubernetes.io/unreachable")
    ]


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
    # A full-power GPU run has hard-reset the Zephyrus host; an automatic
    # retry just triggers a second reset, so fail once and wait for a human.
    retries=0,
    max_active_tis_per_dag=1,
    namespace=NAMESPACE,
    image=TRAINING_IMAGE,
    image_pull_policy="IfNotPresent",
    cmds=["python"],
    arguments=["/app/src/models/training.py", "/app/configs/training_config.yaml"],
    name="training-pod",
    in_cluster=True,
    get_logs=True,
    container_resources=k8s.V1ResourceRequirements(
        requests={"memory": "1Gi", "cpu": "1", "nvidia.com/gpu": "1"},
        limits={"memory": "2560Mi", "cpu": "2", "nvidia.com/gpu": "1"},
    ),
    env_vars=[
        # mlflow's local filesystem backend ("mlruns", the default here) is in
        # maintenance mode as of mlflow 3.x and refuses to run without this --
        # there's no tracking server/database configured for this pipeline, so
        # opting into the (still-supported) file store preserves prior behavior.
        k8s.V1EnvVar(name="MLFLOW_ALLOW_FILE_STORE", value="true"),
    ],
    labels={GPU_EXCLUSIVE_LABEL: "true"},
    affinity=_gpu_affinity(),
    tolerations=_gpu_tolerations(),
    # The models PVC had stale root-owned subdirectories from before this
    # image ran as a non-root user; fsGroup keeps future writes consistent
    # regardless of which UID created a given directory first.
    security_context=k8s.V1PodSecurityContext(fs_group=999),
    full_pod_spec=k8s.V1Pod(
        spec=k8s.V1PodSpec(
            runtime_class_name="nvidia",
            containers=[k8s.V1Container(name="base")],
        )
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


def log_pipeline_complete():
    logger.info("Training pipeline completed successfully")


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
    >> training_task
    >> evaluation_task
    >> log_completion_task
    >> trigger_inference_task
)
