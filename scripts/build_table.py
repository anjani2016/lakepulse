"""Assemble the one tidy table: data/lake_trend_table.csv

Inputs (any that exist):
  data/processed/*.csv   NASA-derived rows from the fetch/process scripts
  data/external/*.csv    rows from the separate model-training track (own source name,
                         tier "Modeled (Machine learning)"), same seven columns
  data/practice/*.csv    practice lake (synthetic, labelled)
Adds the derived lake-minus-air rows, validates and writes.

Usage: .venv/bin/python scripts/build_table.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lakepulse import analysis, schema  # noqa: E402


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-external", action="store_true",
                    help="leave out data/external/ (model-training track rows); says so in the output")
    args = ap.parse_args()
    folders = ("processed", "practice") if args.skip_external else ("processed", "external", "practice")
    if args.skip_external:
        print("NOTE: data/external/ left out on request (--skip-external)")
    parts = []
    for folder in folders:
        for f in sorted((ROOT / "data" / folder).glob("*.csv")):
            df = schema.read(f)
            parts.append(df)
            print(f"{folder}/{f.name}: {len(df)} rows")
    if not parts:
        sys.exit("no input tables found")
    table = schema.combine(*parts)
    real = table[~table["lake"].eq("practice_lake")]
    derived = analysis.add_lake_minus_air(real)
    table = schema.combine(table, derived)
    schema.write(table, ROOT / "data" / "lake_trend_table.csv")
    summary = table.groupby(["lake", "tier"]).size()
    print(f"wrote data/lake_trend_table.csv with {len(table)} rows")
    print(summary.to_string())


if __name__ == "__main__":
    main()
