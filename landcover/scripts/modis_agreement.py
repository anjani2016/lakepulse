"""Agreement check: the model's yearly class shares against LakePulse's MODIS MCD12Q1 shares, same years.

Reads (read-only) LakePulse's built table data/lake_trend_table.csv for the MODIS rows (forest_share, cropland_share,
urban_share; LakePulse's bounding box around the six catchment units; % of land, water and unclassified excluded) and
landcover/data/results/shares_all.csv for the model (same denominator). Adds a third reference: the 2020 Land Cover of
Canada (the training labels), merged to the same classes, over the same two areas.

Large disagreement is reported, not tuned away.

Writes landcover/data/results/modis_agreement.csv and .json.
Run:  landcover/.venv/bin/python landcover/scripts/modis_agreement.py
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import numpy as np
import rasterio

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lc import classes, config  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_shares import EXPORT, LAKE, REPO, bbox_mask  # noqa: E402

MODIS_PREFIX = "MODIS MCD12Q1"


def label_shares(cfg, areas) -> dict:
    """2020 Land Cover of Canada shares (% of land, water excluded) per area."""
    names = cfg["classes"]["names"]
    water = names.index("water")
    with rasterio.open(config.DATA / "labels" / "lcc2020_region.tif") as src:
        lab = classes.merge(src.read(1), classes.lookup(cfg))
    out = {}
    for area, m in areas.items():
        land = m & (lab >= 0) & (lab != water)
        counts = np.bincount(lab[land], minlength=len(names))
        out[area] = {n: round(100.0 * counts[i] / land.sum(), 3) for i, n in enumerate(names) if i != water}
    return out


def main() -> None:
    cfg = config.load()
    table = list(csv.DictReader(open(REPO / "data" / "lake_trend_table.csv")))
    modis = {(r["variable"], r["date"][:4]): float(r["value"]) for r in table
             if r["lake"] == LAKE and r["source"].startswith(MODIS_PREFIX) and r["variable"] in EXPORT.values()}
    if not modis:
        raise SystemExit("no MODIS land-cover rows in data/lake_trend_table.csv; build the LakePulse table first")
    model = {(r["variable"], r["date"][:4]): float(r["value"]) for r in csv.DictReader(open(config.DATA / "results" / "shares_all.csv"))}
    geo = json.loads((config.DATA / "geometry" / "chips.json").read_text())
    from lc.geometry import Grid
    grid = Grid(**geo["grid"])
    with rasterio.open(config.DATA / "geometry" / "masks.tif") as src:
        catchment = src.read(2) == 1
    lcc = label_shares(cfg, {"catchment": catchment, "bbox": bbox_mask(grid)})
    rows = []
    years = sorted({y for (_, y) in model})
    for cls, var in EXPORT.items():
        for y in years:
            m_c, m_b = model.get((f"lcml_catchment_{cls}_share", y)), model.get((f"lcml_bbox_{cls}_share", y))
            mo = modis.get((var, y))
            rows.append({"year": y, "variable": var, "modis_bbox": mo, "model_bbox": m_b, "model_catchment": m_c,
                         "model_minus_modis_bbox": None if mo is None or m_b is None else round(m_b - mo, 3),
                         "lcc2020_bbox": lcc["bbox"][cls], "lcc2020_catchment": lcc["catchment"][cls]})
    out = config.DATA / "results" / "modis_agreement.csv"
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    summary = {}
    for var in EXPORT.values():
        d = [r["model_minus_modis_bbox"] for r in rows if r["variable"] == var and r["model_minus_modis_bbox"] is not None]
        summary[var] = {"years": len(d), "mean_difference_pts": round(float(np.mean(d)), 2), "min": min(d), "max": max(d),
                        "lcc2020_bbox": lcc["bbox"][[k for k, v in EXPORT.items() if v == var][0]],
                        "modis_2020_bbox": modis.get((var, "2020"))}
    (config.DATA / "results" / "modis_agreement.json").write_text(json.dumps(
        {"area": "LakePulse bounding box (study_regions.json simcoe_on.catchment_bbox) for MODIS and model_bbox",
         "denominator": "% of land; water and unclassified excluded", "by_variable": summary, "lcc2020_all_classes": lcc}, indent=1))
    print(json.dumps(summary, indent=1))
    print(json.dumps(lcc, indent=1))


if __name__ == "__main__":
    main()
