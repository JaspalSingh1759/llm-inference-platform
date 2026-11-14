"""Init container: downloads one published model version from the model store before the server starts.

Reads s3://<MODELS_BUCKET>/<MODEL_NAME>/<MODEL_VERSION>/{model.joblib,metadata.json} into MODEL_DIR.
The server then verifies the checksum, so a corrupted or swapped file is still refused. Exits non-zero
if the version doesn't exist, which keeps the pod in Init and the old pods serving.

Credentials: read-only keys for the models bucket locally; an IAM role through Pod Identity on EKS.
"""

import os
import sys
from pathlib import Path

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

FILES = ("model.joblib", "metadata.json")


def main():
    bucket = os.environ.get("MODELS_BUCKET", "models")
    name = os.environ.get("MODEL_NAME", "dispute-classifier")
    version = os.environ["MODEL_VERSION"]
    dest = Path(os.environ.get("MODEL_DIR", "/model"))
    s3 = boto3.client("s3", endpoint_url=os.environ.get("S3_ENDPOINT_URL") or None,
                      config=Config(s3={"addressing_style": "path"}))
    for f in FILES:
        try:
            s3.download_file(bucket, f"{name}/{version}/{f}", str(dest / f))
        except ClientError as e:
            sys.exit(f"can't download s3://{bucket}/{name}/{version}/{f}: {e}")
    print(f"fetched {name} {version} from s3://{bucket}/{name}/{version}/")


if __name__ == "__main__":
    main()
