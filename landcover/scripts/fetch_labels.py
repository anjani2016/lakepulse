"""Read the 2020 Land Cover of Canada over the region only (windowed COG read) and put it on the region's 30 m UTM grid.

Open Government Licence - Canada. Writes landcover/data/labels/lcc2020_region.tif (uint8, the map's own class values,
nearest-neighbour resampled from EPSG:3979 to the region grid) and fetch_record.json. Class merging happens later.

Run:  landcover/.venv/bin/python landcover/scripts/fetch_labels.py
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date
from pathlib import Path

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.warp import reproject, transform_bounds
from rasterio.windows import from_bounds

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lc import config, geometry  # noqa: E402

os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(); ap.add_argument("--v2", action="store_true"); args = ap.parse_args()
    cfg = config.load()
    units = geometry.load_units(cfg, wide=args.v2)
    blk = geometry.blocks(cfg, units)
    grid = geometry.region_grid(cfg, blk["region"])
    west, north = grid.x0, grid.y0
    east, south = west + grid.width * grid.res, north - grid.height * grid.res
    with rasterio.open("/vsicurl/" + cfg["labels"]["url"]) as src:
        b = transform_bounds(grid.crs, src.crs, west, south, east, north, densify_pts=21)
        pad = 300  # metres, so edge pixels have source data
        win = from_bounds(b[0] - pad, b[1] - pad, b[2] + pad, b[3] + pad, src.transform).round_offsets().round_lengths()
        raw = src.read(1, window=win)
        src_tf, src_crs, nodata = src.window_transform(win), src.crs, src.nodata
    out = np.zeros((grid.height, grid.width), dtype=np.uint8)
    reproject(raw, out, src_transform=src_tf, src_crs=src_crs, dst_transform=grid.transform, dst_crs=grid.crs,
              resampling=Resampling.nearest, src_nodata=nodata, dst_nodata=0)
    d = config.dirs(args.v2)["labels"]
    d.mkdir(parents=True, exist_ok=True)
    with rasterio.open(d / "lcc2020_region.tif", "w", driver="GTiff", height=grid.height, width=grid.width, count=1,
                       dtype="uint8", crs=grid.crs, transform=grid.transform, nodata=0, compress="deflate", tiled=True) as dst:
        dst.write(out, 1)
    vals, counts = np.unique(out, return_counts=True)
    rec = {"source": cfg["labels"]["url"], "window_px": [int(win.width), int(win.height)], "grid": grid.__dict__,
           "retrieved_on": date.today().isoformat(), "licence": cfg["labels"]["licence"],
           "value_counts": {int(v): int(c) for v, c in zip(vals, counts)}}
    (d / "fetch_record.json").write_text(json.dumps(rec, indent=1))
    print(json.dumps(rec, indent=1))


if __name__ == "__main__":
    main()
