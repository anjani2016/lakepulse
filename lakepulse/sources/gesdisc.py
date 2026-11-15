"""NASA monthly and daily series via OPeNDAP subset requests: MERRA-2, GPM IMERG and OMI
OMNO2d from GES DISC (Earthdata cloud OPeNDAP), and MODIS MOD08_M3 from LAADS DAAC (LAADS
OPeNDAP, which answers the same DAP4 request; needs the LAADS application approved in the
Earthdata profile, done by the owner 2026-11-14).

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


OPENDAP_CLOUD = "opendap.earthdata.nasa.gov"
OPENDAP_LAADS = "ladsweb.modaps.eosdis.nasa.gov/opendap"


def granules(short_name: str, version: str, start: str, end: str,
             opendap_host: str = OPENDAP_CLOUD) -> list[tuple[pd.Timestamp, str]]:
    """(start day, OPeNDAP URL) for every granule in the range, from CMR. LAADS lists its
    OPeNDAP link with a trailing '.html' page suffix, which is removed."""
    out, page = [], 1
    while True:
        r = requests.get(CMR, params={"short_name": short_name, "version": version,
                                      "temporal": f"{start}T00:00:00Z,{end}T23:59:59Z",
                                      "page_size": 2000, "page_num": page, "sort_key": "start_date"}, timeout=TIMEOUT)
        r.raise_for_status()
        entries = r.json()["feed"]["entry"]
        for e in entries:
            link = next((l["href"] for l in e.get("links", []) if opendap_host in l["href"]), None)
            if link:
                link = link[:-5] if link.endswith(".html") else link
                t = pd.Timestamp(e["time_start"])
                day = pd.Timestamp(t.year, t.month, t.day)
                # CMR also returns a granule whose period ends exactly at `start`; keep only
                # granules that begin inside the requested range.
                if pd.Timestamp(start) <= day <= pd.Timestamp(end):
                    out.append((day, link))
        if len(entries) < 2000:
            return out
        page += 1


def _month(day: pd.Timestamp) -> pd.Timestamp:
    return pd.Timestamp(day.year, day.month, 1)


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
            day, url = item
            ds = _fetch(s, url, ce)
            return _month(day), {v: float(ds[v].values.squeeze()) for v in var_map}

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
        day, url = item
        month = _month(day)
        ds = _fetch(s, url, ce, group="Grid")
        box = ds["precipitation"].squeeze()
        w = np.cos(np.deg2rad(ds["lat"]))
        rate = float(box.weighted(w).mean(dim=["lat", "lon"]))  # mm/hr
        return month, rate * calendar.monthrange(month.year, month.month)[1] * 24

    with ThreadPoolExecutor(WORKERS) as ex:
        ser = pd.Series(dict(ex.map(one, gl))).sort_index()
    return schema.rows(lake_id, "precipitation", ser.index, ser.values.round(2))


# ---------------------------------------------------------------- air quality
# M2TMNXAER 5.12.4: TOTEXTTAU, total aerosol extinction AOT at 550 nm (unitless), confirmed in
# CMR 2026-11-14. Averaged over the MERRA-2 cells whose centres fall in the catchment box,
# weighted by cos(latitude), like IMERG.
def merra2_aer_rows(lake_id: str, bbox: dict, start: str, end: str, log=print) -> pd.DataFrame:
    i0 = int(np.ceil((bbox["south"] + 90) / 0.5))
    i1 = int(np.floor((bbox["north"] + 90) / 0.5))
    j0 = int(np.ceil((bbox["west"] + 180) / 0.625))
    j1 = int(np.floor((bbox["east"] + 180) / 0.625))
    if i1 < i0 or j1 < j0:
        raise ValueError("catchment box contains no MERRA-2 cell centre")
    ce = f"/lat[{i0}:{i1}];/lon[{j0}:{j1}];/TOTEXTTAU[0][{i0}:{i1}][{j0}:{j1}]"
    s = requests.Session()
    s.headers["Authorization"] = f"Bearer {_token()}"
    gl = granules("M2TMNXAER", "5.12.4", start, end)
    log(f"M2TMNXAER: {len(gl)} monthly files for {start} to {end}; box {i1 - i0 + 1} x {j1 - j0 + 1} cells "
        f"(lat {-90 + 0.5 * i0}..{-90 + 0.5 * i1}, lon {-180 + 0.625 * j0}..{-180 + 0.625 * j1})")

    def one(item):
        day, url = item
        ds = _fetch(s, url, ce)
        box = ds["TOTEXTTAU"].squeeze("time", drop=True) if "time" in ds["TOTEXTTAU"].dims else ds["TOTEXTTAU"]
        w = np.cos(np.deg2rad(ds["lat"]))
        return _month(day), float(box.weighted(w).mean(dim=["lat", "lon"]))

    with ThreadPoolExecutor(WORKERS) as ex:
        ser = pd.Series(dict(ex.map(one, gl))).sort_index()
    return schema.rows(lake_id, "aod_model", ser.index, ser.values.round(4))


# OMNO2d 004 (v5.0): ColumnAmountNO2TropCloudScreened (molec/cm2) and Weight on a 0.25° grid,
# first cell edges at 180°W and 90°S (OMNO2 README v5.0, p. 32). The product itself applies
# the screening of Table 4 (p. 32): solar zenith < 85°, effective cloud fraction < 30% for the
# cloud-screened field, cross-track quality flags 0 or 255, ascending orbit, no summary flags.
# Fill value -1.26765e30. Cells in a region are combined with the Weight field (p. 33, eq. 5).
OMNO2D_GROUP = "HDFEOS/GRIDS/ColumnAmountNO2/Data_Fields"
OMNO2D_FILL_BELOW = -1e29
# Project policy, not NASA requirements (the OMNO2 README sets neither threshold):
MIN_VALID_DAYS = 10        # a month with fewer valid days is marked missing
MIN_CELL_FRACTION = 0.5    # a day is valid when at least half the box's cells have data


def omno2d_box_value(no2: np.ndarray, weight: np.ndarray, min_cell_fraction: float = MIN_CELL_FRACTION) -> float:
    """Weighted mean (README eq. 5) of one day's box, or NaN when too few cells have data."""
    no2 = np.asarray(no2, dtype=float)
    weight = np.asarray(weight, dtype=float)
    ok = np.isfinite(no2) & (no2 > OMNO2D_FILL_BELOW) & np.isfinite(weight) & (weight > 0)
    if ok.size == 0 or ok.mean() < min_cell_fraction:
        return float("nan")
    return float(np.sum(no2[ok] * weight[ok]) / np.sum(weight[ok]))


