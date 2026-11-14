"""Plays the data team: turns the B2 datasets into raw CSV exports, the way real exports arrive.

Each export is all rows of one B2 dataset in one file, shuffled, with some mess added:
- about 2% duplicates (the same claim exported twice, sometimes with different spacing or capitals);
- about 1% unusable rows (empty text, or "N/A" as the amount).

Plus two broken exports for the drills:
- claims-broken.csv: almost all "not_received" claims are missing (the export filter was wrong);
- claims-corrupt.csv: the label column is missing.

Usage: python make_raw_drops.py <B2 data folder> <output folder>
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

DROPS = {  # B2 dataset folder → raw export name
    "claims": "claims-2026-11.csv",
    "claims-dec": "claims-2026-12.csv",
    "claims-noisy": "claims-noisy.csv",
    "golden": "golden-2026.csv",
}


def load(folder):
    return pd.concat([pd.read_parquet(folder / f"{s}.parquet") for s in ("train", "val", "test")], ignore_index=True)


def messy(df, seed):
    rng = np.random.default_rng(seed)
    df = df.sample(frac=1, random_state=seed).reset_index(drop=True)
    dups = df.sample(frac=0.02, random_state=seed).copy()
    half = len(dups) // 2
    dups.iloc[:half, dups.columns.get_loc("text")] = "  " + dups["text"].iloc[:half].str.upper() + "  "
    bad = df.sample(frac=0.01, random_state=seed + 1).index
    df["amount"] = df["amount"].map(lambda a: f"{a:.2f}")
    for i, idx in enumerate(bad):
        if i % 2:
            df.loc[idx, "text"] = ""
        else:
            df.loc[idx, "amount"] = "N/A"
    dups["amount"] = dups["amount"].map(lambda a: f"{a:.2f}")
    out = pd.concat([df, dups], ignore_index=True)
    return out.iloc[rng.permutation(len(out))]


def main():
    src, out = Path(sys.argv[1]), Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    for i, (folder, name) in enumerate(DROPS.items()):
        df = messy(load(src / folder), seed=100 + i)
        df.to_csv(out / name, index=False)
        print(f"{name:<22} {len(df):>6} rows   (from {folder})")

    nov = messy(load(src / "claims"), seed=100)
    not_received = nov.index[nov["label"] == "not_received"]
    broken = nov.drop(not_received[: int(len(not_received) * 0.95)])
    broken.to_csv(out / "claims-broken.csv", index=False)
    print(f"{'claims-broken.csv':<22} {len(broken):>6} rows   (95% of not_received removed)")
    nov.drop(columns=["label"]).to_csv(out / "claims-corrupt.csv", index=False)
    print(f"{'claims-corrupt.csv':<22} {len(nov):>6} rows   (no label column)")


if __name__ == "__main__":
    main()
