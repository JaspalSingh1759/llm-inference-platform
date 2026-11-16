#!/usr/bin/env bash
# P5: the training side on EKS: team namespaces + quotas + priorities, MLflow on RDS, Argo Workflows with
# artifacts in S3, and the shared pipeline template. Safe to re-run. P7 moves these into Argo CD.
set -euo pipefail
cd "$(dirname "$0")/../.."
ARGO_CHART_VERSION=2.0.13

kubectl apply -f deploy/eks/teams.yaml

# MLflow's database URI. RDS generated the password and keeps it in Secrets Manager; it goes straight into a
# Kubernetes Secret and is never printed. (Production: External Secrets Operator syncs it, and rotates it.)
ENDPOINT=$(terraform -chdir=infra/platform output -raw mlflow_db_endpoint)
SECRET_ARN=$(terraform -chdir=infra/platform output -raw mlflow_db_secret_arn)
aws secretsmanager get-secret-value --secret-id "$SECRET_ARN" --query SecretString --output text \
  | ENDPOINT="$ENDPOINT" python3 -c '
import json, os, sys, urllib.parse
s = json.load(sys.stdin)
user, password = s["username"], urllib.parse.quote(s["password"], safe="")
print("postgresql://" + user + ":" + password + "@" + os.environ["ENDPOINT"] + "/mlflow?sslmode=require", end="")' \
  | kubectl -n mlops create secret generic mlflow-db --from-file=uri=/dev/stdin --dry-run=client -o yaml \
  | kubectl apply -f - >/dev/null
echo "secret mlops/mlflow-db set"

helm repo add argo https://argoproj.github.io/argo-helm >/dev/null 2>&1 || true
helm repo update argo >/dev/null
helm upgrade --install argo-workflows argo/argo-workflows --version $ARGO_CHART_VERSION \
  -n argo --create-namespace -f deploy/eks/argo-values.yaml --wait >/dev/null
echo "argo workflows installed"

kubectl apply -f deploy/eks/mlflow.yaml -f deploy/eks/train-classifier.yaml
kubectl -n mlops rollout status deploy/mlflow --timeout=180s
