# Zephyrus GPU nodes

Cluster changes on the Zephyrus kind cluster (`reunion`) that ArgoCD does not
manage. Apply them directly with `kubectl`/`docker` from the Zephyrus host.

| File | What it does |
| ---- | ------------ |
| `recreate-gpu-node.sh <node> [<ipv4> <ipv6>]` | Recreates a kind node container with `--runtime=nvidia`, the NVIDIA device mount and the shared `/mnt/shared` mount, keeping its `/var` volume and hostname. Keeps its fixed IPs, or moves it to the ones given (also updating the kubelet's `--node-ip`). The first run keeps the original as `<node>-old` for rollback. |
| `gpu-node-labels.sh` | Labels `reunion-worker` (GPU primary) and `reunion-worker2` (GPU secondary) as the GPU pool; removes GPU labels from every other node. |
| `gpu-exclusive-policy.yaml` | ValidatingAdmissionPolicy: only one GPU pod at a time, cluster-wide. |
| `models-shared-pv.yaml` | Static ReadWriteMany PV on `/mnt/shared/models` for `mlpipeline-serving-models`, usable from either GPU node. |
| `ollama-models-pv.yaml` | Static ReadWriteMany PV on `/mnt/shared/ollama` for the ragpipeline Ollama (`rag/ollama-models`), usable from either GPU node. |

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

## Sharing the GPU with the ragpipeline Ollama

`rag/ollama` (ragpipeline repo, `k8s/176/05-ollama.yaml`) is a long-running GPU
pod under the same `gpu-exclusive` policy, so it holds the GPU between training
runs. The `mlpipeline_training` DAG hands the GPU over:
`pause_rag_ollama` scales it to 0 and waits for the pod to go before
`train_model`, and `resume_rag_ollama` (trigger rule `all_done`) restores the
previous replica count afterwards. The RAG site has no LLM for those ~10
minutes. The `rag` Role allowing `mlpipeline/airflow` to do this is in the
ragpipeline repo (`k8s/176/06-ollama-gpu-handoff-rbac.yaml`).

Setup, once: seed the models so the pod does not re-pull them, then apply the PV.

```bash
mkdir -p ~/mlpipeline-shared/ollama
cp -r /usr/share/ollama/.ollama/models ~/mlpipeline-shared/ollama/
kubectl apply -f ops/zephyrus/ollama-models-pv.yaml
```

If training ever fails with Ollama still down, scale it back by hand:
`kubectl -n rag scale deploy/ollama --replicas=1`.

## Retiring reunion-worker3 and reunion-worker4

`move-local-pv.sh <namespace> <pvc> <target-node>` moves one local-path PV to
another node under the same PVC name: it pre-creates a Retain PV on the target
(pre-bound to the PVC, hostPath not yet present), deletes the PVC and its pods,
copies the data once the old pod has stopped (also saving
`~/k8s-node-retire-backup-20261015/<pvc>.tar`), and the recreated pod starts on
the copied data. `DRY_RUN=1` validates without changing anything.

```bash
bash ops/zephyrus/retire-nodes.sh cordon
bash ops/zephyrus/move-local-pv.sh mlpipeline data-mlpipeline-postgres-0 reunion-worker2
bash ops/zephyrus/move-local-pv.sh mlpipeline data-mlpipeline-airflow-postgresql-0 reunion-worker2
bash ops/zephyrus/move-local-pv.sh rag qdrant-data reunion-worker
bash ops/zephyrus/move-local-pv.sh observability \
  prometheus-kube-prometheus-stack-prometheus-db-prometheus-kube-prometheus-stack-prometheus-0 reunion-worker
bash ops/zephyrus/retire-nodes.sh drain
bash ops/zephyrus/retire-nodes.sh remove
```

`qdrant-data` is recreated by ArgoCD (ragpipeline-workloads) rather than a
StatefulSet; if it doesn't reappear within a few minutes, run
`argocd app sync ragpipeline-workloads` on pop-os.

`remove` keeps the stopped containers and their `/var` volumes. Rollback:
`docker start <node>` (the kubelet re-registers it), then `kubectl uncordon <node>`.

## Host: GPU power cap

Sustained heavy load triggers an ASUS EC power cut (a hard reset with nothing
in the journal) about 3–5 minutes in. Cap GPU clocks at boot, turn off CPU
boost and Dynamic Boost, and disable runtime D3 (the GSP firmware crashed
resuming from it):

```bash
sudo cp ops/zephyrus/host/nvidia-power-cap.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now nvidia-power-cap.service
systemctl status nvidia-power-cap.service --no-pager

# CPU boost off at every boot
sudo cp ops/zephyrus/host/zephyrus-cpu-boost.conf /etc/tmpfiles.d/
sudo systemd-tmpfiles --create /etc/tmpfiles.d/zephyrus-cpu-boost.conf
cat /sys/devices/system/cpu/cpufreq/boost   # 0

# Dynamic Boost lets the GPU draw past its 80 W default (97 W seen before a reset)
sudo systemctl disable --now nvidia-powerd

# Same file name as the driver package's /usr/lib/modprobe.d/nvidia-runtimepm.conf
# so it replaces that file's DynamicPowerManagement=0x02
sudo cp ops/zephyrus/host/nvidia-runtimepm.conf /etc/modprobe.d/nvidia-runtimepm.conf
modprobe -c | grep DynamicPowerManagement   # only 0x00 should be listed
sudo update-initramfs -u                    # takes effect after the next reboot
```

On this RTX 3070 Laptop GPU `nvidia-smi -pl` is rejected ("Changing power
management limit is not supported"); the unit ignores that and the
`-lgc 210,750` clock lock is what limits power. At 1400 MHz it never engaged:
the 2026-10-16 training run peaked at 1245 MHz and sat at the 80 W board limit
(avg 69 W) with the CPU at ~95 °C. At 1000 MHz training drew a steady 67 W and
the host still reset ~4 minutes into `train_model` twice on 2026-10-17 (CPU at
83 °C); a third reset that day came with the rag Ollama on the GPU at only 23 W
but the CPU at 95 °C and RAM nearly exhausted. At 750 MHz with CPU boost off,
a full fp16 matmul burn holds at 40 W / 60 °C GPU. To change it, edit the
upper clock in
`/etc/systemd/system/nvidia-power-cap.service` and
`sudo systemctl daemon-reload && sudo systemctl restart nvidia-power-cap`.

The hardware side (cleaning the fans/heatsink, re-pasting, a BIOS newer than
GA503QR.416) still matters: the CPU idles around 75 °C.

## Fixed node IPs

Docker assigns kind-network addresses in start order, and a stopped container's
fixed IP isn't reserved: after a reboot `kind-registry` took 172.18.0.3 and
`reunion-worker` failed to start ("Address already in use"). The GPU workers
therefore live at fixed addresses far above the dynamic range:

```bash
bash ops/zephyrus/recreate-gpu-node.sh reunion-worker  172.18.200.3 fc00:f853:ccd:e793::200:3
bash ops/zephyrus/recreate-gpu-node.sh reunion-worker2 172.18.200.5 fc00:f853:ccd:e793::200:5
```

The control plane and `kind-registry` stay dynamic; `rag-forward` resolves node
IPs by container name, and metrics-server uses `--kubelet-insecure-tls`.
