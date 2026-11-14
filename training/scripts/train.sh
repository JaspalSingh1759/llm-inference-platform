#!/usr/bin/env bash
# Submits one run of the train-classifier pipeline and follows it to the end (no argo CLI needed).
# Usage: train.sh <raw file under raw/>   e.g. train.sh claims-2026-11.csv
set -euo pipefail
RAW=${1:?usage: train.sh <raw file, e.g. claims-2026-11.csv>}
NAME=$(kubectl create -o name -f - <<YAML
apiVersion: argoproj.io/v1alpha1
kind: Workflow
metadata: {generateName: train-classifier-, namespace: mlops}
spec:
  workflowTemplateRef: {name: train-classifier}
  arguments: {parameters: [{name: raw, value: "$RAW"}]}
YAML
)
NAME=${NAME#*/}
echo "submitted $NAME (raw/$RAW)"
while true; do
  PHASE=$(kubectl -n mlops get workflow "$NAME" -o jsonpath='{.status.phase}')
  case "$PHASE" in Succeeded|Failed|Error) break;; esac
  sleep 5
done
"$(dirname "$0")/run_summary.sh" "$NAME"
[ "$PHASE" = Succeeded ]
