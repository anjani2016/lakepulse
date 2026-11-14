"""Build the study geometry and check how many clean 1 km MODIS water pixels each lake has.

Outputs (in data/geo/):
  study_regions.json  - per lake: sample point, lake polygon file, catchment bounding box,
                        and the water-pixel check result.

Water-pixel check, in plain terms:
  MODIS land surface temperature cells are about 0.93 km squares on the MODIS sinusoidal
  grid. A cell is "clean water" when the whole square sits inside the lake outline after
  the outline is pulled in by a shore margin (default 500 m), so the cell's view does not
  include the shoreline. We count those cells. A lake with only a handful of them gives a
  noisy, shore-contaminated lake temperature.

Run:  python scripts/prepare_geometry.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from pyproj import CRS, Transformer
from shapely import make_valid
from shapely.geometry import box, shape
from shapely.ops import transform, unary_union

ROOT = Path(__file__).resolve().parents[1]
GEO = ROOT / "data" / "geo"

# MODIS sinusoidal grid (from the MODIS land tile grid definition).
SIN = CRS.from_proj4("+proj=sinu +lon_0=0 +x_0=0 +y_0=0 +R=6371007.181 +units=m +no_defs")
CELL_1KM = 926.625433055833  # metres, 1 km product cell size
GRID_ORIGIN_X = -20015109.354
GRID_ORIGIN_Y = 10007554.677

LAKES = {
    "simcoe_on": {
        "name": "Lake Simcoe",
        "sample_point": [44.42139, -79.42556],
        "lake_area_km2_owner": 722,
        "catchment_area_km2_model": 2990,
        "catchment_area_note": "Model catchment from the lake twin's catchment areas file "
        "(docs/verification/02_catchment_areas.md). That file records it as a stored lake "
        "record with no registry source.",
        "catchment_units": [
            "Talbot River - Trent-Severn Waterway",
            "Lake Simcoe",
            "Holland River",
            "Black River",
            "Pefferlaw River",
            "Beaver River",
        ],
    },
    "big_rideau_on": {
        "name": "Big Rideau Lake",
        "sample_point": [44.7725, -76.2128],
        "lake_area_km2_owner": None,
        "catchment_area_km2_model": 480,
        "catchment_area_note": "Model catchment from the lake twin's catchment areas file; "
        "stored lake record with no registry source.",
        "catchment_units": ["Lower Rideau Lake - Rideau River"],
    },
}


def load_geom(path: Path):
    d = json.loads(path.read_text())
    feats = d["features"] if "features" in d else [d]
    return feats


def clean_water_cells(lake_geom_wgs84, shore_margin_m: float):
    to_sin = Transformer.from_crs("EPSG:4326", SIN, always_xy=True).transform
    lake = transform(to_sin, lake_geom_wgs84)
    inner = lake.buffer(-shore_margin_m) if shore_margin_m > 0 else lake
    if inner.is_empty:
        return 0, [], []
    minx, miny, maxx, maxy = lake.bounds
    c0 = int(np.floor((minx - GRID_ORIGIN_X) / CELL_1KM))
    c1 = int(np.ceil((maxx - GRID_ORIGIN_X) / CELL_1KM))
    r0 = int(np.floor((GRID_ORIGIN_Y - maxy) / CELL_1KM))
    r1 = int(np.ceil((GRID_ORIGIN_Y - miny) / CELL_1KM))
    centres = []
    for r in range(r0, r1 + 1):
        for c in range(c0, c1 + 1):
            x0 = GRID_ORIGIN_X + c * CELL_1KM
            y1 = GRID_ORIGIN_Y - r * CELL_1KM
            cell = box(x0, y1 - CELL_1KM, x0 + CELL_1KM, y1)
            if inner.contains(cell):
                centres.append((x0 + CELL_1KM / 2, y1 - CELL_1KM / 2))
    back = Transformer.from_crs(SIN, "EPSG:4326", always_xy=True)
    pts = [back.transform(x, y) for x, y in centres]
    return len(pts), [[round(lat, 5), round(lon, 5)] for lon, lat in pts], [[round(x, 3), round(y, 3)] for x, y in centres]


def main(shore_margin_m: float = 500.0) -> None:
    out = {}
    for lake_id, meta in LAKES.items():
        lake_feats = load_geom(GEO / f"{lake_id}.geojson")
        lake_geom = unary_union([make_valid(shape(f["geometry"])) for f in lake_feats])
        props = lake_feats[0].get("properties", {})
        units = load_geom(GEO / f"{lake_id}_owb_units.geojson")
        chosen = [f for f in units if f["properties"].get("WATERSHED_NAME") in meta["catchment_units"]]
        missing = set(meta["catchment_units"]) - {f["properties"]["WATERSHED_NAME"] for f in chosen}
        if missing:
            sys.exit(f"{lake_id}: catchment units not found: {sorted(missing)}")
        units_crs = json.loads((GEO / f"{lake_id}_owb_units.geojson").read_text()).get("crs", {}).get("properties", {}).get("name", "EPSG:4326")
        catch = unary_union([make_valid(shape(f["geometry"])) for f in chosen])
        catch = transform(Transformer.from_crs(units_crs, "EPSG:4326", always_xy=True).transform, catch)
        minx, miny, maxx, maxy = catch.bounds
        eq = Transformer.from_crs("EPSG:4326", "EPSG:6933", always_xy=True).transform  # equal-area
        catch_area_km2 = transform(eq, catch).area / 1e6
        bbox_area_km2 = transform(eq, box(minx, miny, maxx, maxy)).area / 1e6
        n_clean, cells, cells_sinu = clean_water_cells(lake_geom, shore_margin_m)
        n_any, _, _ = clean_water_cells(lake_geom, 0.0)
        # Width: largest inscribed-circle diameter, a plain measure of "how wide".
        to_m = Transformer.from_crs("EPSG:4326", "EPSG:32617" if meta["sample_point"][1] < -78 else "EPSG:32618", always_xy=True).transform
        lake_m = transform(to_m, lake_geom)
        from shapely import maximum_inscribed_circle  # shapely >= 2.1

        mic = maximum_inscribed_circle(lake_m, tolerance=10)
        max_width_km = 2 * mic.length / 1000.0
        out[lake_id] = {
            "name": meta["name"],
            "sample_point": meta["sample_point"],
            "lake_outline_file": f"data/geo/{lake_id}.geojson",
            "lake_outline_source": props.get("source"),
            "lake_outline_attribution": props.get("attribution"),
            "ohn_area_km2": props.get("ohn_area_km2"),
            "catchment_area_km2_model": meta["catchment_area_km2_model"],
            "catchment_area_note": meta["catchment_area_note"],
            "catchment_units": meta["catchment_units"],
            "catchment_unit_area_km2": round(catch_area_km2, 1),
            "catchment_bbox_area_km2": round(bbox_area_km2, 1),
            "catchment_bbox": {"west": round(minx, 4), "south": round(miny, 4), "east": round(maxx, 4), "north": round(maxy, 4)},
            "water_pixel_check": {
                "cell_size_m": round(CELL_1KM, 3),
                "shore_margin_m": shore_margin_m,
                "cells_fully_inside_outline": n_any,
                "clean_cells_after_margin": n_clean,
                "widest_open_water_km": round(max_width_km, 2),
                "clean_cell_centres_lat_lon": cells,
                "clean_cell_centres_modis_sinusoidal_xy_m": cells_sinu,
            },
        }
        print(
            f"{lake_id}: outline {props.get('ohn_area_km2')} km2 | cells fully inside outline: {n_any} | "
            f"clean cells with {shore_margin_m:.0f} m shore margin: {n_clean} | widest open water: {max_width_km:.2f} km | "
            f"catchment units {catch_area_km2:.1f} km2 | bbox W{minx:.3f} S{miny:.3f} E{maxx:.3f} N{maxy:.3f} = {bbox_area_km2:.1f} km2"
        )
    (GEO / "study_regions.json").write_text(json.dumps(out, indent=2) + "\n")
    print(f"wrote {GEO / 'study_regions.json'}")


if __name__ == "__main__":
    main(float(sys.argv[1]) if len(sys.argv) > 1 else 500.0)
