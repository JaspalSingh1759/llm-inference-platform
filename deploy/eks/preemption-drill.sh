#!/usr/bin/env bash
# P5 part 3 drill: serving beats training. While a training step runs on the training node, a high-priority
# "serving burst" pod that only fits there is created. Expected: the scheduler preempts (evicts) the training
# pod, the burst runs, Argo retries the step, and the retry waits (training never preempts) until the burst ends.
set -euo pipefail
cd "$(dirname "$0")/../.."
NAMESPACE=mlops CLUSTER_TEMPLATE=true training/scripts/train.sh claims-2026-12.csv > /tmp/preemption-drill-run.log 2>&1 &
RUN=$!
echo "waiting for the train step to start..."
until kubectl -n mlops get pods -l workflows.argoproj.io/workflow --field-selector=status.phase=Running -o name 2>/dev/null | grep -q -- '-train-'; do sleep 2; done
TRAIN_POD=$(kubectl -n mlops get pods --field-selector=status.phase=Running -o name | grep -- '-train-' | tail -1)
echo "train step running: $TRAIN_POD"

kubectl apply -f - <<YAML
apiVersion: v1
kind: Pod
metadata: {name: serving-burst, namespace: dispute}
spec:
  priorityClassName: serving
  nodeSelector: {node-role: training}
  tolerations: [{key: workload, operator: Equal, value: training, effect: NoSchedule}]
  containers:
    - {name: pause, image: registry.k8s.io/pause:3.10, resources: {requests: {cpu: 1200m, memory: 256Mi}}}
YAML
kubectl -n dispute wait --for=condition=Ready pod/serving-burst --timeout=120s
echo; echo "--- events: who evicted whom ---"
kubectl get events -A --field-selector reason=Preempted -o custom-columns='POD:.involvedObject.name,MESSAGE:.message' | tail -3
echo; echo "--- training pods now (the retry waits: Pending) ---"
kubectl -n mlops get pods -l workflows.argoproj.io/workflow -o custom-columns='POD:.metadata.name,PHASE:.status.phase,PRIORITY:.spec.priorityClassName' --sort-by=.metadata.creationTimestamp | tail -3
sleep 20
echo; echo "burst over: deleting it"
kubectl -n dispute delete pod serving-burst --wait=true >/dev/null
wait $RUN || true
tail -8 /tmp/preemption-drill-run.log
