"""P2 step 2 (from B2): trains the dispute-type classifier, scores it, and packages it.

1. Loads train / val / test from the prepared dataset (and its version from manifest.json).
2. Tries a few candidates, each trained on `train` and scored on `val`; keeps the best. Two model families
   compete: scikit-learn (TF-IDF + logistic regression) and a small PyTorch text classifier.
3. Scores the chosen model ONCE on `test`: overall, per label, per language, confusion matrix.
4. Applies the evaluation gate (thresholds in GATE). Exits with code 1 if the model fails.
5. Saves the package: model.joblib (the model) + metadata.json (version, data, settings, scores).
6. If an MLflow server is given, logs the run there and registers the model if the gate passed, then
   writes the registered version number to <out>/registry_version (an Argo output parameter).

Usage: python train.py --data <dataset folder or version in the store> [--out /work/out] [--tracking-uri http://mlflow:5000]
       (or set MLFLOW_TRACKING_URI instead of --tracking-uri)
"""

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import joblib
import pandas as pd
import sklearn
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, f1_score
from sklearn.pipeline import FeatureUnion, Pipeline

import store
from torch_model import TorchTextClassifier

HERE = Path(__file__).parent

# The evaluation gate: the minimum scores a model needs before it may be registered (step 3).
GATE = {
    "macro_f1": 0.90,             # average F1 over the 6 labels
    "macro_f1_per_language": 0.85,  # the same, separately for English and French
    "recall_per_label": 0.80,     # each label: share of its claims the model finds
}

# The candidates we try. For scikit-learn, C controls how closely the model fits the training data
# (small C = simpler model, large C = follows the training data more closely). The PyTorch candidate
# is a different model family; the platform scores it on the same data with the same rules.
CANDIDATES = [
    {"framework": "scikit-learn", "features": "words", "C": 1.0},
    {"framework": "scikit-learn", "features": "words", "C": 10.0},
    {"framework": "scikit-learn", "features": "words+chars", "C": 1.0},
    {"framework": "scikit-learn", "features": "words+chars", "C": 10.0},
    {"framework": "pytorch", "features": "words+pairs", "dim": 64, "epochs": 8},
]


def describe(cand):
    return " ".join(f"{k}={v}" for k, v in cand.items() if k != "val_macro_f1")


def build_model(cand):
    if cand["framework"] == "pytorch":
        return TorchTextClassifier(dim=cand["dim"], epochs=cand["epochs"])
    return build_sklearn(cand["features"], cand["C"])


def build_sklearn(features, C):
    """Text → numbers (TF-IDF) → a linear classifier (logistic regression), as one pipeline."""
    words = TfidfVectorizer(analyzer="word", ngram_range=(1, 2), min_df=2, sublinear_tf=True)
    if features == "words":
        vectorizer = words
    else:
        # Character pieces (3–5 letters) help with typos ("paymnets") and French word endings.
        chars = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=2, sublinear_tf=True)
        vectorizer = FeatureUnion([("words", words), ("chars", chars)])
    return Pipeline([
        ("tfidf", vectorizer),
        ("classifier", LogisticRegression(C=C, max_iter=2000)),
    ])


