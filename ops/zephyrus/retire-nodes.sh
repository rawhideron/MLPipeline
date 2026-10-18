#!/usr/bin/env bash
# Retire kind nodes reunion-worker3 and reunion-worker4.
# Usage: retire-nodes.sh cordon|drain|remove
#   cordon  stop new pods landing there (run before move-local-pv.sh)
#   drain   evict the remaining pods (after every PV has been moved)
#   remove  delete the Node objects and stop the containers; the containers
#           and their /var volumes are kept for rollback (docker start + uncordon)
# Completed 2026-10-18: both containers and their /var volumes have been deleted.
set -euo pipefail
NODES=(reunion-worker3 reunion-worker4)

pvs_on_nodes() {
  kubectl get pv -o json | python3 -I -c "
import json, sys
nodes = set(sys.argv[1:])
for pv in json.load(sys.stdin)['items']:
    for t in pv['spec'].get('nodeAffinity', {}).get('required', {}).get('nodeSelectorTerms', []):
        for e in t.get('matchExpressions', []):
            if nodes & set(e.get('values', [])):
                print(pv['metadata']['name'], pv['status']['phase'], (pv['spec'].get('claimRef') or {}).get('name', ''))" "${NODES[@]}"
}

case ${1:-} in
cordon)
  kubectl cordon "${NODES[@]}"
  ;;
drain)
  bound=$(pvs_on_nodes | awk '$2 == "Bound"')
  [[ -n $bound ]] && { echo "PVs still bound on these nodes -- move them first:"; echo "$bound"; exit 1; }
  kubectl drain "${NODES[@]}" --ignore-daemonsets --delete-emptydir-data --timeout=10m
  for n in "${NODES[@]}"; do
    echo "== left on $n (DaemonSet pods are expected):"
    kubectl get pods -A --field-selector spec.nodeName="$n" --no-headers | awk '{print "  "$1"/"$2, $4}'
  done
  ;;
remove)
  left=$(pvs_on_nodes)
  if [[ -n $left ]]; then
    echo "PV objects still pinned to these nodes:"; echo "$left"
    if echo "$left" | awk '$2 == "Bound"' | grep -q .; then echo "bound PVs remain -- aborting"; exit 1; fi
    echo "deleting the released/unbound PV objects (their data stays in the stopped containers' volumes)"
    echo "$left" | awk '{print $1}' | xargs kubectl delete pv
  fi
  kubectl delete node "${NODES[@]}"
  for n in "${NODES[@]}"; do
    docker update --restart=no "$n" >/dev/null
    docker stop "$n"
  done
  echo "Stopped. Rollback: docker start <node> (kubelet re-registers), then kubectl uncordon <node>."
  echo "When no longer needed: docker rm ${NODES[*]} && docker volume rm <their /var volumes>."
  ;;
*)
  echo "usage: $0 cordon|drain|remove"; exit 2
  ;;
esac
