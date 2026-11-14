"""P2 step 0: turns a raw CSV export from the data team into a versioned, training-ready dataset.

1. Reads the raw file (a key under raw/ in the store, or a local path).
2. Cleans it: collapses extra spaces in the text; drops rows that can't be used at all (no text, no label,
   an amount or date that can't be read); drops duplicate claims (same text, ignoring case and spaces).
3. Splits it into train / val / test, stratified by label and language (the B2 split).
4. Writes the parquet files and a manifest whose version is a hash of the content, and uploads them to
   datasets/<version>/. The same raw content always gives the same version, so re-running is harmless.

It doesn't judge whether the data is *good* (enough rows, every label present, no leakage): that is
validate.py's job, the next step. It fails only when the file can't be read, a required column is
missing, or more than 5% of rows are unusable (a sign the export itself is broken).

Usage: python prepare.py --raw raw/claims-2026-11.csv [--out /work/dataset] [--version-file /work/version] [--no-upload]
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

import pandas as pd

import store
from generate_claims import LABELS, content_hash, split

REQUIRED = ["claim_id", "text", "language", "merchant_category", "channel", "amount", "submitted", "label"]
MAX_UNUSABLE = 0.05
SEED = 20261110


class PrepareError(RuntimeError):
    pass


def clean(raw):
    """Returns (clean rows, report). Raises PrepareError if the export itself is broken."""
    missing = [c for c in REQUIRED if c not in raw.columns]
    if missing:
        raise PrepareError(f"required columns missing: {missing}")
    df = raw[REQUIRED].copy()
    df["text"] = df["text"].fillna("").str.split().str.join(" ")
    amount = pd.to_numeric(df["amount"], errors="coerce")
    submitted = pd.to_datetime(df["submitted"], format="%Y-%m-%d", errors="coerce")

    reasons = {
        "no text": df["text"].eq(""),
        "no label": df["label"].isna() | df["label"].fillna("").str.strip().eq(""),
        "bad amount": amount.isna(),
        "bad date": submitted.isna(),
    }
    unusable = pd.concat(reasons.values(), axis=1).any(axis=1)
    report = {"rows_in": len(df), "unusable": {k: int(v.sum()) for k, v in reasons.items() if v.any()}}
    if len(df) == 0 or unusable.mean() > MAX_UNUSABLE:
        raise PrepareError(f"{unusable.sum()} of {len(df)} rows unusable (limit {MAX_UNUSABLE:.0%}): {report['unusable']}")

    # Sort first, so the export's row order can't change which duplicate is kept or how the split falls:
    # the same rows must always give the same dataset version.
    df = df[~unusable].assign(amount=amount[~unusable].astype(float)).sort_values("claim_id", kind="stable")
    key = df["text"].str.lower()
    report["duplicates"] = int(key.duplicated().sum())
    df = df[~key.duplicated()].reset_index(drop=True)
    report["rows_out"] = len(df)
    return df, report


def build_dataset(df, out, source, report):
    """Splits, writes the parquet files + manifest into `out`, and returns the manifest."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    files = {}
    for name, part in split(df, SEED).items():
        part.to_parquet(out / f"{name}.parquet", index=False)
        files[name] = {"rows": len(part), "sha256": content_hash(part)}
    version = hashlib.sha256("".join(files[n]["sha256"] for n in ("train", "val", "test")).encode()).hexdigest()[:12]
    manifest = {
        "dataset": "maple-bank-dispute-claims",
        "version": version,
        "source": source,
        "prepared_by": "training/src/prepare.py",
        "prepare_report": report,
        "labels": LABELS,
        "files": files,
        "label_counts": df["label"].value_counts().sort_index().to_dict(),
        "language_counts": df["language"].value_counts().sort_index().to_dict(),
        "note": "Maple Bank is fictional. All data is synthetic.",
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return manifest


def read_raw(ref):
    path = Path(ref) if Path(ref).exists() else store.download_file(ref, store.WORK / "raw" / Path(ref).name)
    try:
        return pd.read_csv(path, dtype=str, keep_default_na=False, na_values=[""])
    except (pd.errors.ParserError, UnicodeDecodeError) as e:
        raise PrepareError(f"can't read {ref}: {e}")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--raw", required=True, help="key in the store (raw/...) or a local CSV path")
    p.add_argument("--out", default=str(store.WORK / "dataset"))
    p.add_argument("--version-file", help="write the dataset version here (an Argo output parameter)")
    p.add_argument("--no-upload", action="store_true")
    args = p.parse_args()

    try:
        df, report = clean(read_raw(args.raw))
    except PrepareError as e:
        print(f"FAILED: {e}")
        sys.exit(1)
    manifest = build_dataset(df, args.out, args.raw, report)
    version = manifest["version"]

    print(f"prepared {args.raw}: {report['rows_in']} rows in, {report['rows_out']} out "
          f"(unusable {report['unusable'] or 'none'}, duplicates {report['duplicates']})")
    print(f"dataset version {version}: " + " · ".join(f"{n} {f['rows']}" for n, f in manifest["files"].items()))
    if not args.no_upload:
        if store.exists(f"datasets/{version}/"):
            print(f"datasets/{version}/ already in the store (same content as an earlier drop): not uploaded again")
        else:
            store.upload_dir(args.out, f"datasets/{version}")
            print(f"uploaded to s3://{store.MLOPS_BUCKET}/datasets/{version}/")
    if args.version_file:
        Path(args.version_file).write_text(version)


if __name__ == "__main__":
    main()
