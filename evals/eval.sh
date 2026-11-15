#!/usr/bin/env bash
# Runs the golden set against the assistant in the kind cluster.
#   evals/eval.sh              evaluate what is deployed now
#   evals/eval.sh v2           deploy prompt v2 as a candidate, evaluate it, then put the committed version back
# Exit code is the gate's: 0 passed, 1 failed.
set -euo pipefail
cd "$(dirname "$0")/.."
PROMPT=${1:-}
CHART=deploy/charts/service
VALUES=deploy/local/assistant.yaml

PIDS=()
cleanup() {
  kill "${PIDS[@]}" 2>/dev/null || true
  if [ -n "$PROMPT" ]; then
    echo; echo "restoring the committed assistant ($VALUES)"
    helm upgrade assistant $CHART -f $VALUES -n dispute >/dev/null
    kubectl -n dispute rollout status deploy/assistant --timeout=120s >/dev/null
  fi
}
trap cleanup EXIT

if [ -n "$PROMPT" ]; then
  # Like a CI preview environment: the candidate runs only for the evaluation.
  echo "deploying candidate prompt $PROMPT"
  helm upgrade assistant $CHART -f $VALUES -n dispute --set env.PROMPT_VERSION="$PROMPT" >/dev/null
  kubectl -n dispute rollout status deploy/assistant --timeout=120s >/dev/null
fi

# The LLM judge calls the LLM directly; Phoenix gives each failing case a link to its trace.
kubectl -n dispute port-forward svc/llm 18080:8080 >/dev/null 2>&1 & PIDS+=($!)
kubectl -n observability port-forward svc/phoenix 6006:6006 >/dev/null 2>&1 & PIDS+=($!)
sleep 2

.venv/bin/python evals/run_eval.py --url http://localhost:8080 --judge-url http://localhost:18080/v1
