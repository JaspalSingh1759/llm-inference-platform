#!/usr/bin/env bash
# Creates the two buckets in the local S3 store (SeaweedFS's admin shell, inside its pod). Safe to re-run.
set -euo pipefail
for bucket in mlops models; do
  out=$(kubectl -n mlops exec deploy/s3 -- sh -c "echo 's3.bucket.create -name $bucket' | weed shell 2>&1" || true)
  case "$out" in *rror*|*xist*) echo "bucket $bucket: ${out##*> }";; *) echo "bucket $bucket: ok";; esac
done
kubectl -n mlops exec deploy/s3 -- sh -c "echo 's3.bucket.list' | weed shell 2>/dev/null" | grep -E "mlops|models" || true
