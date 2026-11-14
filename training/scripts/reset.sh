#!/usr/bin/env bash
# Local only: forget all training history. Deletes pipeline runs, empties the MLflow database and removes
# generated data (prepared datasets, step files, MLflow files, published models). The raw drops stay.
set -euo pipefail
kubectl -n mlops delete workflows --all >/dev/null
kubectl -n mlops scale deploy/mlflow --replicas=0 >/dev/null
kubectl -n mlops wait --for=delete pod -l app.kubernetes.io/name=mlflow --timeout=60s >/dev/null 2>&1 || true
kubectl -n mlops exec deploy/postgres -- psql -q -U mlflow -d postgres -c "DROP DATABASE mlflow;" -c "CREATE DATABASE mlflow;"
kubectl -n mlops exec deploy/s3 -- sh -c 'printf "fs.rm -r /buckets/mlops/mlflow\nfs.rm -r /buckets/mlops/argo\nfs.rm -r /buckets/mlops/datasets\nfs.rm -r /buckets/models/dispute-classifier\n" | weed shell >/dev/null 2>&1' || true
kubectl -n mlops scale deploy/mlflow --replicas=1 >/dev/null
kubectl -n mlops rollout status deploy/mlflow --timeout=180s >/dev/null
echo "training history reset (raw drops kept)"
