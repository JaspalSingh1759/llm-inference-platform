"""S3 access for the pipeline steps.

Locally the store is SeaweedFS (S3-compatible); on EKS it is Amazon S3. Only S3_ENDPOINT_URL changes:
set it for SeaweedFS, leave it empty for AWS. Credentials come from the usual AWS environment variables
locally, and from Pod Identity on EKS.

Layout:
  mlops bucket   raw/<file>.csv           data team exports
                 datasets/<version>/      prepared datasets (train/val/test parquet + manifest.json)
                 mlflow/                  MLflow's files (written by the MLflow server)
                 argo/                    files passed between pipeline steps
  models bucket  <model name>/v<N>/       published models (model.joblib + metadata.json); serving reads only this
"""

import os
from pathlib import Path

import boto3
from botocore.config import Config

MLOPS_BUCKET = os.environ.get("MLOPS_BUCKET", "mlops")
MODELS_BUCKET = os.environ.get("MODELS_BUCKET", "models")
WORK = Path(os.environ.get("WORK_DIR", "/work"))


def client():
    return boto3.client("s3", endpoint_url=os.environ.get("S3_ENDPOINT_URL") or None,
                        config=Config(s3={"addressing_style": "path"}))


def keys(prefix, bucket=MLOPS_BUCKET):
    for page in client().get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            yield obj["Key"]


def exists(prefix, bucket=MLOPS_BUCKET):
    return next(keys(prefix, bucket), None) is not None


def download_file(key, dest, bucket=MLOPS_BUCKET):
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    client().download_file(bucket, key, str(dest))
    return dest


def download_prefix(prefix, dest, bucket=MLOPS_BUCKET):
    dest = Path(dest)
    found = list(keys(prefix.rstrip("/") + "/", bucket))
    if not found:
        raise FileNotFoundError(f"nothing under s3://{bucket}/{prefix}")
    for key in found:
        download_file(key, dest / key[len(prefix.rstrip("/")) + 1:], bucket)
    return dest


def upload_dir(src, prefix, bucket=MLOPS_BUCKET):
    s3 = client()
    for f in sorted(Path(src).iterdir()):
        if f.is_file():
            s3.upload_file(str(f), bucket, f"{prefix.rstrip('/')}/{f.name}")


def dataset_dir(ref):
    """A local dataset folder, or a dataset version in the store (downloaded to /work/datasets/<version>)."""
    if Path(ref).is_dir():
        return Path(ref)
    local = WORK / "datasets" / ref
    if not (local / "manifest.json").exists():
        download_prefix(f"datasets/{ref}", local)
    return local
