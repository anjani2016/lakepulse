"""Adversarial probe chips, all taken from the held-out test area (or the catchment edge), labelled with the 2020 map.

  cloudy      - one summer 2020 scene with high scene cloud cover, NO cloud masking, over a test chip
  winter      - one winter (Jan-Mar 2020) low-cloud scene, no SCL masking (snow is the point), over the same test chip
  edge        - the test chip whose labelled area is cut most by the region boundary (summer composite)
  all_water   - a composite window with all labels water, lying wholly in chips no model trained or validated on
                (test chips and gap-dropped chips); the window with the MOST water is used. No 100% water window exists there
                (best 96.5%, 2026-11-14), because Cook's Bay is narrower than one chip and open-lake chips are in training
  half_water  - a test-block composite window whose labelled pixels are closest to half water, half land

Writes landcover/data/chips/probes/<name>_{img,label,strip}.tif and probes.json. Scored later with the same metrics.

Run:  landcover/.venv/bin/python landcover/scripts/build_probes.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import rasterio
from rasterio.enums import Resampling

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lc import classes, composite, config, geometry  # noqa: E402
from lc.imagery import band_scaling  # noqa: E402


def write(name, img, lab, strip, transform, crs, out):
    base = dict(driver="GTiff", height=img.shape[1], width=img.shape[2], crs=crs, transform=transform, compress="deflate")
    for suffix, arr, dtype in (("img", np.nan_to_num(img, nan=0.0), "float32"), ("label", lab[None], "int16"), ("strip", strip[None], "uint8")):
        with rasterio.open(out / f"{name}_{suffix}.tif", "w", count=arr.shape[0], dtype=dtype, **base) as dst:
            dst.write(arr.astype(dtype))


def single_scene(item, cfg, grid_chip):
    """Six bands of one item on a chip grid, reflectance as in training, no SCL masking."""
    bands = []
    for b in cfg["imagery"]["model_bands"]:
        scale, offset, nodata = band_scaling(item, b["asset"])
        dn = composite._warp(item["assets"][b["asset"]]["href"], grid_chip, Resampling.bilinear, np.float32)
        r = dn * np.float32(scale) + np.float32(offset)
        r[dn <= 0] = np.nan
        bands.append(r)
    return np.stack(bands)


def main() -> None:
    cfg = config.load()
    chip = cfg["chips"]["chip_px"]
    ign = cfg["classes"]["ignore_index"]
    geo = json.loads((config.DATA / "geometry" / "chips.json").read_text())
    g = geometry.Grid(**geo["grid"])
    with rasterio.open(config.DATA / "composites" / "s2_summer_2020.tif") as src:
        comp = src.read()
    with rasterio.open(config.DATA / "labels" / "lcc2020_region.tif") as src:
        lab_all = classes.merge(src.read(1), classes.lookup(cfg))
    with rasterio.open(config.DATA / "geometry" / "masks.tif") as src:
        masks = src.read()
    lab_all[masks[0] == 0] = ign
    water = cfg["classes"]["names"].index("water")
    out = config.DATA / "chips" / "probes"
    out.mkdir(parents=True, exist_ok=True)
    rec = {}

    def window(r, c):
        return (slice(r, r + chip), slice(c, c + chip))

    def tf(r, c):
        return rasterio.windows.transform(rasterio.windows.Window(c, r, chip, chip), g.transform)

    # pixels no model saw in training or validation: test chips and chips dropped by the gap rule
    unseen = np.zeros(lab_all.shape, dtype=bool)
    for ch in geo["chips"]:
        if ch["split"] == "test" or (ch["split"] is None and ch["why"].startswith("gap")):
            unseen[ch["row"]:ch["row"] + chip, ch["col"]:ch["col"] + chip] = True
    # composite-based probes: slide at a 32 px step
    best_water, best_half = None, None
    for r in range(0, g.height - chip, 32):
        for c in range(0, g.width - chip, 32):
            lab = lab_all[window(r, c)]
            wf = float((lab == water).mean())
            if unseen[window(r, c)].all() and (best_water is None or wf > best_water[2]):
                best_water = (r, c, wf)
            if masks[3][window(r, c)].mean() < 0.99:
                continue
            if (lab >= 0).all() and (best_half is None or abs(wf - 0.5) < best_half[2]):
                best_half = (r, c, abs(wf - 0.5))
    test_chips = [ch for ch in geo["chips"] if ch["split"] == "test"]
    edge = min(test_chips, key=lambda ch: masks[0][window(ch["row"], ch["col"])].mean())
    for name, rc in (("all_water", best_water and best_water[:2]), ("half_water", best_half and best_half[:2]), ("edge", (edge["row"], edge["col"]))):
        if rc is None:
            rec[name] = {"status": "no window found"}
            continue
        r, c = rc
        lab = lab_all[window(r, c)].copy()
        img = comp[(slice(None),) + window(r, c)]
        lab[~np.isfinite(img).all(axis=0)] = ign
        write(name, img, lab, masks[2][window(r, c)], tf(r, c), g.crs, out)
        rec[name] = {"row": r, "col": c, "water_fraction": round(float((lab == water).mean()), 3),
                     "in_region_fraction": round(float(masks[0][window(r, c)].mean()), 3)}

    # single-scene probes over the test chip with the most labelled pixels
    target = max(test_chips, key=lambda ch: ch["labelled_px"])
    r, c = target["row"], target["col"]
    gc = geometry.Grid(g.crs, g.x0 + c * g.res, g.y0 - r * g.res, g.res, chip, chip)
    from pyproj import Transformer
    to_wgs = Transformer.from_crs(g.crs, "EPSG:4326", always_xy=True)
    x0, y1 = gc.x0, gc.y0
    x1, y0 = x0 + chip * g.res, y1 - chip * g.res
    pts = [to_wgs.transform(x, y) for x in (x0, x1) for y in (y0, y1)]
    bbox = [min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts)]
    lab = lab_all[window(r, c)].copy()
    lab[masks[3][window(r, c)] == 0] = ign
    for name, win, lo, hi in (("cloudy", ("06-15", "09-15"), 60, 95), ("winter", ("01-15", "03-15"), 0, 20)):
        items = composite.search(cfg, bbox, 2020, window=win, max_cloud=hi)
        items = [i for i in items if float(i["properties"]["eo:cloud_cover"]) >= lo]
        items.sort(key=lambda i: (-float(i["properties"]["eo:cloud_cover"]) if name == "cloudy" else float(i["properties"]["eo:cloud_cover"])))
        chosen = None
        for it in items:
            img = single_scene(it, cfg, gc)
            if np.isfinite(img).all(axis=0).mean() > 0.9:  # whole chip inside the swath
                chosen = it
                break
        if chosen is None:
            rec[name] = {"status": "no covering scene", "candidates": len(items)}
            continue
        write(name, img, lab, masks[2][window(r, c)], gc.transform, g.crs, out)
        rec[name] = {"chip": target["id"], "scene": chosen["id"], "cloud": chosen["properties"]["eo:cloud_cover"]}
    (out / "probes.json").write_text(json.dumps(rec, indent=1))
    print(json.dumps(rec, indent=1))


if __name__ == "__main__":
    main()