def git_commit():
    """The commit the code came from; "-dirty" if mlops/ has uncommitted changes (then the commit
    alone can't reproduce this model; CI always trains from a clean commit). In a container there is
    no .git folder, so the image carries it as GIT_COMMIT (a build argument)."""
    if os.environ.get("GIT_COMMIT"):
        return os.environ["GIT_COMMIT"]
    def git(*args):
        return subprocess.run(["git", *args], capture_output=True, text=True, cwd=HERE, check=True).stdout.strip()
    try:
        commit = git("rev-parse", "--short", "HEAD")
        return commit + ("-dirty" if git("status", "--porcelain", "--", str(HERE.parent)) else "")
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--data", required=True, help="dataset folder, or a dataset version in the store")
    p.add_argument("--out", default=str(store.WORK / "out"))
    p.add_argument("--tracking-uri", default=os.environ.get("MLFLOW_TRACKING_URI"),
                   help="MLflow server; if empty, nothing is logged to MLflow")
    args = p.parse_args()

    data = store.dataset_dir(args.data)
    manifest = json.loads((data / "manifest.json").read_text(encoding="utf-8"))
    train, val, test = (pd.read_parquet(data / f"{s}.parquet") for s in ("train", "val", "test"))
    labels = manifest["labels"]
    print(f"dataset {manifest['version']}: train {len(train)} · val {len(val)} · test {len(test)}\n")

    # --- 2. Choose settings on the validation set -------------------------------------------
    print("choosing settings (trained on train, scored on val):")
    best, best_f1, tried = None, -1.0, []
    for cand in CANDIDATES:
        start = time.perf_counter()
        model = build_model(cand).fit(train["text"], train["label"])
        f1 = f1_score(val["label"], model.predict(val["text"]), average="macro")
        print(f"  {describe(cand):<62} val macro-F1 {f1:.4f}  ({time.perf_counter() - start:.1f}s)")
        tried.append({**cand, "val_macro_f1": f1})
        if f1 > best_f1:
            best, best_f1, best_model = cand, f1, model
    print(f"→ chosen: {best}\n")

    # --- 3. Score once on the test set ------------------------------------------------------
    pred = best_model.predict(test["text"])
    report = classification_report(test["label"], pred, labels=labels, output_dict=True, zero_division=0)
    per_language = {lang: f1_score(g["label"], best_model.predict(g["text"]), average="macro")
                    for lang, g in test.groupby("language")}
    scores = {
        "accuracy": accuracy_score(test["label"], pred),
        "macro_f1": report["macro avg"]["f1-score"],
        "macro_f1_per_language": per_language,
        "per_label": {l: {k: report[l][k] for k in ("precision", "recall", "f1-score", "support")} for l in labels},
    }
    print(f"test set ({len(test)} claims, never seen during training or tuning):")
    print(f"  accuracy {scores['accuracy']:.4f} · macro-F1 {scores['macro_f1']:.4f} · "
          + " · ".join(f"{k} macro-F1 {v:.4f}" for k, v in per_language.items()))
    print(f"\n  {'label':<22}{'precision':>10}{'recall':>9}{'f1':>8}{'claims':>8}")
    for l in labels:
        r = scores["per_label"][l]
        print(f"  {l:<22}{r['precision']:>10.3f}{r['recall']:>9.3f}{r['f1-score']:>8.3f}{int(r['support']):>8}")

    cm = confusion_matrix(test["label"], pred, labels=labels)
    short = [l[:9] for l in labels]
    confusion = "\n".join(["rows = true label, columns = predicted", " " * 22 + "".join(f"{s:>11}" for s in short)]
                          + [f"{l:<22}" + "".join(f"{n:>11}" for n in row) for l, row in zip(labels, cm)])
    print("\n  confusion matrix " + confusion.replace("\n", "\n  "))

    # Examples of mistakes help explain the numbers.
    wrong = test[pred != test["label"]].assign(predicted=pred[pred != test["label"]])
    print(f"\n  {len(wrong)} mistakes; first 5:")
    for _, r in wrong.head(5).iterrows():
        print(f"   true={r['label']:<21} predicted={r['predicted']:<21} {r['text'][:80]}")

    # --- 4. Evaluation gate -----------------------------------------------------------------
    failures = []
    if scores["macro_f1"] < GATE["macro_f1"]:
        failures.append(f"macro-F1 {scores['macro_f1']:.3f} < {GATE['macro_f1']}")
    for lang, f1 in per_language.items():
        if f1 < GATE["macro_f1_per_language"]:
            failures.append(f"{lang} macro-F1 {f1:.3f} < {GATE['macro_f1_per_language']}")
    for l in labels:
        if scores["per_label"][l]["recall"] < GATE["recall_per_label"]:
            failures.append(f"{l} recall {scores['per_label'][l]['recall']:.3f} < {GATE['recall_per_label']}")

    # --- 5. Package -------------------------------------------------------------------------
    # Saved even when the gate fails, so the failure can be investigated; `gate.passed` says which.
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    model_path = out / "model.joblib"
    joblib.dump(best_model, model_path)
    metadata = {
        "model": "dispute-classifier",
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "dataset": {"name": manifest["dataset"], "version": manifest["version"]},
        "code_commit": git_commit(),
        "framework": best["framework"],
        "settings": best,
        "labels": labels,
        "input": {"type": "list of strings", "example": ["I was charged twice at BestElectro for $49.99."]},
        "output": {"type": "list of labels", "example": ["duplicate_charge"]},
        "scores": {"validation_macro_f1": best_f1, "test": scores},
        "gate": {"thresholds": GATE, "passed": not failures, "failures": failures},
        "environment": {"python": platform.python_version(), "scikit-learn": sklearn.__version__,
                        "joblib": joblib.__version__}
                       | ({"torch": __import__("torch").__version__} if best["framework"] == "pytorch" else {}),
        "file_sha256": hashlib.sha256(model_path.read_bytes()).hexdigest(),
    }
    (out / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    print(f"\npackage written: {model_path} ({model_path.stat().st_size / 1024:.0f} KB) + metadata.json")

    # --- 6. Track and register (step 3) ----------------------------------------------------
    if args.tracking_uri:
        from tracking import log_run
        version = log_run(args.tracking_uri, tried, best, best_model, metadata, out, confusion)
        if version:
            (out / "registry_version").write_text(str(version))

    if failures:
        print("\nGATE FAILED:")
        for f in failures:
            print(f"  ✗ {f}")
        sys.exit(1)
    print("\nGATE PASSED: the model may be registered (step 3)")


if __name__ == "__main__":
    main()
