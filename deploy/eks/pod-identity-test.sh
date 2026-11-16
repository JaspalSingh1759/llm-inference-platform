#!/usr/bin/env bash
# P4 check: Pod Identity gives each service account exactly its own permissions, with no keys anywhere.
# Runs the AWS CLI as dispute/classifier (may read published models only) and as mlops/trainer.
set -uo pipefail
cd "$(dirname "$0")/../.."
MODELS=$(terraform -chdir=infra/platform output -json buckets | python3 -c 'import json,sys; print(json.load(sys.stdin)["models"])')
MLOPS=$(terraform -chdir=infra/platform output -json buckets | python3 -c 'import json,sys; print(json.load(sys.stdin)["mlops"])')

try() {   # try <namespace> <service account> <description> <aws args...>
  local ns=$1 sa=$2 what=$3; shift 3
  kubectl create namespace "$ns" --dry-run=client -o yaml | kubectl apply -f - >/dev/null
  kubectl -n "$ns" create serviceaccount "$sa" --dry-run=client -o yaml | kubectl apply -f - >/dev/null
  out=$(kubectl -n "$ns" run "pi-test-$RANDOM" --rm -i --restart=Never --quiet \
        --image=amazon/aws-cli:2.39.2 --overrides="{\"spec\":{\"serviceAccountName\":\"$sa\"}}" -- "$@" 2>&1)
  rc=$?
  if echo "$out" | grep -q "AccessDenied"; then result="DENIED"
  elif [ $rc -eq 0 ]; then result="allowed"
  else result="error: $(echo "$out" | tail -1 | cut -c1-60)"; fi
  printf "  %-20s %-45s %s\n" "$ns/$sa" "$what" "$result"
}

echo "service account      action                                        result"
try dispute classifier "list s3://models"                    s3 ls "s3://$MODELS/"
try dispute classifier "write s3://models/x"                 s3api put-object --bucket "$MODELS" --key dispute-classifier/x --body /etc/hostname
try dispute classifier "list s3://mlops"                     s3 ls "s3://$MLOPS/"
try mlops   trainer    "write s3://mlops/raw/x"              s3api put-object --bucket "$MLOPS" --key raw/x --body /etc/hostname
try mlops   trainer    "list s3://models"                    s3 ls "s3://$MODELS/"
echo "  (identity seen by the classifier pod:)"
kubectl -n dispute run "pi-whoami-$RANDOM" --rm -i --restart=Never --quiet --image=amazon/aws-cli:2.39.2 \
  --overrides='{"spec":{"serviceAccountName":"classifier"}}' -- sts get-caller-identity --query Arn --output text
