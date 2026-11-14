"""P2 step 3: promotes this run's challenger to champion, but only if it is at least as good.

Uses registry.promote. When the challenger and the champion were trained on different dataset versions,
their logged test scores aren't comparable, so both are re-scored on a shared evaluation set: the golden
raw drop, prepared with the same code as training data (registry.py then removes any claim that either
model saw in training).

Outcomes:
- promoted: writes "true" to --result; publish runs next.
- nothing new (same dataset and same code as the champion, so the same model): not promoted, writes
  "false", exits 0. The run succeeds and Argo skips publish.
- worse than the champion: exits 1. The run fails before publish; production keeps the champion.

Usage: python compare.py --version <N> [--eval-raw raw/golden-2026.csv] [--result /work/promoted]
"""

import argparse
import os
import sys
from pathlib import Path

import mlflow
from mlflow import MlflowClient

import registry
import store
from prepare import build_dataset, clean, read_raw


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--version", required=True, help="the version this run registered as challenger")
    p.add_argument("--eval-raw", default="raw/golden-2026.csv")
    p.add_argument("--result", default=str(store.WORK / "promoted"), help='"true" or "false" (an Argo output parameter)')
    args = p.parse_args()
    result = Path(args.result)

    client = MlflowClient()
    challenger = registry.version_by_alias(client, "challenger")
    if challenger is None or challenger.version != args.version:
        # Another run registered a newer challenger in the meantime; never promote a model we didn't evaluate.
        sys.exit(f"challenger is {challenger.version if challenger else 'missing'}, expected {args.version}: not promoting")

    champion = registry.version_by_alias(client, "champion")
    same = ("dataset_version", "code_commit")
    if champion and all(champion.tags.get(k) == challenger.tags.get(k) for k in same):
        print(f"NOT promoted: v{challenger.version} was trained on the same dataset "
              f"({challenger.tags.get('dataset_version')}) with the same code ({challenger.tags.get('code_commit')}) "
              f"as champion v{champion.version}, so it is the same model. Nothing new to publish.")
        result.write_text("false")
        return
    eval_data = None
    if champion and champion.tags.get("dataset_version") != challenger.tags.get("dataset_version"):
        print(f"v{challenger.version} and champion v{champion.version} were trained on different datasets: "
              f"re-scoring both on {args.eval_raw}")
        df, report = clean(read_raw(args.eval_raw))
        eval_data = store.WORK / "eval"
        build_dataset(df, eval_data, args.eval_raw, report)

    registry.promote(client, force=False, eval_data=eval_data)   # exits 1 if the challenger is worse
    result.write_text("true")


if __name__ == "__main__":
    mlflow.set_tracking_uri(os.environ.get("MLFLOW_TRACKING_URI", "http://mlflow:5000"))
    main()
