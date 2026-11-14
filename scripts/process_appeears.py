"""Turn downloaded AppEEARS bundles into table rows.

Usage: .venv/bin/python scripts/process_appeears.py
Reads data/raw/appeears/<task key>/*.nc; writes data/processed/simcoe_on_modis_lake.csv,
data/processed/simcoe_on_modis_catchment.csv and data/processed/appeears_processing_report.json.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lakepulse import schema  # noqa: E402
from lakepulse.sources import appeears_process as ap  # noqa: E402


def main() -> None:
    region = json.loads((ROOT / "data" / "geo" / "study_regions.json").read_text())["simcoe_on"]
    raw = ROOT / "data" / "raw" / "appeears"
    out = ROOT / "data" / "processed"
    report = {}
    lake_files = sorted((raw / "simcoe_lake_lst").glob("*.nc"))
    if lake_files:
        rows, info = ap.lake_lst_rows(lake_files, "simcoe_on", region["water_pixel_check"]["clean_cell_centres_modis_sinusoidal_xy_m"])
        schema.write(rows, out / "simcoe_on_modis_lake.csv")
        report["simcoe_lake_lst"] = info
        print(f"lake LST: {len(rows)} rows | {info}")
    else:
        print("lake LST: no bundle yet (run scripts/fetch_appeears.py)")
    catch_files = sorted((raw / "simcoe_catchment").glob("*.nc"))
    if catch_files:
        rows, info = ap.catchment_rows(catch_files, "simcoe_on")
        schema.write(rows, out / "simcoe_on_modis_catchment.csv")
        report["simcoe_catchment"] = info
        print(f"catchment: {len(rows)} rows | {info}")
    else:
        print("catchment: no bundle yet (run scripts/fetch_appeears.py)")
    if report:
        (out / "appeears_processing_report.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
