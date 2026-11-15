"""Summer median composite of Sentinel-2 L2A on the region grid.

Per year: search Earth Search for items in the summer window under max_cloud, keep one item per (tile, date) (the
latest processing), then the max_scenes_per_tile lowest-cloud items per tile. Each item's six bands and SCL are warped
onto the region grid (bands bilinear, SCL nearest). Pixels whose SCL is in invalid_scl_classes are dropped. The
composite is the per-pixel median of the remaining observations; pixels with none are NaN.

Reflectance follows the fire work exactly (lc.imagery.band_scaling): DN x scale + offset, with the offset skipped when
Earth Search says it is already applied.
"""
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Mapping

import numpy as np
import requests

from .geometry import Grid
from .imagery import ImageryError, band_scaling

os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
os.environ.setdefault("GDAL_HTTP_MAX_RETRY", "4")
os.environ.setdefault("GDAL_HTTP_RETRY_DELAY", "3")
os.environ.setdefault("AWS_NO_SIGN_REQUEST", "YES")


def search(cfg: Mapping[str, Any], bbox_wgs84: list[float], year: int, window: tuple[str, str] | None = None,
           max_cloud: float | None = None) -> list[dict]:
    img = cfg["imagery"]
    start, end = window or img["window"]
    body = {"collections": [img["collection"]], "bbox": bbox_wgs84, "limit": 200,
            "datetime": f"{year}-{start}T00:00:00Z/{year}-{end}T23:59:59Z",
            "query": {"eo:cloud_cover": {"lt": img["max_cloud"] if max_cloud is None else max_cloud}}}
    url, items = f"{img['stac_url']}/search", []
    while url:
        r = requests.post(url, json=body, timeout=120)
        r.raise_for_status()
        page = r.json()
        items += page.get("features", [])
        nxt = [link for link in page.get("links", []) if link.get("rel") == "next"]
        url, body = (nxt[0]["href"], nxt[0].get("body", body)) if nxt else (None, None)
    return items


def choose(items: list[dict], per_tile: int) -> list[dict]:
    """One item per (tile, date), latest processing first; then the per_tile lowest-cloud items of each tile."""
    by_key: dict[tuple, dict] = {}
    for it in items:
        p = it["properties"]
        key = (p.get("s2:mgrs_tile") or it["id"].split("_")[1], p["datetime"][:10])
        prev = by_key.get(key)
        if prev is None or str(p.get("s2:processing_baseline", "")) > str(prev["properties"].get("s2:processing_baseline", "")):
            by_key[key] = it
    tiles: dict[str, list] = {}
    for (tile, _), it in by_key.items():
        tiles.setdefault(tile, []).append(it)
    out = []
    for tile in sorted(tiles):
        ranked = sorted(tiles[tile], key=lambda it: (float(it["properties"]["eo:cloud_cover"]), it["properties"]["datetime"], it["id"]))
        out += ranked[:per_tile]
    return out


def _warp(href: str, grid: Grid, resampling, dtype) -> np.ndarray:
    import rasterio
    from rasterio.warp import reproject

    out = np.zeros((grid.height, grid.width), dtype=dtype)
    with rasterio.open(href) as src:
        reproject(source=rasterio.band(src, 1), destination=out, dst_transform=grid.transform, dst_crs=grid.crs,
                  resampling=resampling, src_nodata=src.nodata if src.nodata is not None else 0, dst_nodata=0)
    return out


