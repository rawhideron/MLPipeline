#!/usr/bin/env bash
# Move a local-path PersistentVolume's data to another kind node, keeping the
# PVC name so StatefulSets, ArgoCD and Helm don't need to change.
#
# Usage: move-local-pv.sh <namespace> <pvc> <target-node>
#
# How it works (no need to pause ArgoCD or scale anything down):
#   1. The old PV is switched to Retain and a new PV is created on the target
#      node, pre-bound to the same PVC name, whose hostPath (type: Directory)
#      does not exist yet.
#   2. The PVC and the pods using it are deleted. The StatefulSet / ArgoCD
#      recreates the PVC, it binds to the new PV, and the new pod waits on the
#      target node because its directory is missing.
#   3. With the old pod fully stopped, the data is copied (and saved to a tar
#      in $BACKUP_DIR), then moved into place atomically; the pod mounts it
#      and starts on the exact same data.
#   4. The old PV object is deleted. Its directory stays on the old node until
#      that node is removed.
set -euo pipefail

NS=$1 PVC=$2 DST=$3
BACKUP_DIR=${BACKUP_DIR:-$HOME/k8s-node-retire-backup-20261015}
mkdir -p "$BACKUP_DIR"

OLD_PV=$(kubectl -n "$NS" get pvc "$PVC" -o jsonpath='{.spec.volumeName}')
OLD_UID=$(kubectl -n "$NS" get pvc "$PVC" -o jsonpath='{.metadata.uid}')
SRC=$(kubectl get pv "$OLD_PV" -o jsonpath='{.spec.nodeAffinity.required.nodeSelectorTerms[0].matchExpressions[0].values[0]}')
SRC_PATH=$(kubectl get pv "$OLD_PV" -o jsonpath='{.spec.hostPath.path}')
SIZE=$(kubectl get pv "$OLD_PV" -o jsonpath='{.spec.capacity.storage}')
SC=$(kubectl get pv "$OLD_PV" -o jsonpath='{.spec.storageClassName}')
MODES=$(kubectl get pv "$OLD_PV" -o jsonpath='{.spec.accessModes}')
DIR=$(basename "$SRC_PATH")
NEW_PV="$OLD_PV-m"
PARENT=$(dirname "$SRC_PATH")

echo "pvc=$NS/$PVC old_pv=$OLD_PV ($SRC:$SRC_PATH, $SIZE, $SC) -> new_pv=$NEW_PV on $DST"
[[ $SRC == "$DST" ]] && { echo "already on $DST"; exit 1; }
[[ $SRC_PATH == /var/local-path-provisioner/* ]] || { echo "unexpected path $SRC_PATH"; exit 1; }
docker exec "$DST" test ! -e "$SRC_PATH" || { echo "$DST:$SRC_PATH already exists"; exit 1; }

pods_using() {
  kubectl -n "$NS" get pods -o json | python3 -I -c "
import json, sys
for p in json.load(sys.stdin)['items']:
    if any((v.get('persistentVolumeClaim') or {}).get('claimName') == '$PVC' for v in p['spec'].get('volumes', [])):
        print(p['metadata']['name'], p['spec'].get('nodeName', ''), p['metadata']['uid'])"
}

# DRY_RUN=1: validate the new PV server-side and stop before changing anything
DRY=()
[[ ${DRY_RUN:-0} == 1 ]] && DRY=(--dry-run=server)

# 1. keep the old data, pre-create the new PV
kubectl patch pv "$OLD_PV" "${DRY[@]}" -p '{"spec":{"persistentVolumeReclaimPolicy":"Retain"}}'
kubectl apply "${DRY[@]}" -f - <<EOF
apiVersion: v1
kind: PersistentVolume
metadata:
  name: $NEW_PV
  labels:
    mlpipeline.io/moved-from: $SRC
spec:
  capacity:
    storage: $SIZE
  accessModes: $MODES
  persistentVolumeReclaimPolicy: Retain
  storageClassName: $SC
  volumeMode: Filesystem
  claimRef:
    namespace: $NS
    name: $PVC
  hostPath:
    path: $SRC_PATH
    type: Directory
  nodeAffinity:
    required:
      nodeSelectorTerms:
        - matchExpressions:
            - key: kubernetes.io/hostname
              operator: In
              values: [$DST]
EOF
[[ ${DRY_RUN:-0} == 1 ]] && { echo "dry run: pods using $PVC:"; pods_using; exit 0; }

# 2. release the PVC; pods on the old node shut down gracefully
OLD_PODS=$(pods_using | awk -v n="$SRC" '$2 == n {print $1}')
echo "stopping on $SRC: ${OLD_PODS:-<none>}"
kubectl -n "$NS" delete pvc "$PVC" --wait=false
[[ -n $OLD_PODS ]] && kubectl -n "$NS" delete pod $OLD_PODS --wait=true --timeout=15m

echo -n "waiting for the old PVC to be gone"
for _ in $(seq 1 180); do
  uid=$(kubectl -n "$NS" get pvc "$PVC" -o jsonpath='{.metadata.uid}' 2>/dev/null || true)
  [[ $uid != "$OLD_UID" ]] && break
  echo -n .; sleep 5
done
echo
[[ $uid == "$OLD_UID" ]] && { echo "old PVC still present -- check finalizers"; exit 1; }

# 3. copy (old pods are gone, so the source is quiescent) + backup tar
echo "copying $SRC:$SRC_PATH -> $DST (backup: $BACKUP_DIR/$PVC.tar)"
docker exec "$SRC" tar --sparse --numeric-owner -C "$PARENT" -cpf - "$DIR" \
  | tee "$BACKUP_DIR/$PVC.tar" \
  | docker exec -i "$DST" sh -c "mkdir -p $PARENT/.incoming && tar --numeric-owner -C $PARENT/.incoming -xpf - && mv $PARENT/.incoming/$DIR $PARENT/ && rmdir $PARENT/.incoming"
echo "src: $(docker exec "$SRC" du -s "$SRC_PATH" | cut -f1)K  dst: $(docker exec "$DST" du -s "$SRC_PATH" | cut -f1)K"

# 4. wait for the workload to come back on the new PV
echo -n "waiting for the new PVC to bind to $NEW_PV"
for _ in $(seq 1 120); do
  [[ $(kubectl -n "$NS" get pvc "$PVC" -o jsonpath='{.spec.volumeName}/{.status.phase}' 2>/dev/null) == "$NEW_PV/Bound" ]] && break
  echo -n .; sleep 5
done
echo
kubectl -n "$NS" get pvc "$PVC"
echo -n "waiting for pods to be Ready"
ready=0
for _ in $(seq 1 120); do
  read -r name node _ < <(pods_using | head -1) || true
  if [[ -n ${name:-} ]] && kubectl -n "$NS" wait --for=condition=Ready "pod/$name" --timeout=5s >/dev/null 2>&1; then
    echo; echo "ready: $name on $node"; ready=1; break
  fi
  echo -n .; sleep 5
done

if [[ $ready == 1 ]]; then
  kubectl delete pv "$OLD_PV" --wait=false
  echo "done. Old data still on $SRC:$SRC_PATH until the node is removed."
else
  echo "pod not Ready yet -- old PV $OLD_PV kept; check 'kubectl -n $NS describe pod'"
  exit 1
fi
