"""Fetch MERRA-2 (point) and IMERG (catchment box) monthly series for Lake Simcoe.

Usage: .venv/bin/python scripts/fetch_gesdisc.py [--start 2000-01-01] [--end 2025-12-31] [--only merra2|imerg]
Writes data/processed/simcoe_on_merra2.csv and data/processed/simcoe_on_imerg.csv.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lakepulse import schema  # noqa: E402
from lakepulse.sources import gesdisc  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2000-01-01")
    ap.add_argument("--end", default="2025-12-31")
    ap.add_argument("--only", choices=["merra2", "imerg"])
    args = ap.parse_args()
    region = json.loads((ROOT / "data" / "geo" / "study_regions.json").read_text())["simcoe_on"]
    lat, lon = region["sample_point"]
    out = ROOT / "data" / "processed"
    if args.only in (None, "merra2"):
        df = gesdisc.merra2_rows("simcoe_on", lat, lon, args.start, args.end)
        schema.write(df, out / "simcoe_on_merra2.csv")
        print(f"wrote {len(df)} rows to data/processed/simcoe_on_merra2.csv")
    if args.only in (None, "imerg"):
        df = gesdisc.imerg_rows("simcoe_on", region["catchment_bbox"], args.start, args.end)
        schema.write(df, out / "simcoe_on_imerg.csv")
        print(f"wrote {len(df)} rows to data/processed/simcoe_on_imerg.csv")


if __name__ == "__main__":
    main()