def read_item(item: dict, cfg: Mapping[str, Any], grid: Grid, max_aot: float | None = None) -> tuple[np.ndarray, np.ndarray]:
    """(reflectance x 10000 as uint16 with 0 = invalid, shape (6, H, W); valid mask (H, W)).

    max_aot: when given, pixels whose aerosol optical thickness exceeds it are invalid (smoke and thick haze pass the
    scene classification as clear). A missing or unscaled AOT asset fails the item rather than skipping the filter.
    """
    from rasterio.enums import Resampling

    img = cfg["imagery"]
    scaling = [band_scaling(item, b["asset"]) for b in img["model_bands"]]  # fails closed before any read
    scl = _warp(item["assets"][img["scl_asset"]]["href"], grid, Resampling.nearest, np.uint8)
    valid = (scl > 0) & ~np.isin(scl, img["invalid_scl_classes"])
    if max_aot is not None:
        a = item["assets"].get(img["aot_asset"])
        bands = (a or {}).get("raster:bands") or [{}]
        scale = bands[0].get("scale")
        if not a or not isinstance(scale, (int, float)) or scale <= 0:
            raise ImageryError(f"{item.get('id')}: no usable AOT asset; refusing to composite without the aerosol filter")
        aot = _warp(a["href"], grid, Resampling.nearest, np.float32) * np.float32(scale)
        valid &= (aot > 0) & (aot <= max_aot)
    stack = np.zeros((len(scaling), grid.height, grid.width), dtype=np.uint16)
    for k, (b, (scale, offset, nodata)) in enumerate(zip(img["model_bands"], scaling)):
        dn = _warp(item["assets"][b["asset"]]["href"], grid, Resampling.bilinear, np.float32)
        refl = dn * np.float32(scale) + np.float32(offset)
        ok = valid & (dn > 0)
        if nodata is not None:
            ok &= dn != nodata
        # reflectance below 0 can occur after the offset; clip to 1 (0 is reserved for "invalid")
        stack[k] = np.where(ok, np.clip(np.rint(refl * 10000), 1, 65535), 0).astype(np.uint16)
        valid &= ok
    stack[:, ~valid] = 0
    return stack, valid


def median_composite(items: list[dict], cfg: Mapping[str, Any], grid: Grid, workers: int = 6,
                     log=print, max_aot: float | None = None) -> tuple[np.ndarray, np.ndarray, list[dict]]:
    """(composite float32 (6, H, W) reflectance with NaN where no observation, count uint16 (H, W), per-item log)."""
    stacks, records = [], []

    def work(it):
        try:
            s, v = read_item(it, cfg, grid, max_aot)
            return it, s, v, None
        except (ImageryError, Exception) as exc:  # one bad item must not stop the year; it is logged and skipped
            return it, None, None, f"{type(exc).__name__}: {exc}"

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for n, (it, s, v, err) in enumerate(pool.map(work, items), 1):
            rec = {"id": it["id"], "cloud": it["properties"]["eo:cloud_cover"],
                   "boa_offset_applied": it["properties"].get("earthsearch:boa_offset_applied")}
            if err:
                rec["error"] = err
            else:
                rec["valid_px"] = int(v.sum())
                if rec["valid_px"]:
                    # keep only the item's own footprint, so 16 GB of RAM holds a year's scenes
                    rows, cols = np.flatnonzero(v.any(axis=1)), np.flatnonzero(v.any(axis=0))
                    r0, r1, c0, c1 = rows[0], rows[-1] + 1, cols[0], cols[-1] + 1
                    stacks.append((r0, r1, c0, c1, s[:, r0:r1, c0:c1].copy()))
                del s, v
            records.append(rec)
            log(f"  [{n}/{len(items)}] {it['id']} {'ERROR ' + err if err else rec['valid_px']}")
    nb = len(cfg["imagery"]["model_bands"])
    comp = np.full((nb, grid.height, grid.width), np.nan, dtype=np.float32)
    count = np.zeros((grid.height, grid.width), dtype=np.uint16)
    if not stacks:
        return comp, count, records
    rows = 128
    for r0 in range(0, grid.height, rows):
        r1 = min(r0 + rows, grid.height)
        hits = [st for st in stacks if st[0] < r1 and st[1] > r0]
        if not hits:
            continue
        block = np.full((len(hits), nb, r1 - r0, grid.width), np.nan, dtype=np.float32)  # (N, 6, rows, W)
        for k, (a0, a1, c0, c1, s) in enumerate(hits):
            lo, hi = max(r0, a0), min(r1, a1)
            part = s[:, lo - a0:hi - a0].astype(np.float32)
            part[part == 0] = np.nan
            block[k, :, lo - r0:hi - r0, c0:c1] = part
        count[r0:r0 + rows] = np.isfinite(block[:, 0]).sum(axis=0)
        with np.errstate(all="ignore"):
            import warnings
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                comp[:, r0:r0 + rows] = np.nanmedian(block, axis=0) / 10000.0
    return comp, count, records
