"""Build the chip split, the shoreline-and-stream strip, and region masks; write a summary and a split map.

Outputs in landcover/data/geometry/:
  chips.json        - every chip window with its split (test / val / train / dropped) and reason, and class counts
  masks.tif         - band 1 region, 2 catchment, 3 strip, 4 test block (uint8 0/1), on the region grid
  split_summary.json, split_map.png

Run:  landcover/.venv/bin/python landcover/scripts/build_geometry.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import rasterio
from pyproj import Transformer
from shapely.geometry import shape
from shapely.ops import transform

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lc import classes, config, geometry  # noqa: E402


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(); ap.add_argument("--v2", action="store_true"); args = ap.parse_args()
    D = config.dirs(args.v2)
    cfg = config.load()
    units = geometry.load_units(cfg, wide=args.v2)
    blk = geometry.blocks(cfg, units)
    lake = geometry.load_lake(cfg)
    grid = geometry.region_grid(cfg, blk["region"])
    chip_px = cfg["chips"]["chip_px"]
    chip_m = chip_px * grid.res

    to_utm = Transformer.from_crs("EPSG:4326", grid.crs, always_xy=True).transform
    hydro = json.loads((config.DATA / "hydro" / "ohn_watercourse_simcoe.geojson").read_text())
    keep = set(cfg["hydro"]["stream_types"])
    streams = [transform(to_utm, shape(f["geometry"])) for f in hydro["features"]
               if f.get("geometry") and (f.get("properties") or {}).get("WATERCOURSE_TYPE") in keep]
    streams = [s for s in streams if s.intersects(blk["catchment"])]
    strip_geom = geometry.strip(cfg, lake, streams, blk["catchment"])

    masks = np.stack([geometry.rasterize(blk["region"], grid), geometry.rasterize(blk["catchment"], grid),
                      geometry.rasterize(strip_geom, grid), geometry.rasterize(blk["test"], grid)]).astype("uint8")
    out = D["geometry"]
    out.mkdir(parents=True, exist_ok=True)
    with rasterio.open(out / "masks.tif", "w", driver="GTiff", height=grid.height, width=grid.width, count=4, dtype="uint8",
                       crs=grid.crs, transform=grid.transform, compress="deflate", tiled=True) as dst:
        dst.write(masks)
        for i, d in enumerate(["region", "catchment", "strip", "test_block"], 1):
            dst.set_band_description(i, d)

    with rasterio.open(D["labels"] / "lcc2020_region.tif") as src:
        merged = classes.merge(src.read(1), classes.lookup(cfg))
    merged[masks[0] == 0] = cfg["classes"]["ignore_index"]
    names = cfg["classes"]["names"]

    chips = geometry.assign_split(geometry.chip_boxes(grid, chip_px), blk, cfg["split"]["gap_chips"] * chip_m)
    records = []
    for ch in chips:
        lab = merged[ch["row"]:ch["row"] + chip_px, ch["col"]:ch["col"] + chip_px].copy()
        if ch["split"] == "test":
            lab[masks[3, ch["row"]:ch["row"] + chip_px, ch["col"]:ch["col"] + chip_px] == 0] = -1
        strip_px = int(masks[2, ch["row"]:ch["row"] + chip_px, ch["col"]:ch["col"] + chip_px][lab >= 0].sum())
        records.append({"id": ch["id"], "row": ch["row"], "col": ch["col"], "split": ch["split"], "why": ch["why"],
                        "bounds": [round(v) for v in ch["geom"].bounds], "labelled_px": int((lab >= 0).sum()),
                        "strip_px": strip_px, "class_px": {n: int((lab == i).sum()) for i, n in enumerate(names)}})
    (out / "chips.json").write_text(json.dumps({"grid": grid.__dict__, "chip_px": chip_px, "chips": records}, indent=0))

    summary = {"grid": grid.__dict__, "streams_in_catchment": len(streams),
               "stream_length_km": round(sum(s.length for s in streams) / 1e3, 1),
               "strip_km2": round(strip_geom.area / 1e6, 1), "catchment_km2": round(blk["catchment"].area / 1e6, 1),
               "region_km2": round(blk["region"].area / 1e6, 1), "test_block_km2": round(blk["test"].area / 1e6, 1),
               "test_block_shoreline_km": round(blk["test"].intersection(lake.boundary).length / 1e3, 1), "splits": {}}
    for s in ("train", "val", "test", None):
        rs = [r for r in records if r["split"] == s]
        key = s or "dropped"
        summary["splits"][key] = {"chips": len(rs)}
        if s:
            summary["splits"][key].update({"labelled_px": sum(r["labelled_px"] for r in rs), "strip_px": sum(r["strip_px"] for r in rs),
                                           "class_px": {n: sum(r["class_px"][n] for r in rs) for n in names}})
        else:
            summary["splits"][key]["why"] = {w: sum(1 for r in rs if r["why"] == w) for w in sorted({r["why"] for r in rs})}
    (out / "split_summary.json").write_text(json.dumps(summary, indent=1))
    print(json.dumps(summary, indent=1))
    _plot(records, blk, lake, strip_geom, chip_px, grid, out / "split_map.png")


def _plot(records, blk, lake, strip_geom, chip_px, grid, path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle

    colour = {"train": "#4c78a8", "val": "#f58518", "test": "#e45756", None: "#dddddd"}
    fig, ax = plt.subplots(figsize=(8, 10))
    step = chip_px * grid.res
    for r in records:
        x0, y0 = r["bounds"][0], r["bounds"][1]
        ax.add_patch(Rectangle((x0, y0), step, step, facecolor=colour[r["split"]], alpha=0.35, edgecolor="white", lw=0.5))
    for g, c, lw in ((blk["region"], "#333333", 0.6), (blk["catchment"], "black", 1.4), (blk["test"], "#b00020", 1.6)):
        for p in getattr(g, "geoms", [g]):
            ax.plot(*p.exterior.xy, color=c, lw=lw)
    for p in getattr(lake, "geoms", [lake]):
        ax.fill(*p.exterior.xy, color="#9ecae1", lw=0)
    for p in getattr(strip_geom, "geoms", [strip_geom]):
        if p.geom_type == "Polygon":
            ax.fill(*p.exterior.xy, color="#2ca02c", lw=0)
    handles = [Rectangle((0, 0), 1, 1, color=colour[k], alpha=0.5) for k in ("train", "val", "test", None)]
    ax.legend(handles, ["train chips", "val chips", "test chips", "dropped (gap / outside)"], loc="lower left", fontsize=8)
    ax.set_title("Land-cover split: black = Simcoe catchment, red = test block, green = 30 m strip", fontsize=9)
    ax.set_aspect("equal")
    ax.set_xticks([]), ax.set_yticks([])
    fig.tight_layout()
    fig.savefig(path, dpi=130)


if __name__ == "__main__":
    main()
