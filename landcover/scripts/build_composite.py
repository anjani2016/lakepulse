"""Build the summer median composite for one or more years on the region grid.

Writes landcover/data/composites/s2_summer_<year>.tif (6 bands float32 reflectance, NaN = no clear observation;
band order as config imagery.model_bands), s2_summer_<year>_count.tif (clear observations per pixel) and
s2_summer_<year>.json (items used, errors, coverage).

Run:  landcover/.venv/bin/python landcover/scripts/build_composite.py 2020 [2017 ...]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import rasterio
from pyproj import Transformer

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lc import composite, config, geometry  # noqa: E402


def region_bbox_wgs84(grid) -> list[float]:
    to_wgs = Transformer.from_crs(grid.crs, "EPSG:4326", always_xy=True)
    xs = [grid.x0, grid.x0 + grid.width * grid.res]
    ys = [grid.y0 - grid.height * grid.res, grid.y0]
    pts = [to_wgs.transform(x, y) for x in xs for y in ys]
    return [min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts)]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("years", nargs="+", type=int)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--v2", action="store_true")
    ap.add_argument("--aot", action="store_true", help="drop pixels with AOT above config imagery.max_aot; writes to composites_aot")
    args = ap.parse_args()
    cfg = config.load()
    blk = geometry.blocks(cfg, geometry.load_units(cfg, wide=args.v2))
    grid = geometry.region_grid(cfg, blk["region"])
    region_mask = geometry.rasterize(blk["region"], grid)
    bbox = region_bbox_wgs84(grid)
    out = config.dirs(args.v2)["composites"]
    max_aot = cfg["imagery"]["max_aot"] if args.aot else None
    if args.aot:
        out = out.with_name(out.name + "_aot")
    out.mkdir(parents=True, exist_ok=True)
    for year in args.years:
        t0 = time.time()
        found = composite.search(cfg, bbox, year)
        items = composite.choose(found, cfg["imagery"]["max_scenes_per_tile"])
        print(f"{year}: {len(found)} items found, {len(items)} chosen", flush=True)
        comp, count, records = composite.median_composite(items, cfg, grid, workers=args.workers,
                                                          log=lambda m: print(m, flush=True), max_aot=max_aot)
        prof = dict(driver="GTiff", height=grid.height, width=grid.width, crs=grid.crs, transform=grid.transform,
                    compress="deflate", tiled=True, blockxsize=256, blockysize=256)
        with rasterio.open(out / f"s2_summer_{year}.tif", "w", count=comp.shape[0], dtype="float32", nodata=np.nan, **prof) as dst:
            dst.write(comp)
            for i, b in enumerate(cfg["imagery"]["model_bands"], 1):
                dst.set_band_description(i, b["model"])
        with rasterio.open(out / f"s2_summer_{year}_count.tif", "w", count=1, dtype="uint16", **prof) as dst:
            dst.write(count, 1)
        covered = np.isfinite(comp[0]) & region_mask
        rec = {"year": year, "window": cfg["imagery"]["window"], "max_cloud": cfg["imagery"]["max_cloud"], "max_aot": max_aot,
               "items_found": len(found), "items_chosen": len(items), "items": records,
               "region_px": int(region_mask.sum()), "region_px_with_clear_obs": int(covered.sum()),
               "region_clear_fraction": round(float(covered.sum() / region_mask.sum()), 4),
               "median_clear_obs_in_region": float(np.median(count[region_mask])),
               "seconds": round(time.time() - t0)}
        (out / f"s2_summer_{year}.json").write_text(json.dumps(rec, indent=1))
        print(json.dumps({k: v for k, v in rec.items() if k != "items"}, indent=1), flush=True)


if __name__ == "__main__":
    main()
