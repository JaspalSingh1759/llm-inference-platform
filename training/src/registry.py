"""P2 (from B2): model registry operations: see versions, promote the challenger, roll back, predict by alias.

Aliases are movable names pointing at a version:
  challenger = the newest version that passed the gate (set by train.py)
  champion   = the version production should serve
Promotion and rollback only move the `champion` alias; versions themselves never change.

Usage (MLFLOW_TRACKING_URI or --tracking-uri must point at the server):
  python registry.py status
  python registry.py promote            # challenger → champion, only if it's at least as good
  python registry.py promote --eval-data ../data-pipeline/data/golden
                                        # re-score both on the same data (needed when their datasets differ)
  python registry.py promote --force    # skip the comparison (needs a reason in real life)
  python registry.py rollback           # champion → the previous champion
  python registry.py rollback --to 1    # champion → version 1
  python registry.py predict "they charged me twice"
"""

import argparse
import os
import sys
from pathlib import Path

import mlflow
import numpy as np
import pandas as pd
from sklearn.metrics import f1_score
from mlflow import MlflowClient
from mlflow.exceptions import MlflowException

import store

MODEL = os.environ.get("MODEL_NAME", "dispute-classifier")
COMPARE = ["test_macro_f1", "test_macro_f1_en", "test_macro_f1_fr"]   # challenger must not be worse on any


def dataset_folder(version):
    """The dataset folder for this version, downloaded from the store (datasets/<version>/)."""
    try:
        return store.dataset_dir(version)
    except FileNotFoundError:
        sys.exit(f"dataset {version} not found in the store")


def score_on_shared_data(client, versions, folder):
    """Scores every version on the same evaluation claims, leaving out any claim
    that appears in the training data of one of the versions (that would favour it)."""
    data = pd.concat([pd.read_parquet(f) for f in sorted(Path(folder).glob("*.parquet"))], ignore_index=True)
    seen = set()
    for v in versions:
        train = pd.read_parquet(dataset_folder(v.tags["dataset_version"]) / "train.parquet")
        seen |= set(train["text"].str.lower().str.split().str.join(" "))
    leaked = data["text"].str.lower().str.split().str.join(" ").isin(seen)
    data = data[~leaked].reset_index(drop=True)
    print(f"shared evaluation set: {folder} · {len(data)} claims "
          f"({leaked.sum()} removed because a model trained on them)")
    results = {}
    for v in versions:
        data["pred"] = mlflow.pyfunc.load_model(f"models:/{MODEL}/{v.version}").predict(as_input(data["text"]))
        r = {"test_macro_f1": f1_score(data["label"], data["pred"], average="macro")}
        for lang, group in data.groupby("language"):
            r[f"test_macro_f1_{lang}"] = f1_score(group["label"], group["pred"], average="macro")
        results[v.version] = r
    return results


def as_input(texts):
    """The model's signature (its input contract) is an array of strings; MLflow rejects anything else,
    such as a plain list or a pandas object array."""
    return np.asarray(list(texts), dtype=str)


def version_by_alias(client, alias):
    try:
        return client.get_model_version_by_alias(MODEL, alias)
    except MlflowException:
        return None


def metrics_of(client, version):
    return client.get_run(version.run_id).data.metrics


def status(client):
    versions = sorted(client.search_model_versions(f"name='{MODEL}'"), key=lambda v: int(v.version))
    if not versions:
        print("no registered versions yet")
        return
    # Alias → version map from the registered model (version search results don't include aliases).
    aliases = {}
    for alias, number in client.get_registered_model(MODEL).aliases.items():
        aliases.setdefault(str(number), []).append(alias)
    print(f"{'version':<9}{'aliases':<22}{'dataset':<15}{'macro-F1':>9}{'en':>8}{'fr':>8}  commit")
    for v in versions:
        m = metrics_of(client, v)
        print(f"{v.version:<9}{', '.join(aliases.get(v.version, [])) or '-':<22}{v.tags.get('dataset_version', '?'):<15}"
              f"{m.get('test_macro_f1', 0):>9.4f}{m.get('test_macro_f1_en', 0):>8.4f}{m.get('test_macro_f1_fr', 0):>8.4f}"
              f"  {v.tags.get('code_commit', '?')}")


