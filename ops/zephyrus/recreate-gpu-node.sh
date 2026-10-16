#!/usr/bin/env bash
# Recreate a kind node container with the NVIDIA device mount, keeping its
# /var volume, hostname and IPs so Kubernetes sees the same node come back.
# Usage: recreate-gpu-node.sh <node-name> [<new-ipv4> <new-ipv6>]
#
# Pass new IPs to move the node to a fixed address outside the low range
# Docker hands out dynamically on the kind network (kind-registry and the
# control plane get .2-.4 in whatever order they start at boot, and a stopped
# container's fixed IP isn't reserved): the GPU workers use 172.18.200.x.
set -euo pipefail
N=$1
VOL=$(docker inspect "$N" --format '{{range .Mounts}}{{if eq .Destination "/var"}}{{.Name}}{{end}}{{end}}')
# Configured (fixed) IPs are present even when the container isn't running.
IP4=$(docker inspect "$N" --format '{{with .NetworkSettings.Networks.kind.IPAMConfig}}{{.IPv4Address}}{{end}}')
IP6=$(docker inspect "$N" --format '{{with .NetworkSettings.Networks.kind.IPAMConfig}}{{.IPv6Address}}{{end}}')
[[ -n $IP4 ]] || IP4=$(docker inspect "$N" --format '{{.NetworkSettings.Networks.kind.IPAddress}}')
[[ -n $IP6 ]] || IP6=$(docker inspect "$N" --format '{{.NetworkSettings.Networks.kind.GlobalIPv6Address}}')
if [[ $# -ge 3 ]]; then
  echo "changing $N address: $IP4/$IP6 -> $2/$3"
  IP4=$2 IP6=$3
  CHANGE_IP=1
fi
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

# The kubelet registers the node with --node-ip; point it at the new address.
if [[ ${CHANGE_IP:-0} == 1 ]]; then
  docker run --rm --entrypoint sed -v "$VOL":/var "$IMG" \
    -i "s/--node-ip=[^ \"]*/--node-ip=$IP4/" /var/lib/kubelet/kubeadm-flags.env
  docker run --rm --entrypoint cat -v "$VOL":/var "$IMG" /var/lib/kubelet/kubeadm-flags.env
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
