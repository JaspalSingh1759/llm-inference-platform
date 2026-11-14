#!/usr/bin/env bash
# Uploads the raw exports in training/raw/ to s3://mlops/raw/ (this plays the data team dropping files).
# Uses the AWS CLI through a port-forward, with the trainer's keys read from the cluster (never printed).
set -euo pipefail
cd "$(dirname "$0")/.."
kubectl -n mlops port-forward svc/s3 18333:8333 >/dev/null 2>&1 &
PF=$!
trap 'kill $PF 2>/dev/null' EXIT
sleep 2
secret() { kubectl -n mlops get secret s3-trainer -o "jsonpath={.data.$1}" | base64 -d; }
export AWS_ACCESS_KEY_ID="$(secret AWS_ACCESS_KEY_ID)" AWS_SECRET_ACCESS_KEY="$(secret AWS_SECRET_ACCESS_KEY)"
export AWS_DEFAULT_REGION=us-east-1
unset AWS_PROFILE AWS_SESSION_TOKEN   # never the real AWS account
aws --endpoint-url http://localhost:18333 s3 cp raw/ s3://mlops/raw/ --recursive --exclude '*' --include '*.csv' --only-show-errors
aws --endpoint-url http://localhost:18333 s3 ls s3://mlops/raw/
