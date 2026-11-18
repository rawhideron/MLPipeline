"""
Shared GPU-training helpers for mlpipeline_training and mlpipeline_test_training.

Airflow 3 appends the dag bundle path (the dags folder) to sys.path in both the
DAG processor and the task runner, so the DAG files import this module directly.
This file defines no DAG.
"""

import logging
import time

from kubernetes.client import models as k8s

logger = logging.getLogger(__name__)

# PVC name matches the Helm Release.Name prefix
MODELS_PVC = "mlpipeline-serving-models"


def models_volume():
    return k8s.V1Volume(
        name="models",
        persistent_volume_claim=k8s.V1PersistentVolumeClaimVolumeSource(
            claim_name=MODELS_PVC
        ),
    )


def models_mount():
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


def gpu_training_pod_kwargs():
    """KubernetesPodOperator settings for a train_model pod on the shared GPU."""
    return {
        # A full-power GPU run has hard-reset the Zephyrus host; an automatic
        # retry just triggers a second reset, so fail once and wait for a human.
        "retries": 0,
        "max_active_tis_per_dag": 1,
        "container_resources": k8s.V1ResourceRequirements(
            requests={"memory": "1Gi", "cpu": "1", "nvidia.com/gpu": "1"},
            limits={"memory": "2560Mi", "cpu": "2", "nvidia.com/gpu": "1"},
        ),
        "labels": {GPU_EXCLUSIVE_LABEL: "true"},
        "affinity": _gpu_affinity(),
        "tolerations": _gpu_tolerations(),
        # The models PVC had stale root-owned subdirectories from before this
        # image ran as a non-root user; fsGroup keeps future writes consistent
        # regardless of which UID created a given directory first.
        "security_context": k8s.V1PodSecurityContext(fs_group=999),
        "full_pod_spec": k8s.V1Pod(
            spec=k8s.V1PodSpec(
                runtime_class_name="nvidia",
                containers=[k8s.V1Container(name="base")],
            )
        ),
        "volumes": [models_volume()],
        "volume_mounts": [models_mount()],
    }


# The ragpipeline Ollama server (rag/ollama) is a long-running GPU pod under the
# same gpu-exclusive policy, so train_model would stay Pending behind it. Scale
# it to 0 for training and restore it afterwards (RBAC lives in the ragpipeline
# repo, k8s/176/06-ollama-gpu-handoff-rbac.yaml).
RAG_NAMESPACE = "rag"
OLLAMA_DEPLOYMENT = "ollama"
OLLAMA_REPLICAS_XCOM = "ollama_replicas"
OLLAMA_RELEASE_TIMEOUT = 180


def _rag_clients():
    from kubernetes import client, config

    config.load_incluster_config()
    return client.AppsV1Api(), client.CoreV1Api()


def pause_rag_ollama(ti):
    from kubernetes.client.rest import ApiException

    apps, core = _rag_clients()
    try:
        scale = apps.read_namespaced_deployment_scale(OLLAMA_DEPLOYMENT, RAG_NAMESPACE)
    except ApiException as e:
        if e.status == 404:
            logger.info(
                "No %s/%s deployment; nothing to pause",
                RAG_NAMESPACE,
                OLLAMA_DEPLOYMENT,
            )
            return
        raise
    # Record before scaling so resume restores it even if the wait below fails.
    ti.xcom_push(key=OLLAMA_REPLICAS_XCOM, value=scale.spec.replicas or 0)
    apps.patch_namespaced_deployment_scale(
        OLLAMA_DEPLOYMENT, RAG_NAMESPACE, {"spec": {"replicas": 0}}
    )
    deadline = time.monotonic() + OLLAMA_RELEASE_TIMEOUT
    # Finished pods hold no GPU but linger as objects, e.g. one the kubelet
    # rejected with UnexpectedAdmissionError after a node restart; skip them.
    while pods := core.list_namespaced_pod(
        RAG_NAMESPACE,
        label_selector="app=ollama",
        field_selector="status.phase!=Failed,status.phase!=Succeeded",
    ).items:
        if time.monotonic() > deadline:
            names = ", ".join(pod.metadata.name for pod in pods)
            raise TimeoutError(
                f"Ollama pods still present after {OLLAMA_RELEASE_TIMEOUT}s: {names}"
            )
        time.sleep(5)
    logger.info("Ollama scaled from %s to 0; GPU released", scale.spec.replicas)


def resume_rag_ollama(ti):
    replicas = ti.xcom_pull(task_ids="pause_rag_ollama", key=OLLAMA_REPLICAS_XCOM)
    if not replicas:
        logger.info("Ollama was not running before training; leaving it scaled down")
        return
    apps, _ = _rag_clients()
    apps.patch_namespaced_deployment_scale(
        OLLAMA_DEPLOYMENT, RAG_NAMESPACE, {"spec": {"replicas": replicas}}
    )
    logger.info("Ollama scaled back to %s", replicas)
