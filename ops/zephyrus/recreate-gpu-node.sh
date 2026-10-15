#!/usr/bin/env bash
# Recreate a kind node container with the NVIDIA device mount, keeping its
# /var volume, hostname and IPs so Kubernetes sees the same node come back.
# Usage: recreate-gpu-node.sh <node-name>
set -euo pipefail
N=$1
VOL=$(docker inspect "$N" --format '{{range .Mounts}}{{if eq .Destination "/var"}}{{.Name}}{{end}}{{end}}')
IP4=$(docker inspect "$N" --format '{{.NetworkSettings.Networks.kind.IPAddress}}')
IP6=$(docker inspect "$N" --format '{{.NetworkSettings.Networks.kind.GlobalIPv6Address}}')
IMG="reunion-node-gpu:${N#reunion-}"
# Host directory shared by both GPU nodes (models volume lives under it)
SHARED=/home/ron-goodman/mlpipeline-shared
[[ -d $SHARED ]] || { echo "create $SHARED first"; exit 1; }
[[ -n $VOL && -n $IP4 && -n $IP6 ]] || { echo "missing vol/ip for $N"; exit 1; }
echo "node=$N vol=$VOL ip4=$IP4 ip6=$IP6 image=$IMG"

kubectl cordon "$N"
if docker inspect "$N-old" >/dev/null 2>&1; then
  # Already swapped once: the old container is the rollback copy, so only
  # replace the new container. Re-commit it first so rootfs changes made
  # since the last swap (e.g. containerd config) carry over; its /var volume
  # is kept because rm has no -v.
  echo "$N-old exists; re-committing and re-running the new container only"
  docker stop "$N"
  docker commit "$N" "$IMG" >/dev/null
  docker rm "$N" >/dev/null
else
  # Persist the GPU label for any future kubelet re-registration
  docker exec "$N" sed -i 's/--node-labels=[^ "]*/--node-labels=nvidia.com\/gpu.present=true/' /var/lib/kubelet/kubeadm-flags.env
  docker exec "$N" cat /var/lib/kubelet/kubeadm-flags.env
  docker stop "$N"
  docker commit "$N" "$IMG" >/dev/null
  docker rename "$N" "$N-old"
  docker update --restart=no "$N-old" >/dev/null
fi

# --runtime=nvidia: snap docker resets daemon.json on refresh/boot, dropping
# default-runtime=nvidia, and only the nvidia runtime injects the driver.
docker run -d --tty --runtime=nvidia --name "$N" --hostname "$N" \
  --label io.x-k8s.kind.cluster=reunion --label io.x-k8s.kind.role=worker \
  --privileged --security-opt seccomp=unconfined --security-opt apparmor=unconfined --security-opt label=disable \
  --tmpfs /tmp --tmpfs /run \
  -v "$VOL":/var -v /lib/modules:/lib/modules:ro \
  -v /dev/null:/var/run/nvidia-container-devices/all \
  -v "$SHARED":/mnt/shared \
  -e KIND_EXPERIMENTAL_CONTAINERD_SNAPSHOTTER \
  --cgroupns=private --init=false --restart=on-failure:1 \
  --network kind --ip "$IP4" --ip6 "$IP6" \
  "$IMG" >/dev/null
echo "started $N"
