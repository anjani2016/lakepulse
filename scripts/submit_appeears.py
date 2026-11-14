"""Submit the two AppEEARS area requests (they queue on the server, so run this first).

  1. Lake Simcoe water surface: MOD11A2.061 LST day/night + QC + day view time.
  2. Simcoe catchment bounding box: MOD13A3.061 NDVI + reliability, MCD12Q1.061 LC_Type1.

Usage:
  .venv/bin/python scripts/submit_appeears.py --dry-run   # show what would be sent, no login
  .venv/bin/python scripts/submit_appeears.py             # log in and submit

Task IDs are saved to data/appeears_tasks.json (no credentials in it). Re-running skips
tasks that already have an ID unless --force is given.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lakepulse.sources import appeears  # noqa: E402
from lakepulse.sources.earthdata_auth import status as cred_status  # noqa: E402

TASKS_FILE = ROOT / "data" / "appeears_tasks.json"
START, END = "02-18-2000", "12-31-2025"  # MOD11A2.061 first date per AppEEARS catalog; last full year


def valid_polygon(geom: dict) -> dict:
    """The stored outline is simplified and self-crosses at one vertex; AppEEARS rejects
    that. Repair it and keep only the polygon parts."""
    from shapely import make_valid
    from shapely.geometry import MultiPolygon, mapping, shape

    g = make_valid(shape(geom))
    polys = [p for p in getattr(g, "geoms", [g]) if p.geom_type in ("Polygon", "MultiPolygon")]
    parts = [q for p in polys for q in getattr(p, "geoms", [p])]
    fixed = MultiPolygon(parts) if len(parts) > 1 else parts[0]
    if not fixed.is_valid:
        raise ValueError("lake outline still invalid after repair")
    return mapping(fixed)


def build() -> dict:
    regions = json.loads((ROOT / "data" / "geo" / "study_regions.json").read_text())
    simcoe = regions["simcoe_on"]
    lake_fc = json.loads((ROOT / simcoe["lake_outline_file"]).read_text())
    feats = lake_fc["features"] if "features" in lake_fc else [lake_fc]
    lake_fc = {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {"lake": "simcoe_on"}, "geometry": valid_polygon(f["geometry"])} for f in feats]}
    return {
        "simcoe_lake_lst": appeears.lake_lst_task("lakepulse_simcoe_lake_lst", lake_fc, START, END),
        "simcoe_catchment": appeears.catchment_task("lakepulse_simcoe_catchment", simcoe["catchment_bbox"], "02-01-2000", END),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    tasks = build()
    for key, t in tasks.items():
        p = t["params"]
        n_vertices = sum(len(ring) for f in p["geo"]["features"] for poly in ([f["geometry"]["coordinates"]] if f["geometry"]["type"] == "Polygon" else f["geometry"]["coordinates"]) for ring in poly)
        print(f"{key}: {t['task_name']} | dates {p['dates'][0]['startDate']} to {p['dates'][0]['endDate']} | "
              f"layers {[l['product'] + ':' + l['layer'] for l in p['layers']]} | polygon vertices {n_vertices} | output {p['output']}")
    if args.dry_run:
        print(f"dry run: nothing sent. Earthdata credentials: {cred_status()}")
        return
    saved = appeears.load_tasks(TASKS_FILE)
    with appeears.Client() as c:
        for key, t in tasks.items():
            if key in saved and not args.force:
                print(f"{key}: already submitted as {saved[key]['task_id']} (use --force to resubmit)")
                continue
            resp = c.submit(t)
            saved[key] = {"task_id": resp["task_id"], "task_name": t["task_name"], "status_at_submit": resp.get("status")}
            appeears.save_tasks(TASKS_FILE, saved)
            print(f"{key}: submitted, task_id {resp['task_id']}, status {resp.get('status')}")


if __name__ == "__main__":
    main()
