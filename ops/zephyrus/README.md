# Zephyrus GPU nodes

Cluster changes on the Zephyrus kind cluster (`reunion`) that ArgoCD does not
manage. Apply them directly with `kubectl`/`docker` from the Zephyrus host.

| File | What it does |
| ---- | ------------ |
| `recreate-gpu-node.sh <node>` | Recreates a kind node container with `--runtime=nvidia`, the NVIDIA device mount and the shared `/mnt/shared` mount, keeping its `/var` volume, hostname and IPs. The first run keeps the original as `<node>-old` for rollback. |
| `gpu-node-labels.sh` | Labels `reunion-worker` (GPU primary) and `reunion-worker2` (GPU secondary) as the GPU pool; removes GPU labels from every other node. |
| `gpu-exclusive-policy.yaml` | ValidatingAdmissionPolicy: only one GPU pod at a time, cluster-wide. |
| `models-shared-pv.yaml` | Static ReadWriteMany PV on `/mnt/shared/models` for `mlpipeline-serving-models`, usable from either GPU node. |

## Moving the models volume to shared storage

The serving chart binds `mlpipeline-serving-models` to `mlpipeline-models-shared`.
A PVC's storage class, access modes and volume can't be changed in place, so
the old PVC has to be deleted once while ArgoCD recreates it.

1. Create the host directory: `mkdir -p ~/mlpipeline-shared/models`
2. Give both GPU nodes the shared mount, one at a time, waiting for `Ready`:
   `bash ops/zephyrus/recreate-gpu-node.sh reunion-worker`, then `reunion-worker2`.
   Then `bash ops/zephyrus/gpu-node-labels.sh`.
3. Keep the old data if the PVC is deleted:
   `kubectl patch pv <old-pv> -p '{"spec":{"persistentVolumeReclaimPolicy":"Retain"}}'`
4. Copy the model files into the shared directory, keeping ownership:

   ```bash
   docker exec <old-node> tar --numeric-owner -C /var/local-path-provisioner/<old-pv-dir> -cpf - . \
     | docker exec -i reunion-worker tar --numeric-owner -C /mnt/shared/models -xpf -
   ```

5. `kubectl apply -f ops/zephyrus/models-shared-pv.yaml` — the PV shows `Available`, reserved for the PVC.
6. Merge the chart change to `main`. ArgoCD's sync of `mlpipeline-serving-178` fails on the
   immutable PVC fields until the next step; that is expected.
7. Swap the PVC:

   ```bash
   kubectl -n mlpipeline delete pvc mlpipeline-serving-models --wait=false
   kubectl -n mlpipeline delete pod -l app=mlpipeline,component=serving
   ```

   ArgoCD self-heal recreates the PVC from the chart and it binds to `mlpipeline-models-shared`.
8. Verify the PVC is `Bound` to `mlpipeline-models-shared`, the serving pod is running on
   `reunion-worker` or `reunion-worker2`, and `/health` returns 200.

Rollback: revert the chart change, delete the new PVC, and recreate the old one
with `volumeName: <old-pv>` and `storageClassName: standard`.