def monthly_from_daily(daily: pd.Series, min_days: int = MIN_VALID_DAYS) -> pd.DataFrame:
    """Average valid daily values into months.

    Returns one row per calendar month in the span of `daily`: month (first day), value
    (mean of valid days, NaN when fewer than `min_days`), n_valid_days. Missing or NaN days
    are not filled. Months with no valid day at all still appear, with n_valid_days = 0.
    """
    d = pd.Series(daily, dtype=float).dropna()
    d.index = pd.to_datetime(d.index)
    idx = pd.to_datetime(pd.Series(daily).index)
    if len(idx) == 0:
        return pd.DataFrame(columns=["month", "value", "n_valid_days"])
    months = pd.period_range(idx.min().to_period("M"), idx.max().to_period("M"), freq="M")
    g = d.groupby(d.index.to_period("M"))
    mean, count = g.mean(), g.size()
    out = pd.DataFrame({"month": months.to_timestamp()})
    out["n_valid_days"] = [int(count.get(m, 0)) for m in months]
    out["value"] = [float(mean[m]) if count.get(m, 0) >= min_days else float("nan") for m in months]
    return out[["month", "value", "n_valid_days"]]


def omno2d_rows(lake_id: str, bbox: dict, start: str, end: str, log=print,
                min_days: int = MIN_VALID_DAYS) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Monthly NO2 rows (10^15 molecules/cm²) and the per-month valid-day counts."""
    i0 = int(np.ceil((bbox["south"] + 89.875) / 0.25))
    i1 = int(np.floor((bbox["north"] + 89.875) / 0.25))
    j0 = int(np.ceil((bbox["west"] + 179.875) / 0.25))
    j1 = int(np.floor((bbox["east"] + 179.875) / 0.25))
    base = "/HDFEOS/GRIDS/ColumnAmountNO2/Data_Fields/"
    ce = f"{base}ColumnAmountNO2TropCloudScreened[{i0}:{i1}][{j0}:{j1}];{base}Weight[{i0}:{i1}][{j0}:{j1}]"
    s = requests.Session()
    s.headers["Authorization"] = f"Bearer {_token()}"
    gl = granules("OMNO2d", "004", start, end)
    log(f"OMNO2d 004: {len(gl)} daily files for {start} to {end}; box {i1 - i0 + 1} x {j1 - j0 + 1} cells "
        f"(lat {-89.875 + 0.25 * i0}..{-89.875 + 0.25 * i1}, lon {-179.875 + 0.25 * j0}..{-179.875 + 0.25 * j1})")

    def one(item):
        day, url = item
        ds = _fetch(s, url, ce, group=OMNO2D_GROUP)
        return day, omno2d_box_value(ds["ColumnAmountNO2TropCloudScreened"].values, ds["Weight"].values)

    with ThreadPoolExecutor(WORKERS) as ex:
        daily = pd.Series(dict(ex.map(one, gl))).sort_index()
    m = monthly_from_daily(daily, min_days)
    m["value"] = m["value"] / 1e15
    kept = m.dropna(subset=["value"])
    rows = schema.rows(lake_id, "no2_trop_column", kept["month"], kept["value"].round(4))
    log(f"OMNO2d: {int(daily.notna().sum())} valid days of {len(daily)}; {len(kept)} of {len(m)} months kept "
        f"(threshold {min_days} valid days)")
    return rows, m.assign(lake=lake_id)


# MOD08_M3 6.1 (LAADS): AOD_550_Dark_Target_Deep_Blue_Combined_Mean_Mean, 1° grid, YDim from
# 89.5°N southward, XDim from 179.5°W eastward (read from the file 2026-11-14). Stored as
# Int16 with scale_factor 0.001, _FillValue -9999, valid_range 0..5000. The product applies
# its own screening: L2 QA flags are used to aggregate and QA-weight L3 statistics (MODIS
# Atmosphere L3 ATBD C6/C6.1, 2019-02-20, p. 24, section 3.1); file attributes give
# Statistic_Type "Simple_MND", Weighting "MinNumDays", QA set "Quality_Assurance_Land".
# We drop fill and values outside the valid range, nothing else.
MOD08_VAR = "AOD_550_Dark_Target_Deep_Blue_Combined_Mean_Mean"


def mod08_box_indices(bbox: dict) -> tuple[int, int, int, int]:
    i0 = int(np.ceil(89.5 - bbox["north"]))
    i1 = int(np.floor(89.5 - bbox["south"]))
    j0 = int(np.ceil(bbox["west"] + 179.5))
    j1 = int(np.floor(bbox["east"] + 179.5))
    if i1 < i0 or j1 < j0:
        raise ValueError("catchment box contains no MOD08_M3 1° cell centre")
    return i0, i1, j0, j1


def mod08_rows(lake_id: str, bbox: dict, start: str, end: str, log=print) -> pd.DataFrame:
    i0, i1, j0, j1 = mod08_box_indices(bbox)
    ce = f"/YDim[{i0}:{i1}];/XDim[{j0}:{j1}];/{MOD08_VAR}[{i0}:{i1}][{j0}:{j1}]"
    s = requests.Session()
    s.headers["Authorization"] = f"Bearer {_token()}"
    gl = granules("MOD08_M3", "6.1", start, end, opendap_host=OPENDAP_LAADS)
    log(f"MOD08_M3 6.1: {len(gl)} monthly files for {start} to {end}; box {i1 - i0 + 1} x {j1 - j0 + 1} cells "
        f"(lat {89.5 - i1}..{89.5 - i0}, lon {-179.5 + j0}..{-179.5 + j1})")

    def one(item):
        day, url = item
        ds = _fetch(s, url, ce)
        v = ds[MOD08_VAR].where((ds[MOD08_VAR] >= 0) & (ds[MOD08_VAR] <= 5.0))
        w = np.cos(np.deg2rad(ds["YDim"]))
        val = v.weighted(w).mean(dim=["YDim", "XDim"]) if int(v.notnull().sum()) else np.nan
        return _month(day), float(val)

    with ThreadPoolExecutor(WORKERS) as ex:
        ser = pd.Series(dict(ex.map(one, gl))).sort_index()
    kept = ser.dropna()
    log(f"MOD08_M3: {len(kept)} of {len(ser)} months with a valid value")
    return schema.rows(lake_id, "aod_satellite", kept.index, kept.values.round(4))