def promote(client, force, eval_data):
    challenger = version_by_alias(client, "challenger")
    if challenger is None:
        sys.exit("nothing to promote: no version has the 'challenger' alias")
    champion = version_by_alias(client, "champion")

    if champion and champion.version == challenger.version:
        sys.exit(f"version {challenger.version} is already champion")
    if champion and not force:
        same_data = challenger.tags.get("dataset_version") == champion.tags.get("dataset_version")
        if eval_data:
            scores = score_on_shared_data(client, [challenger, champion], eval_data)
            new, old = scores[challenger.version], scores[champion.version]
        elif same_data:
            new, old = metrics_of(client, challenger), metrics_of(client, champion)
        else:
            print(f"challenger v{challenger.version} and champion v{champion.version} were scored on different "
                  "test sets, so their logged scores aren't comparable.\n"
                  "Re-run with --eval-data <dataset folder> to score both on the same claims.")
            sys.exit(1)
        print(f"comparing challenger v{challenger.version} with champion v{champion.version}:")
        worse = []
        for k in COMPARE:
            mark = "✓" if new[k] >= old[k] else "✗"
            print(f"  {mark} {k:<18} {new[k]:.4f} vs {old[k]:.4f}")
            if new[k] < old[k]:
                worse.append(k)
        if worse:
            print(f"NOT promoted: challenger is worse on {', '.join(worse)} (use --force to override)")
            sys.exit(1)

    if champion:
        # Remember who was champion, so rollback knows where to go back to.
        client.set_registered_model_tag(MODEL, "previous_champion", champion.version)
    client.set_registered_model_alias(MODEL, "champion", challenger.version)
    client.delete_registered_model_alias(MODEL, "challenger")
    print(f"PROMOTED: champion → version {challenger.version}"
          + (f" (was {champion.version})" if champion else " (first champion)"))


def rollback(client, to):
    champion = version_by_alias(client, "champion")
    target = to or client.get_registered_model(MODEL).tags.get("previous_champion")
    if not target:
        sys.exit("no previous champion recorded; use --to <version>")
    client.get_model_version(MODEL, target)            # fails clearly if the version doesn't exist
    if champion:
        client.set_registered_model_tag(MODEL, "previous_champion", champion.version)
    client.set_registered_model_alias(MODEL, "champion", target)
    print(f"ROLLED BACK: champion → version {target}" + (f" (was {champion.version})" if champion else ""))


def predict(texts):
    # Callers ask for "the champion", not a version number: promotion and rollback change
    # what they get without changing their code.
    uri = f"models:/{MODEL}@champion"
    model = mlflow.pyfunc.load_model(uri)
    version = model.metadata.run_id[:8]
    for text, label in zip(texts, model.predict(as_input(texts))):
        print(f"{label:<22} ← {text}")
    print(f"(served by {uri}, run {version})")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--tracking-uri", default=os.environ.get("MLFLOW_TRACKING_URI", "http://mlflow:5000"))
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    pr = sub.add_parser("promote")
    pr.add_argument("--force", action="store_true")
    pr.add_argument("--eval-data", help="dataset folder to re-score both versions on")
    rb = sub.add_parser("rollback")
    rb.add_argument("--to")
    pd_ = sub.add_parser("predict")
    pd_.add_argument("texts", nargs="+")
    args = p.parse_args()

    mlflow.set_tracking_uri(args.tracking_uri)
    client = MlflowClient()
    if args.command == "status":
        status(client)
    elif args.command == "promote":
        promote(client, args.force, args.eval_data)
    elif args.command == "rollback":
        rollback(client, args.to)
    else:
        predict(args.texts)


if __name__ == "__main__":
    main()
