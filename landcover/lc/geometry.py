"""Region grid, catchment, shoreline-and-stream strip, and the area split.

All work is in UTM 17N metres on one region-wide 30 m grid. Chips are windows of that grid, so the label raster, the
yearly composites and the masks all line up pixel for pixel.

Split rule (by area, never by pixel):
  test  - chips whose centre lies in the test block (Holland River unit + the Lake Simcoe unit within test_reach_m of
          it, so the block holds shoreline and stream-side land). Label pixels outside the block are set to ignore.
  val   - chips whose centre lies in the val units.
  train - every other chip whose centre lies in the region (13 units), except:
  gap   - any non-test chip within gap_chips chip widths of a test chip, and any train chip within gap_chips chip widths
          of a val chip, is dropped, so no neighbouring chips sit on both sides.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping

import numpy as np
from pyproj import Transformer
from shapely.geometry import box, mapping, shape
from shapely.ops import transform, unary_union


class GeometryError(ValueError):
    pass


@dataclass(frozen=True)
class Grid:
    crs: str
    x0: float  # west edge
    y0: float  # north edge
    res: float
    width: int
    height: int

    @property
    def transform(self):
        from rasterio.transform import from_origin
        return from_origin(self.x0, self.y0, self.res, self.res)


def _fix(g):
    return g if g.is_valid else g.buffer(0)


def load_units(cfg: Mapping[str, Any], wide: bool = False) -> dict[str, Any]:
    """The 13 region units; with wide=True also the v2 training-only ring (config v2.extra_units_file)."""
    units = _load_units(cfg)
    if wide:
        from .config import LC_ROOT
        v2 = cfg["v2"]
        data = json.loads((LC_ROOT / v2["extra_units_file"]).read_text())
        to_utm = Transformer.from_crs(v2["extra_units_crs"], cfg["region"]["crs"], always_xy=True).transform
        for f in data["features"]:
            name = f["properties"][cfg["region"]["unit_name_field"]]
            if name in units:
                raise GeometryError(f"extra unit {name!r} is already a region unit")
            units[name] = _fix(transform(to_utm, shape(f["geometry"])))
        if len(units) != 13 + len(data["features"]):
            raise GeometryError("extra units file has duplicate names")
    return units


def _load_units(cfg: Mapping[str, Any]) -> dict[str, Any]:
    reg = cfg["region"]
    data = json.loads(open(reg["units_file"]).read())
    file_crs = (data.get("crs") or {}).get("properties", {}).get("name")
    if file_crs != reg["units_crs"]:
        raise GeometryError(f"units file CRS {file_crs!r} differs from config {reg['units_crs']!r}")
    to_utm = Transformer.from_crs(reg["units_crs"], reg["crs"], always_xy=True).transform
    units = {f["properties"][reg["unit_name_field"]]: _fix(transform(to_utm, shape(f["geometry"]))) for f in data["features"]}
    wanted = list(reg["catchment_units"]) + list(reg["ring_units"])
    missing = [n for n in wanted if n not in units]
    if missing:
        raise GeometryError(f"units missing from file: {missing}")  # fail closed
    for name in list(cfg["split"]["test_units"]) + list(cfg["split"]["val_units"]) + [cfg["split"]["test_shore_unit"]]:
        if name not in wanted:
            raise GeometryError(f"split unit {name!r} is not a catchment or ring unit")
    return {n: units[n] for n in wanted}


def load_lake(cfg: Mapping[str, Any]):
    reg = cfg["region"]
    d = json.loads(open(reg["lake_outline"]).read())
    to_utm = Transformer.from_crs("EPSG:4326", reg["crs"], always_xy=True).transform
    return _fix(transform(to_utm, _fix(shape(d["geometry"]))))


def blocks(cfg: Mapping[str, Any], units: Mapping[str, Any]) -> dict[str, Any]:
    reg, sp = cfg["region"], cfg["split"]
    region = unary_union(list(units.values()))
    catchment = unary_union([units[n] for n in reg["catchment_units"]])
    test_core = unary_union([units[n] for n in sp["test_units"]])
    test = unary_union([test_core, units[sp["test_shore_unit"]].intersection(test_core.buffer(sp["test_reach_m"]))])
    val = unary_union([units[n] for n in sp["val_units"]])
    if test.intersection(val).area > 1.0:  # sharing a border is fine; sharing area is not
        raise GeometryError("test and val blocks overlap")
    return {"region": region, "catchment": catchment, "test": test, "val": val}


def region_grid(cfg: Mapping[str, Any], region) -> Grid:
    res, chip = cfg["chips"]["res_m"], cfg["chips"]["chip_px"]
    step = res * chip
    minx, miny, maxx, maxy = region.bounds
    x0, x1 = np.floor(minx / step) * step, np.ceil(maxx / step) * step
    y0, y1 = np.floor(miny / step) * step, np.ceil(maxy / step) * step
    return Grid(cfg["region"]["crs"], float(x0), float(y1), float(res), int(round((x1 - x0) / res)), int(round((y1 - y0) / res)))


def chip_boxes(grid: Grid, chip_px: int) -> list[dict[str, Any]]:
    out = []
    step = grid.res * chip_px
    for r in range(grid.height // chip_px):
        for c in range(grid.width // chip_px):
            x, y = grid.x0 + c * step, grid.y0 - r * step
            out.append({"id": f"r{r:02d}c{c:02d}", "row": r * chip_px, "col": c * chip_px, "geom": box(x, y - step, x + step, y)})
    return out


def assign_split(chips: list[dict[str, Any]], blk: Mapping[str, Any], gap_m: float) -> list[dict[str, Any]]:
    """Set chip['split'] to test / val / train / None (dropped) with a reason."""
    for ch in chips:
        c = ch["geom"].centroid
        if blk["test"].contains(c):
            ch["split"], ch["why"] = "test", "centre in test block"
        elif blk["val"].contains(c):
            ch["split"], ch["why"] = "val", "centre in val block"
        elif blk["region"].contains(c):
            ch["split"], ch["why"] = "train", "centre in region"
        else:
            ch["split"], ch["why"] = None, "centre outside region"
    test_area = unary_union([ch["geom"] for ch in chips if ch["split"] == "test"])
    val_area = unary_union([ch["geom"] for ch in chips if ch["split"] == "val"])
    for ch in chips:
        if ch["split"] in ("train", "val") and not test_area.is_empty and ch["geom"].distance(test_area) < gap_m:
            ch["split"], ch["why"] = None, "gap next to test"
    for ch in chips:
        if ch["split"] == "train" and not val_area.is_empty and ch["geom"].distance(val_area) < gap_m:
            ch["split"], ch["why"] = None, "gap next to val"
    return chips


def strip(cfg: Mapping[str, Any], lake, streams: list, catchment):
    """Land and water within strip_m of the lake shoreline or of a stream line, inside the catchment."""
    w = float(cfg["region"]["strip_m"])
    if w <= 0:
        raise GeometryError("strip_m must be positive")
    parts = [lake.boundary.buffer(w)] + [s.buffer(w) for s in streams]
    return unary_union(parts).intersection(catchment)


def rasterize(geom, grid: Grid) -> np.ndarray:
    from rasterio.features import rasterize as rz
    if geom.is_empty:
        return np.zeros((grid.height, grid.width), dtype=bool)
    return rz([(mapping(geom), 1)], out_shape=(grid.height, grid.width), transform=grid.transform, fill=0, dtype="uint8").astype(bool)
