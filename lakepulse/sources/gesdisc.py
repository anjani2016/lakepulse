"""MERRA-2 monthly means and GPM IMERG monthly precipitation from GES DISC.

Why not Giovanni's API: on 2026-11-14 both the Giovanni catalog and api.giovanni.earthdata.nasa.gov
returned 403 / "Missing Authentication Token" without a login, and no public specification
of its time parameters could be found. We therefore read the same GES DISC monthly files
that Giovanni serves, through earthaccess (Earthdata Login), and recommend a Giovanni
area-averaged time series as a manual cross-check (docs/PLAN.md).

Collections (confirmed in NASA CMR on 2026-11-14):
- M2TMNXSLV 5.12.4: T2M (K), PS (Pa), QV2M (kg kg-1). 1980-01 onward.
- M2TMNXFLX 5.12.4: SPEED (m s-1). 1980-01 onward.
- M2TMNXRAD 5.12.4: SWGDN (W m-2). 1980-01 onward.
- GPM_3IMERGM 07: Grid/precipitation (mm/hr). 1998-01 to 2025-09 (CMR collection end).

MERRA-2 values are taken from the single grid cell nearest the lake sample point
(0.5° lat x 0.625° lon). IMERG is the cos(latitude)-weighted mean of 0.1° cells whose
centres fall in the catchment bounding box.
"""
from __future__ import annotations

import calendar

import numpy as np
import pandas as pd
import xarray as xr

from .. import schema

MERRA = {
    "M2TMNXSLV": {"T2M": ("air_temp_2m", lambda v: v - 273.15),
                  "PS": ("surface_pressure", lambda v: v / 1000.0),
                  "QV2M": ("specific_humidity", lambda v: v * 1000.0)},
    "M2TMNXFLX": {"SPEED": ("wind_speed", lambda v: v)},
    "M2TMNXRAD": {"SWGDN": ("solar_radiation", lambda v: v)},
}


def _login():
    import earthaccess

    from .earthdata_auth import credentials

    credentials()  # fail closed with a clear message before earthaccess tries anything
    auth = earthaccess.login(strategy="netrc") if _has_netrc() else earthaccess.login(strategy="environment")
    if not auth.authenticated:
        raise RuntimeError("Earthdata login failed")
    return earthaccess


def _has_netrc() -> bool:
    import netrc

    try:
        return netrc.netrc().authenticators("urs.earthdata.nasa.gov") is not None
    except (FileNotFoundError, netrc.NetrcParseError):
        return False


def _month_of(ds: xr.Dataset, fallback_name: str) -> pd.Timestamp:
    if "time" in ds.coords and ds["time"].size:
        t = pd.to_datetime(ds["time"].values[0])
        return pd.Timestamp(t.year, t.month, 1)
    raise ValueError(f"no time coordinate in {fallback_name}")


def merra2_rows(lake_id: str, lat: float, lon: float, start: str, end: str, log=print) -> pd.DataFrame:
    ea = _login()
    frames = []
    for short_name, var_map in MERRA.items():
        granules = ea.search_data(short_name=short_name, version="5.12.4", temporal=(start, end))
        log(f"{short_name}: {len(granules)} monthly files found for {start} to {end}")
        files = ea.open(granules)
        vals = {v: {} for v in var_map}
        for f in files:
            with xr.open_dataset(f, engine="h5netcdf") as ds:
                month = _month_of(ds, short_name)
                cell = ds.sel(lat=lat, lon=lon, method="nearest")
                for v in var_map:
                    vals[v][month] = float(cell[v].values.squeeze())
        for v, (var_id, conv) in var_map.items():
            s = pd.Series(vals[v]).sort_index()
            frames.append(schema.rows(lake_id, var_id, s.index, np.round(conv(s.values), 4)))
    return pd.concat(frames)


def imerg_rows(lake_id: str, bbox: dict, start: str, end: str, log=print) -> pd.DataFrame:
    ea = _login()
    granules = ea.search_data(short_name="GPM_3IMERGM", version="07", temporal=(start, end))
    log(f"GPM_3IMERGM: {len(granules)} monthly files found for {start} to {end}")
    files = ea.open(granules)
    vals = {}
    for f in files:
        with xr.open_dataset(f, engine="h5netcdf", group="Grid", decode_times=True) as ds:
            month = _month_of(ds, "GPM_3IMERGM")
            box = ds["precipitation"].sel(
                lat=slice(bbox["south"], bbox["north"]), lon=slice(bbox["west"], bbox["east"])
            ).squeeze()
            w = np.cos(np.deg2rad(box["lat"]))
            rate = float(box.weighted(w).mean(dim=["lat", "lon"]))  # mm/hr
            hours = calendar.monthrange(month.year, month.month)[1] * 24
            vals[month] = rate * hours
    s = pd.Series(vals).sort_index()
    return schema.rows(lake_id, "precipitation", s.index, s.values.round(2))
