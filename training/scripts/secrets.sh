#!/usr/bin/env bash
# Creates the local P2 secrets once, with random values that are never printed or written to disk:
#   mlops/seaweedfs-s3-config  who may do what in which bucket (SeaweedFS's S3 permissions)
#   mlops/s3-trainer           pipeline + MLflow: read/write the mlops and models buckets
#   dispute/s3-reader          the classifier: read-only, and only the models bucket
#   mlops/postgres-creds       MLflow's database password
# On EKS none of these exist: pods get IAM roles through Pod Identity, and RDS uses IAM auth or Secrets Manager.
set -euo pipefail

if kubectl -n mlops get secret s3-trainer >/dev/null 2>&1; then
  echo "secrets already exist"
  exit 0
fi

for ns in mlops dispute; do
  kubectl create namespace "$ns" --dry-run=client -o yaml | kubectl apply -f - >/dev/null
done

rand() { openssl rand -hex "$1"; }
TRAINER_KEY="trainer$(rand 6)"; TRAINER_SECRET="$(rand 24)"
READER_KEY="reader$(rand 6)";   READER_SECRET="$(rand 24)"

CONFIG=$(cat <<EOF
{"identities": [
  {"name": "trainer", "credentials": [{"accessKey": "$TRAINER_KEY", "secretKey": "$TRAINER_SECRET"}],
   "actions": ["Read:mlops", "Write:mlops", "List:mlops", "Tagging:mlops", "Read:models", "Write:models", "List:models"]},
  {"name": "classifier", "credentials": [{"accessKey": "$READER_KEY", "secretKey": "$READER_SECRET"}],
   "actions": ["Read:models", "List:models"]}
]}
EOF
)

kubectl -n mlops create secret generic seaweedfs-s3-config --from-literal=s3.json="$CONFIG" >/dev/null
kubectl -n mlops create secret generic s3-trainer \
  --from-literal=AWS_ACCESS_KEY_ID="$TRAINER_KEY" --from-literal=AWS_SECRET_ACCESS_KEY="$TRAINER_SECRET" >/dev/null
kubectl -n dispute create secret generic s3-reader \
  --from-literal=AWS_ACCESS_KEY_ID="$READER_KEY" --from-literal=AWS_SECRET_ACCESS_KEY="$READER_SECRET" >/dev/null
kubectl -n mlops create secret generic postgres-creds --from-literal=password="$(rand 24)" >/dev/null
echo "secrets created (values not shown)"
