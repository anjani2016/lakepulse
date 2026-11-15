"""Download OHN Watercourse lines inside the Lake Simcoe catchment box (Land Information Ontario open-data MapServer).

Open Government Licence - Ontario. Writes landcover/data/hydro/ohn_watercourse_simcoe.geojson (WGS84) and a small
fetch record next to it. Only features intersecting the catchment's bounding box are requested.

Run:  landcover/.venv/bin/python landcover/scripts/fetch_hydro.py
"""
from __future__ import annotations

import json
import sys
import time
from datetime import date
from pathlib import Path

import requests
from pyproj import Transformer
from shapely.ops import unary_union

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lc import config, geometry  # noqa: E402

PAGE = 100


def _get(url: str, params: dict, tries: int = 6) -> dict:
    """GET JSON; the service returns occasional 504s, 500s and error bodies, so retry with a growing pause."""
    last = None
    for attempt in range(tries):
        try:
            r = requests.get(url, params=params, timeout=120)
            r.raise_for_status()
            body = r.json()
            if "error" not in body:
                return body
            last = body["error"]
        except (requests.RequestException, ValueError) as exc:
            last = str(exc)
        time.sleep(5 * (attempt + 1))
    raise SystemExit(f"request failed after {tries} tries: {last}")


def main() -> None:
    cfg = config.load()
    units = geometry.load_units(cfg)
    catch = unary_union([units[n] for n in cfg["region"]["catchment_units"]])
    to_wgs = Transformer.from_crs(cfg["region"]["crs"], "EPSG:4326", always_xy=True)
    w, s = to_wgs.transform(*catch.bounds[:2])
    e, n = to_wgs.transform(*catch.bounds[2:])
    # the box corners in UTM don't map to the WGS84 box corners exactly; pad 0.02 degrees
    env = f"{min(w, e) - 0.02},{min(s, n) - 0.02},{max(w, e) + 0.02},{max(s, n) + 0.02}"
    url = f"{cfg['hydro']['service']}/{cfg['hydro']['layers']['watercourse']}/query"
    # Offset paging returned short pages without an exceeded flag (843 of 36,697 on 2026-11-14), so page by object ID.
    where = {"geometry": env, "geometryType": "esriGeometryEnvelope", "inSR": 4326, "spatialRel": "esriSpatialRelIntersects"}
    ids = sorted(_get(url, {"where": "1=1", **where, "returnIdsOnly": "true", "f": "json"}).get("objectIds") or [])
    count = _get(url, {"where": "1=1", **where, "returnCountOnly": "true", "f": "json"}).get("count")
    if not ids or len(ids) != count:
        raise SystemExit(f"ID list ({len(ids)}) and count ({count}) differ")
    feats = []
    for i in range(0, len(ids), PAGE):
        batch = ids[i:i + PAGE]
        page = _get(url, {"objectIds": ",".join(map(str, batch)), "outFields": "OGF_ID,WATERCOURSE_TYPE,PERMANENCY",
                          "outSR": 4326, "f": "geojson"})
        got = page.get("features", [])
        if len(got) != len(batch):
            raise SystemExit(f"batch at {i}: asked {len(batch)}, got {len(got)}")
        feats += got
    if len(feats) != count:
        raise SystemExit(f"fetched {len(feats)} of {count}")
    out = config.DATA / "hydro"
    out.mkdir(parents=True, exist_ok=True)
    (out / "ohn_watercourse_simcoe.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": feats}))
    rec = {"source": url, "envelope_wgs84": env, "features": len(feats), "retrieved_on": date.today().isoformat(),
           "licence": cfg["hydro"]["licence"], "attribution": cfg["hydro"]["attribution"]}
    (out / "fetch_record.json").write_text(json.dumps(rec, indent=1))
    print(json.dumps(rec, indent=1))


if __name__ == "__main__":
    main()
