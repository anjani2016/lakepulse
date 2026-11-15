"""Fetch GES DISC monthly series for Lake Simcoe.

  merra2   MERRA-2 weather variables at the cell nearest the lake
  imerg    GPM IMERG precipitation over the catchment box
  aerosol  MERRA-2 aerosol optical depth over the catchment box
  no2      OMI OMNO2d daily NO2 over the catchment box, averaged to months
  mod08    MODIS MOD08_M3 satellite aerosol optical depth over the catchment box (LAADS)

Usage: .venv/bin/python scripts/fetch_gesdisc.py [--start 2000-01-01] [--end 2025-12-31] [--only merra2|imerg|aerosol|no2|mod08]
Writes data/processed/simcoe_on_<name>.csv; for NO2 also data/qc/simcoe_on_no2_valid_days.csv
(kept out of data/processed/ because build_table.py reads every CSV there as table rows).
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
    ap.add_argument("--only", choices=["merra2", "imerg", "aerosol", "no2", "mod08"])
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
    if args.only in (None, "aerosol"):
        df = gesdisc.merra2_aer_rows("simcoe_on", region["catchment_bbox"], args.start, args.end)
        schema.write(df, out / "simcoe_on_merra2_aer.csv")
        print(f"wrote {len(df)} rows to data/processed/simcoe_on_merra2_aer.csv")
    if args.only in (None, "mod08"):
        df = gesdisc.mod08_rows("simcoe_on", region["catchment_bbox"], args.start, args.end)
        schema.write(df, out / "simcoe_on_mod08.csv")
        print(f"wrote {len(df)} rows to data/processed/simcoe_on_mod08.csv")
    if args.only in (None, "no2"):
        # OMI starts 2004-10-01; ask from there at the earliest.
        start = max(args.start, "2004-10-01")
        df, days = gesdisc.omno2d_rows("simcoe_on", region["catchment_bbox"], start, args.end)
        schema.write(df, out / "simcoe_on_no2.csv")
        qc = ROOT / "data" / "qc"
        qc.mkdir(parents=True, exist_ok=True)
        days.to_csv(qc / "simcoe_on_no2_valid_days.csv", index=False, date_format="%Y-%m-%d")
        print(f"wrote {len(df)} rows to data/processed/simcoe_on_no2.csv and valid-day counts to "
              "data/qc/simcoe_on_no2_valid_days.csv")


if __name__ == "__main__":
    main()
