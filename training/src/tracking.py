"""P2 (from B2): records a training run in MLflow and, if the gate passed, registers the model.

What ends up in MLflow for one `train.py` run:
  experiment "dispute-classifier"
  └─ run "train-<dataset version>"            params, metrics, tags, metadata.json, the model
     ├─ child run per candidate setting       its settings and validation score
  registered model "dispute-classifier"
  └─ version N, alias "challenger"            only when the gate passed
"""

import json
import os
from pathlib import Path

import mlflow
import numpy as np
from mlflow import MlflowClient
from mlflow.models import infer_signature

MODEL_NAME = os.environ.get("MODEL_NAME", "dispute-classifier")
EXPERIMENT = MODEL_NAME


def log_run(tracking_uri, candidates, chosen, model, metadata, artifacts_dir, confusion):
    mlflow.set_tracking_uri(tracking_uri)
    mlflow.set_experiment(EXPERIMENT)
    scores = metadata["scores"]["test"]
    gate = metadata["gate"]

    with mlflow.start_run(run_name=f"train-{metadata['dataset']['version']}") as run:
        # Every setting we tried, as child runs, so the comparison is visible in the UI.
        for cand in candidates:
            name = "-".join(str(v) for k, v in cand.items() if k in ("framework", "features", "C"))
            with mlflow.start_run(run_name=name, nested=True):
                mlflow.log_params({k: v for k, v in cand.items() if k != "val_macro_f1"})
                mlflow.log_metric("val_macro_f1", cand["val_macro_f1"])

        # Parameters: inputs that define this run (data + chosen settings).
        mlflow.log_params({"dataset_version": metadata["dataset"]["version"], **chosen})
        # Tags: searchable labels about the run.
        mlflow.set_tags({"code_commit": metadata["code_commit"], "gate_passed": str(gate["passed"]),
                         "framework": metadata["framework"], "scikit_learn": metadata["environment"]["scikit-learn"]})
        # Metrics: the results.
        metrics = {"val_macro_f1": metadata["scores"]["validation_macro_f1"],
                   "test_accuracy": scores["accuracy"], "test_macro_f1": scores["macro_f1"]}
        metrics |= {f"test_macro_f1_{lang}": v for lang, v in scores["macro_f1_per_language"].items()}
        metrics |= {f"test_recall_{label}": v["recall"] for label, v in scores["per_label"].items()}
        mlflow.log_metrics(metrics)
        # Files: the metadata and the confusion matrix, for anyone investigating later.
        mlflow.log_artifact(str(Path(artifacts_dir) / "metadata.json"))
        mlflow.log_text(confusion, "confusion_matrix.txt")

        # The model itself, in MLflow's standard format, with its input/output contract (signature).
        example = np.array(metadata["input"]["example"])
        signature = infer_signature(example, model.predict(example))
        info = mlflow.sklearn.log_model(
            model, name="model", signature=signature, input_example=example,
            registered_model_name=MODEL_NAME if gate["passed"] else None,   # the gate decides
        )

    print(f"\nMLflow: run {run.info.run_id[:8]} logged to experiment '{EXPERIMENT}' ({tracking_uri})")
    if not gate["passed"]:
        print("MLflow: gate failed, so the model was NOT registered")
        return None

    version = info.registered_model_version
    client = MlflowClient()
    client.set_registered_model_alias(MODEL_NAME, "challenger", version)
    client.set_model_version_tag(MODEL_NAME, version, "dataset_version", metadata["dataset"]["version"])
    client.set_model_version_tag(MODEL_NAME, version, "code_commit", metadata["code_commit"])
    client.set_model_version_tag(MODEL_NAME, version, "framework", metadata["framework"])
    client.update_model_version(MODEL_NAME, version, description=model_card(metadata))
    print(f"MLflow: registered {MODEL_NAME} version {version} with alias 'challenger'")
    return version


def model_card(m):
    """A short model card: what the model is for, what it was trained on, how good it is, its limits."""
    s = m["scores"]["test"]
    langs = ", ".join(f"{k} {v:.3f}" for k, v in s["macro_f1_per_language"].items())
    return (
        f"Dispute-type classifier for Maple Bank (fictional; synthetic data).\n\n"
        f"Intended use: route a customer's dispute claim (English or French text) to one of "
        f"{len(m['labels'])} dispute types. Not for decisions about the customer without analyst review.\n\n"
        f"Training data: {m['dataset']['name']} version {m['dataset']['version']}.\n"
        f"Model: {'PyTorch EmbeddingBag text classifier' if m['framework'] == 'pytorch' else 'TF-IDF + logistic regression'}, "
        f"settings {json.dumps(m['settings'])}.\n"
        f"Test results: macro-F1 {s['macro_f1']:.3f}, accuracy {s['accuracy']:.3f}; per language: {langs}.\n\n"
        f"Known limits: trained on template-generated claims; confidence drops on wording unlike the "
        f"templates, so real-world accuracy will be lower. Code commit {m['code_commit']}."
    )
