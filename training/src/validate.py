"""P2 step 1 (from B2): data validation, the "unit tests for data". Runs before any training.

Checks each split against a schema (pandera) and then checks the dataset as a whole:
no text shared between splits, every label present in every split, no class too small,
and the files still match the hashes in the manifest. Exits with code 1 on any failure,
so a pipeline stops here instead of training on bad data.

Usage: python validate.py <dataset folder or dataset version in the store>
"""

import json
import sys
from pathlib import Path

import pandas as pd
import pandera.pandas as pa

import store
from generate_claims import LABELS, content_hash

SCHEMA = pa.DataFrameSchema(
    {
        "claim_id": pa.Column(str, pa.Check.str_matches(r"^CLM-\d{6}$"), unique=True),
        "text": pa.Column(str, pa.Check.str_length(15, 600)),
        "language": pa.Column(str, pa.Check.isin(["en", "fr"])),
        "merchant_category": pa.Column(str),
        "channel": pa.Column(str, pa.Check.isin(["online", "in_store"])),
        "amount": pa.Column(float, pa.Check.in_range(0.01, 50_000)),
        "submitted": pa.Column(str, pa.Check.str_matches(r"^\d{4}-\d{2}-\d{2}$")),
        "label": pa.Column(str, pa.Check.isin(LABELS)),
    },
    strict=True,          # no unexpected columns
    coerce=False,
)

MIN_ROWS = {"train": 1000, "val": 200, "test": 200}
MIN_CLASS_SHARE = 0.08    # with 6 labels a fair share is ~0.167; alert if one falls below half of that


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    folder = store.dataset_dir(sys.argv[1])
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    failures = []

    splits = {}
    for name in ("train", "val", "test"):
        df = pd.read_parquet(folder / f"{name}.parquet")
        splits[name] = df
        try:
            SCHEMA.validate(df, lazy=True)       # lazy = report every problem, not just the first
        except pa.errors.SchemaErrors as e:
            failures.append(f"{name}: schema\n{e.failure_cases.head(20).to_string()}")
        if len(df) < MIN_ROWS[name]:
            failures.append(f"{name}: only {len(df)} rows (minimum {MIN_ROWS[name]})")
        missing = set(LABELS) - set(df["label"])
        if missing:
            failures.append(f"{name}: labels missing {sorted(missing)}")
        shares = df["label"].value_counts(normalize=True)
        small = shares[shares < MIN_CLASS_SHARE]
        if not small.empty:
            failures.append(f"{name}: classes below {MIN_CLASS_SHARE:.0%}: {small.round(3).to_dict()}")
        if content_hash(df) != manifest["files"][name]["sha256"]:
            failures.append(f"{name}: content doesn't match the manifest hash (file changed after generation?)")

    # Leakage: the same claim text in two splits makes test scores look better than reality.
    def norm(s):
        return set(s.str.lower().str.split().str.join(" "))
    for a, b in (("train", "val"), ("train", "test"), ("val", "test")):
        overlap = norm(splits[a]["text"]) & norm(splits[b]["text"])
        if overlap:
            failures.append(f"leakage: {len(overlap)} texts in both {a} and {b}")
    ids = pd.concat(s["claim_id"] for s in splits.values())
    if ids.duplicated().any():
        failures.append("leakage: claim_id appears in more than one split")

    if failures:
        print(f"FAILED: dataset {manifest['version']}")
        for f in failures:
            print(f"  ✗ {f}")
        sys.exit(1)

    total = sum(len(s) for s in splits.values())
    print(f"PASSED: dataset {manifest['version']} ({total} rows)")
    for name, df in splits.items():
        print(f"  {name:5} {len(df):>5} rows · fr {df['language'].eq('fr').mean():.0%} · "
              f"smallest class {df['label'].value_counts(normalize=True).min():.1%}")


if __name__ == "__main__":
    main()
