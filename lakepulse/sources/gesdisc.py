"""MERRA-2 monthly means and GPM IMERG monthly precipitation from GES DISC, via OPeNDAP.

Why not Giovanni's API: on 2026-11-14 both the Giovanni catalog and api.giovanni.earthdata.nasa.gov
returned 403 / "Missing Authentication Token" without a login, and no public specification
of its time parameters could be found. We read the same GES DISC monthly files, asking
the Earthdata cloud OPeNDAP server (Hyrax) for only the grid cells we need, one small
request per month. Streaming whole files took over 10 minutes for one month; a subset
request takes about a second (both measured 2026-11-14).

Collections (confirmed in NASA CMR on 2026-11-14):
- M2TMNXSLV 5.12.4: T2M (K), PS (Pa), QV2M (kg kg-1). 1980-01 onward.
- M2TMNXFLX 5.12.4: SPEED (m s-1). 1980-01 onward.
- M2TMNXRAD 5.12.4: SWGDN (W m-2). 1980-01 onward.
- GPM_3IMERGM 07: /Grid/precipitation (mm/hr), dims (time, lon, lat). 1998-01 to 2025-09.

MERRA-2: the single grid cell nearest the lake sample point (0.5° lat x 0.625° lon grid,
lat = -90 + 0.5 i, lon = -180 + 0.625 j). IMERG: cos(latitude)-weighted mean of the 0.1°
cells whose centres fall inside the catchment bounding box.

Authentication: an Earthdata bearer token fetched with the netrc / environment
credentials, held in memory only, never printed or written.
"""
from __future__ import annotations

import calendar
import io
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd
import requests
import xarray as xr

from .. import schema
from .earthdata_auth import credentials

CMR = "https://cmr.earthdata.nasa.gov/search/granules.json"
TOKEN_URL = "https://urs.earthdata.nasa.gov/api/users/find_or_create_token"
TIMEOUT = 120
WORKERS = 8

MERRA = {
    "M2TMNXSLV": {"T2M": ("air_temp_2m", lambda v: v - 273.15),
                  "PS": ("surface_pressure", lambda v: v / 1000.0),
                  "QV2M": ("specific_humidity", lambda v: v * 1000.0)},
    "M2TMNXFLX": {"SPEED": ("wind_speed", lambda v: v)},
    "M2TMNXRAD": {"SWGDN": ("solar_radiation", lambda v: v)},
}


def _token() -> str:
    user, pwd = credentials()
    r = requests.post(TOKEN_URL, auth=(user, pwd), timeout=TIMEOUT)
    if r.status_code != 200:
        raise RuntimeError(f"Earthdata token request failed with HTTP {r.status_code}")
    return r.json()["access_token"]


def granules(short_name: str, version: str, start: str, end: str) -> list[tuple[pd.Timestamp, str]]:
    """(month, OPeNDAP URL) for every granule in the range, from CMR."""
    out, page = [], 1
    while True:
        r = requests.get(CMR, params={"short_name": short_name, "version": version,
                                      "temporal": f"{start}T00:00:00Z,{end}T23:59:59Z",
                                      "page_size": 2000, "page_num": page, "sort_key": "start_date"}, timeout=TIMEOUT)
        r.raise_for_status()
        entries = r.json()["feed"]["entry"]
        for e in entries:
            link = next((l["href"] for l in e.get("links", []) if "opendap.earthdata.nasa.gov" in l["href"]), None)
            if link:
                t = pd.Timestamp(e["time_start"])
                out.append((pd.Timestamp(t.year, t.month, 1), link))
        if len(entries) < 2000:
            return out
        page += 1


def _fetch(session: requests.Session, url: str, ce: str, group: str | None = None) -> xr.Dataset:
    for attempt in range(3):
        try:
            r = session.get(url + ".dap.nc4", params={"dap4.ce": ce}, timeout=TIMEOUT)
            if r.status_code == 200:
                return xr.open_dataset(io.BytesIO(r.content), engine="h5netcdf", group=group).load()
            if r.status_code in (401, 403):
                raise RuntimeError(f"OPeNDAP refused access: HTTP {r.status_code}")
        except (requests.ConnectionError, requests.Timeout):
            pass
    raise RuntimeError(f"OPeNDAP request failed after retries: {url.split('/')[-1]}")


def merra2_rows(lake_id: str, lat: float, lon: float, start: str, end: str, log=print) -> pd.DataFrame:
    i = int(round((lat + 90) / 0.5))
    j = int(round((lon + 180) / 0.625))
    log(f"MERRA-2 cell: lat {-90 + 0.5 * i}, lon {-180 + 0.625 * j} (nearest to {lat}, {lon})")
    s = requests.Session()
    s.headers["Authorization"] = f"Bearer {_token()}"
    frames = []
    for short_name, var_map in MERRA.items():
        gl = granules(short_name, "5.12.4", start, end)
        log(f"{short_name}: {len(gl)} monthly files for {start} to {end}")
        ce = ";".join([f"/lat[{i}]", f"/lon[{j}]"] + [f"/{v}[0][{i}][{j}]" for v in var_map])

        def one(item):
            month, url = item
            ds = _fetch(s, url, ce)
            return month, {v: float(ds[v].values.squeeze()) for v in var_map}

        with ThreadPoolExecutor(WORKERS) as ex:
            results = dict(ex.map(one, gl))
        for v, (var_id, conv) in var_map.items():
            ser = pd.Series({m: d[v] for m, d in results.items()}).sort_index()
            frames.append(schema.rows(lake_id, var_id, ser.index, np.round(conv(ser.values), 4)))
    return pd.concat(frames)


def imerg_rows(lake_id: str, bbox: dict, start: str, end: str, log=print) -> pd.DataFrame:
    li0 = int(np.ceil((bbox["south"] + 89.95) / 0.1))
    li1 = int(np.floor((bbox["north"] + 89.95) / 0.1))
    lo0 = int(np.ceil((bbox["west"] + 179.95) / 0.1))
    lo1 = int(np.floor((bbox["east"] + 179.95) / 0.1))
    ce = f"/Grid/lat[{li0}:{li1}];/Grid/lon[{lo0}:{lo1}];/Grid/precipitation[0][{lo0}:{lo1}][{li0}:{li1}]"
    s = requests.Session()
    s.headers["Authorization"] = f"Bearer {_token()}"
    gl = granules("GPM_3IMERGM", "07", start, end)
    log(f"GPM_3IMERGM: {len(gl)} monthly files for {start} to {end}; box {li1 - li0 + 1} x {lo1 - lo0 + 1} cells")

    def one(item):
        month, url = item
        ds = _fetch(s, url, ce, group="Grid")
        box = ds["precipitation"].squeeze()
        w = np.cos(np.deg2rad(ds["lat"]))
        rate = float(box.weighted(w).mean(dim=["lat", "lon"]))  # mm/hr
        return month, rate * calendar.monthrange(month.year, month.month)[1] * 24

    with ThreadPoolExecutor(WORKERS) as ex:
        ser = pd.Series(dict(ex.map(one, gl))).sort_index()
    return schema.rows(lake_id, "precipitation", ser.index, ser.values.round(2))
