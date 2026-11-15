"""Yearly land-cover shares from the land-cover-ca maps.

Reads landcover/data/maps/lc_<year>.tif (the yearly maps from colab/infer_vm.py, copied from Drive) and
landcover/data/geometry/masks.tif. Map value 255 = no clear observation.

Denominator (same as LakePulse's MODIS shares): labelled LAND pixels, i.e. pixels with a prediction that is not water.
  land-class share  = pixels of the class / land pixels x 100            (forest, cropland, built_up, wetland, other)
  water share      = water pixels / all pixels with a prediction x 100   (landcover outputs only)
A year is left out of an area when less than MIN_COVER of that area has a prediction; coverage is recorded either way.

Areas:
  catchment - the six Lake Simcoe watershed units (polygon union, Ontario Watershed Boundaries)
  strip30m  - land and water within 30 m of the lake shoreline or an OHN stream, inside the catchment
  bbox      - the bounding box LakePulse's MODIS shares use (data/geo/study_regions.json, simcoe_on.catchment_bbox),
              for comparison only

Outputs:
  ../data/external/land_cover_ca.csv   the LakePulse hand-off (contract from the owner, 2026-11-14): only the catchment
                                       forest, cropland and built-up shares, as forest_share / cropland_share /
                                       urban_share, unit "%", dated 1 January, tier "Modeled (Machine learning)".
  landcover/data/results/shares_all.csv  every class and area under lcml_* names (not for LakePulse yet)
  landcover/data/results/shares_coverage.json

Run:  landcover/.venv/bin/python landcover/scripts/build_shares.py --version v2 --run ft-a100-v2cw
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import numpy as np
import rasterio
from pyproj import Transformer
from shapely.geometry import box
from shapely.ops import transform

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lc import config, geometry  # noqa: E402

MIN_COVER = 0.8  # gate choice
LAKE = "simcoe_on"
TIER = "Modeled (Machine learning)"  # LakePulse TIERS; owner hand-off contract 2026-11-14
COLUMNS = ["lake", "variable", "date", "value", "unit", "source", "tier"]
EXPORT = {"forest": "forest_share", "cropland": "cropland_share", "built_up": "urban_share"}  # LakePulse names
REPO = config.LC_ROOT.parent


def bbox_mask(grid) -> np.ndarray:
    b = json.loads((REPO / "data" / "geo" / "study_regions.json").read_text())[LAKE]["catchment_bbox"]
    to_utm = Transformer.from_crs("EPSG:4326", grid.crs, always_xy=True).transform
    poly = box(b["west"], b["south"], b["east"], b["north"]).segmentize(0.01)  # densify so the box edges stay true
    return geometry.rasterize(transform(to_utm, poly), grid)


def shares(pred: np.ndarray, area: np.ndarray, names: list[str]) -> tuple[dict, dict]:
    water = names.index("water")
    has = area & (pred != 255)
    land = has & (pred != water)
    cover = {"area_px": int(area.sum()), "predicted_px": int(has.sum()), "land_px": int(land.sum()),
             "cover": round(float(has.sum() / area.sum()), 4)}
    counts = np.bincount(pred[land], minlength=len(names))[: len(names)]
    out = {n: 100.0 * counts[i] / land.sum() for i, n in enumerate(names) if i != water}
    out["water_share_of_all"] = 100.0 * float((pred[has] == water).sum()) / has.sum()
    return out, cover


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", required=True, help="model version label, e.g. v2")
    ap.add_argument("--run", required=True, help="training run the maps came from")
    args = ap.parse_args()
    cfg = config.load()
    names = cfg["classes"]["names"]
    source = (f"{cfg['model']['name']} {args.version} (fine-tuned Prithvi-EO-2.0-300M, run {args.run}; "
              f"Sentinel-2 L2A summer median)")
    geo = json.loads((config.DATA / "geometry" / "chips.json").read_text())
    grid = geometry.Grid(**geo["grid"])
    with rasterio.open(config.DATA / "geometry" / "masks.tif") as src:
        masks = src.read()
    areas = {"catchment": masks[1] == 1, f"strip{int(cfg['region']['strip_m'])}m": masks[2] == 1, "bbox": bbox_mask(grid)}
    export, full, coverage = [], [], {}
    for path in sorted((config.DATA / "maps").glob("lc_*.tif")):
        year = int(path.stem.split("_")[1])
        with rasterio.open(path) as src:
            pred = src.read(1)
            if pred.shape != masks.shape[1:] or src.transform != grid.transform:
                raise SystemExit(f"{path.name} is not on the region grid")
        coverage[year] = {}
        date = f"{year}-01-01"
        for area, m in areas.items():
            s, cov = shares(pred, m, names)
            coverage[year][area] = cov
            if cov["cover"] < MIN_COVER:
                continue
            for k, v in s.items():
                full.append([LAKE, f"lcml_{area}_{k}" + ("" if k.endswith("_of_all") else "_share"), date, round(v, 3), "%",
                             source, TIER])
            if area == "catchment":
                for cls, var in EXPORT.items():
                    export.append([LAKE, var, date, round(s[cls], 3), "%", source, TIER])
    out = REPO / "data" / "external" / "land_cover_ca.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    for path, rows in ((out, export), (config.DATA / "results" / "shares_all.csv", full)):
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(COLUMNS)
            w.writerows(rows)
    (config.DATA / "results" / "shares_coverage.json").write_text(json.dumps(
        {"min_cover": MIN_COVER, "denominator": "land pixels with a prediction (water and 255 excluded)",
         "source": source, "coverage": coverage}, indent=1))
    print(f"{len(export)} rows -> {out}")
    print(f"{len(full)} rows -> {config.DATA / 'results' / 'shares_all.csv'}")


if __name__ == "__main__":
    main()
