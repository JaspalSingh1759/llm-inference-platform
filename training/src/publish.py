"""P2 step 4: publishes the promoted model to the model store, where serving pulls it from.

Writes models/<model name>/v<N>/model.joblib + metadata.json. Before uploading it checks that:
- version N is the registry's champion (only promoted models are published);
- model.joblib still matches the checksum in metadata.json;
- v<N> doesn't exist yet: published versions are never overwritten, so v<N> always means the same bytes.

metadata.json gains a "registry" section (name, version, publish time), so the serving pod can report
exactly which registered version it is running.

Usage: python publish.py <package folder> --version <N>
"""

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import mlflow
from mlflow import MlflowClient

import registry
import store


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("package")
    p.add_argument("--version", required=True)
    args = p.parse_args()

    package = Path(args.package)
    metadata = json.loads((package / "metadata.json").read_text(encoding="utf-8"))
    model_file = package / "model.joblib"
    if hashlib.sha256(model_file.read_bytes()).hexdigest() != metadata["file_sha256"]:
        sys.exit("model.joblib doesn't match the checksum in metadata.json: not publishing")

    champion = registry.version_by_alias(MlflowClient(), "champion")
    if champion is None or champion.version != args.version:
        sys.exit(f"v{args.version} is not the champion: not publishing")

    prefix = f"{registry.MODEL}/v{args.version}"
    if store.exists(prefix + "/", store.MODELS_BUCKET):
        sys.exit(f"s3://{store.MODELS_BUCKET}/{prefix}/ already exists; published versions are never overwritten")

    metadata["registry"] = {"name": registry.MODEL, "version": args.version,
                            "published": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    out = store.WORK / "publish"
    out.mkdir(parents=True, exist_ok=True)
    (out / "model.joblib").write_bytes(model_file.read_bytes())
    (out / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    store.upload_dir(out, prefix, store.MODELS_BUCKET)
    print(f"PUBLISHED: s3://{store.MODELS_BUCKET}/{prefix}/ ({metadata['framework']}, dataset "
          f"{metadata['dataset']['version']}, test macro-F1 {metadata['scores']['test']['macro_f1']:.4f})")
    print(f"To serve it: set MODEL_VERSION=v{args.version} in deploy/local/classifier.yaml and run make deploy")


if __name__ == "__main__":
    mlflow.set_tracking_uri(os.environ.get("MLFLOW_TRACKING_URI", "http://mlflow:5000"))
    main()
