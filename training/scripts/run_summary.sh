#!/usr/bin/env bash
# Prints each step of a pipeline run with its result, and the log of the step that stopped it.
set -euo pipefail
NAME=${1:?usage: run_summary.sh <workflow name>}
WF=$(kubectl -n mlops get workflow "$NAME" -o json)
PODS=$(kubectl -n mlops get pods -l "workflows.argoproj.io/workflow=$NAME" -o json)

python3 - "$WF" "$PODS" <<'PY'
import json, sys
wf, pods = json.loads(sys.argv[1]), json.loads(sys.argv[2])
nodes = [n for n in wf["status"].get("nodes", {}).values() if n.get("type") == "Pod"]
latest = {}
for n in sorted(nodes, key=lambda n: n.get("startedAt") or ""):
    latest[n["displayName"].split("(")[0]] = n          # a retried step: keep the last attempt
print(f"\n{wf['metadata']['name']}: {wf['status']['phase']}")
for step in ("prepare", "validate", "train", "compare", "publish"):
    n = latest.get(step)
    print(f"  {step:<9} {n['phase'] if n else '-- not run'}")
skipped = [n for n in wf["status"].get("nodes", {}).values() if n.get("type") == "Skipped"]
for n in skipped:
    print(f"  ({n['displayName']} skipped: {n.get('message', '')})")
# Pod names aren't node IDs; the node-id annotation links them.
bad = [n for n in latest.values() if n["phase"] in ("Failed", "Error")]
if bad:
    by_node = {p["metadata"].get("annotations", {}).get("workflows.argoproj.io/node-id"): p["metadata"]["name"]
               for p in pods["items"]}
    with open("/tmp/.p2-failed-pod", "w") as f:
        f.write(by_node.get(bad[-1]["id"], ""))
PY

if [ -s /tmp/.p2-failed-pod ]; then
  POD=$(cat /tmp/.p2-failed-pod); rm -f /tmp/.p2-failed-pod
  echo; echo "--- log of the step that stopped the run ($POD) ---"
  kubectl -n mlops logs "$POD" -c main 2>/dev/null | tail -25 || echo "(pod already removed)"
fi
