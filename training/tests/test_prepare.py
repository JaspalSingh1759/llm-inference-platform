import subprocess
import sys

import pandas as pd
import pytest

from generate_claims import build
from prepare import PrepareError, build_dataset, clean


@pytest.fixture(scope="module")
def raw():
    """A raw export as the data team sends it: strings everywhere, no claim IDs reused."""
    df = build(2400, 0.25, 0.0, seed=1)
    return df.assign(amount=df["amount"].map(lambda a: f"{a:.2f}")).astype(str)


def test_duplicates_and_unusable_rows_are_dropped(raw):
    dup = raw.iloc[[0]].assign(text="  " + raw["text"].iloc[0].upper() + "  ")   # same claim, different spacing/case
    bad = raw.iloc[[1, 2]].copy()
    bad.loc[bad.index[0], "text"] = None
    bad.loc[bad.index[1], "amount"] = "N/A"
    df, report = clean(pd.concat([raw, dup, bad], ignore_index=True))
    assert report["duplicates"] == 1
    assert report["unusable"] == {"no text": 1, "bad amount": 1}
    assert df["text"].str.lower().is_unique
    assert df["amount"].dtype == float


def test_missing_column_fails(raw):
    with pytest.raises(PrepareError, match="label"):
        clean(raw.drop(columns=["label"]))


def test_too_many_unusable_rows_fails(raw):
    broken = raw.copy()
    broken.loc[broken.index[:200], "amount"] = "N/A"     # ~8% > 5%
    with pytest.raises(PrepareError, match="unusable"):
        clean(broken)


def test_same_content_same_version_and_validation_passes(raw, tmp_path):
    a = build_dataset(*clean(raw)[:1], tmp_path / "a", "raw/x.csv", {})
    shuffled = raw.sample(frac=1, random_state=3)          # the same export, rows in another order
    b = build_dataset(*clean(shuffled)[:1], tmp_path / "b", "raw/x.csv", {})
    assert a["version"] == b["version"]
    result = subprocess.run([sys.executable, "validate.py", str(tmp_path / "a")], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout
