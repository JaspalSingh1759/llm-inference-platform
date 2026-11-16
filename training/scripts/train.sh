#!/usr/bin/env bash
# Submits one run of the train-classifier pipeline and follows it to the end (no argo CLI needed).
# Usage: train.sh <raw file under raw/>   e.g. train.sh claims-2026-11.csv
# Env: NAMESPACE (default mlops; another team submits from its own namespace),
#      CLUSTER_TEMPLATE=true to use the shared ClusterWorkflowTemplate (EKS) instead of the namespaced one (kind),
#      MODEL_NAME (default dispute-classifier).
set -euo pipefail
RAW=${1:?usage: train.sh <raw file, e.g. claims-2026-11.csv>}
NAMESPACE=${NAMESPACE:-mlops}
SCOPE=$([ "${CLUSTER_TEMPLATE:-false}" = true ] && echo ", clusterScope: true" || true)
export NAMESPACE
NAME=$(kubectl create -o name -f - <<YAML
apiVersion: argoproj.io/v1alpha1
kind: Workflow
metadata: {generateName: train-classifier-, namespace: $NAMESPACE}
spec:
  workflowTemplateRef: {name: train-classifier$SCOPE}
  arguments: {parameters: [{name: raw, value: "$RAW"}, {name: model-name, value: "${MODEL_NAME:-dispute-classifier}"}]}
YAML
)
NAME=${NAME#*/}
echo "submitted $NAME in $NAMESPACE (raw/$RAW)"
while true; do
  PHASE=$(kubectl -n "$NAMESPACE" get workflow "$NAME" -o jsonpath='{.status.phase}')
  case "$PHASE" in Succeeded|Failed|Error) break;; esac
  sleep 5
done
"$(dirname "$0")/run_summary.sh" "$NAME"
[ "$PHASE" = Succeeded ]
