#!/usr/bin/env bash
# Label the kind nodes that share the single RTX 3070 on Zephyrus.
#   reunion-worker  -> GPU pool, primary   (GPU pods prefer this node)
#   reunion-worker2 -> GPU pool, secondary (used only when the primary is down/cordoned)
# Any other node loses its GPU labels, so the device plugin and DCGM leave it.
# Labels are also written to each pool node's kubelet flags so they survive a
# kubelet re-registration.
set -euo pipefail

POOL=rtx3070
declare -A ROLE=([reunion-worker]=primary [reunion-worker2]=secondary)

for node in "${!ROLE[@]}"; do
  labels="nvidia.com/gpu.present=true,mlpipeline.io/gpu-pool=$POOL,mlpipeline.io/gpu-role=${ROLE[$node]}"
  kubectl label node "$node" --overwrite \
    nvidia.com/gpu.present=true mlpipeline.io/gpu-pool="$POOL" mlpipeline.io/gpu-role="${ROLE[$node]}"
  docker exec "$node" sed -i "s|--node-labels=[^ \"]*|--node-labels=$labels|" /var/lib/kubelet/kubeadm-flags.env
done

for node in $(kubectl get nodes -l nvidia.com/gpu.present=true -o name | sed 's|node/||'); do
  [[ -n ${ROLE[$node]:-} ]] && continue
  kubectl label node "$node" nvidia.com/gpu.present- mlpipeline.io/gpu-pool- mlpipeline.io/gpu-role-
  docker exec "$node" sed -i 's|--node-labels=[^ "]*|--node-labels=|' /var/lib/kubelet/kubeadm-flags.env
done

kubectl get nodes -L nvidia.com/gpu.present,mlpipeline.io/gpu-pool,mlpipeline.io/gpu-role
