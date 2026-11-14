"""Turn AppEEARS netCDF bundles into monthly / yearly table rows.

Lake surface temperature (MOD11A2.061, 8-day composites, 1 km):
- Keep only clean water cells: cells that sit wholly inside the lake outline after a 500 m
  shore margin (list made by scripts/prepare_geometry.py).
- Keep only pixels whose QC says the LST was produced (mandatory QA bits 0-1 = 00 or 01)
  AND whose LST error flag (bits 6-7) is 00, "average LST error <= 1K"
  (MOD11 User Guide V6.1, p. 21).
- An 8-day composite counts only if at least MIN_VALID_FRACTION of the clean cells pass.
- Monthly value = mean of the composite means whose start date falls in that month.

Catchment (bounding box):
- NDVI (MOD13A3.061, monthly 1 km): pixels with reliability 0 (good) or 1 (marginal),
  excluding cells the same-year (or nearest-year) MCD12Q1 map calls water (class 17).
- Land-cover shares (MCD12Q1.061 LC_Type1, yearly 500 m): forest = classes 1-5,
  cropland = 12, urban = 13, as a percentage of non-water, labelled pixels.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

from .. import schema
from .. import variables as V

MIN_VALID_FRACTION = 0.10


def _open(path: Path) -> xr.Dataset:
    return xr.open_dataset(path, mask_and_scale=True, decode_times=True)


def _find(files, product: str) -> Path:
    hits = [f for f in files if Path(f).name.startswith(product) and str(f).endswith(".nc")]
    if not hits:
        raise FileNotFoundError(f"no {product} netCDF among {len(files)} files")
    return Path(hits[0])


def _qc_ok(qc: xr.DataArray) -> xr.DataArray:
    q = qc.fillna(255).astype("uint8")
    mandatory = q & 0b11
    lst_error = (q >> 6) & 0b11
    return (mandatory <= 1) & (lst_error == 0)


def _cell_mask(ds: xr.Dataset, centres_xy: list[list[float]], tol_m: float = 5.0) -> xr.DataArray:
    # AppEEARS native-projection netCDF names its grid axes xdim/ydim [verify: on first bundle];
    # fall back to x/y.
    xname = "xdim" if "xdim" in ds.dims else "x"
    yname = "ydim" if "ydim" in ds.dims else "y"
    xs, ys = ds[xname].values, ds[yname].values
    mask = np.zeros((len(ys), len(xs)), dtype=bool)
    for cx, cy in centres_xy:
        i = int(np.argmin(np.abs(ys - cy)))
        j = int(np.argmin(np.abs(xs - cx)))
        if abs(ys[i] - cy) <= tol_m and abs(xs[j] - cx) <= tol_m:
            mask[i, j] = True
    return xr.DataArray(mask, dims=(yname, xname))


def lake_lst_rows(nc_files, lake_id: str, clean_centres_xy: list[list[float]]) -> tuple[pd.DataFrame, dict]:
    ds = _open(_find(nc_files, "MOD11A2"))
    mask = _cell_mask(ds, clean_centres_xy)
    n_cells = int(mask.sum())
    if n_cells == 0:
        raise ValueError("none of the clean water cells matched the AppEEARS grid; check projection='native'")
    out = {}
    stats = {"clean_cells_matched": n_cells, "clean_cells_listed": len(clean_centres_xy)}
    for pass_name, lst_var, qc_var in (("day", "LST_Day_1km", "QC_Day"), ("night", "LST_Night_1km", "QC_Night")):
        lst = ds[lst_var]
        if float(lst.max(skipna=True)) > 1000:  # scale factor not applied by the file
            lst = lst * 0.02
        ok = _qc_ok(ds[qc_var]) & mask & lst.notnull()
        frac = ok.sum(dim=[d for d in ok.dims if d != "time"]) / n_cells
        comp_mean = lst.where(ok).mean(dim=[d for d in lst.dims if d != "time"]) - 273.15
        comp = comp_mean.where(frac >= MIN_VALID_FRACTION).to_series().dropna()
        stats[f"{pass_name}_composites_total"] = int(ds.sizes["time"])
        stats[f"{pass_name}_composites_kept"] = int(len(comp))
        comp.index = pd.to_datetime(comp.index)
        out[pass_name] = comp.groupby(comp.index.to_period("M")).mean()
    vt = ds["Day_view_time"]
    if float(vt.max(skipna=True)) > 30:
        vt = vt * 0.1
    vt_c = vt.where(mask & _qc_ok(ds["QC_Day"])).mean(dim=[d for d in vt.dims if d != "time"]).to_series().dropna()
    vt_c.index = pd.to_datetime(vt_c.index)
    view = vt_c.groupby(vt_c.index.to_period("M")).mean()

    both = pd.concat({"day": out["day"], "night": out["night"]}, axis=1).dropna()
    avg = both.mean(axis=1)

    def _r(var, s):
        return schema.rows(lake_id, var, s.index.to_timestamp(), s.values.round(3))

    rows = pd.concat([
        _r("lake_skin_temp_day", out["day"]),
        _r("lake_skin_temp_night", out["night"]),
        _r("lake_skin_temp", avg),
        _r("modis_day_view_time", view),
    ])
    return rows, stats


def catchment_rows(nc_files, lake_id: str) -> tuple[pd.DataFrame, dict]:
    lc_ds = _open(_find(nc_files, "MCD12Q1"))
    lc = lc_ds["LC_Type1"]
    years = pd.to_datetime(lc["time"].values).year
    shares = []
    for k, yr in enumerate(years):
        a = lc.isel(time=k).values
        a = a[np.isfinite(a)].astype(int)
        land = a[~np.isin(a, V.IGBP_WATER + V.IGBP_FILL)]
        if land.size == 0:
            continue
        shares.append({
            "date": pd.Timestamp(year=int(yr), month=1, day=1),
            "forest_share": 100 * np.isin(land, V.IGBP_FOREST).mean(),
            "cropland_share": 100 * np.isin(land, V.IGBP_CROPLAND).mean(),
            "urban_share": 100 * np.isin(land, V.IGBP_URBAN).mean(),
            "n_land": int(land.size),
        })
    sh = pd.DataFrame(shares)

    nd_ds = _open(_find(nc_files, "MOD13A3"))
    ndvi = nd_ds["_1_km_monthly_NDVI"]
    if float(ndvi.max(skipna=True)) > 2:
        ndvi = ndvi * 0.0001
    rel = nd_ds["_1_km_monthly_pixel_reliability"]
    xname = "xdim" if "xdim" in ndvi.dims else "x"
    yname = "ydim" if "ydim" in ndvi.dims else "y"
    lc_x = "xdim" if "xdim" in lc.dims else "x"
    lc_y = "ydim" if "ydim" in lc.dims else "y"
    monthly = {}
    for k, t in enumerate(pd.to_datetime(ndvi["time"].values)):
        k_lc = int(np.argmin(np.abs(years - t.year)))
        water_500 = lc.isel(time=k_lc).isin(list(V.IGBP_WATER))
        water_1km = water_500.rename({lc_x: xname, lc_y: yname}).sel(
            {xname: ndvi[xname], yname: ndvi[yname]}, method="nearest"
        )
        water_1km = water_1km.assign_coords({xname: ndvi[xname], yname: ndvi[yname]})
        good = rel.isel(time=k).isin([0, 1]) & ~water_1km & ndvi.isel(time=k).notnull()
        if int(good.sum()) == 0:
            continue
        monthly[pd.Timestamp(t.year, t.month, 1)] = float(ndvi.isel(time=k).where(good).mean())
    nd = pd.Series(monthly).sort_index()

    rows = pd.concat([
        schema.rows(lake_id, "forest_share", sh["date"], sh["forest_share"].round(2)),
        schema.rows(lake_id, "cropland_share", sh["date"], sh["cropland_share"].round(2)),
        schema.rows(lake_id, "urban_share", sh["date"], sh["urban_share"].round(2)),
        schema.rows(lake_id, "ndvi", nd.index, nd.values.round(4)),
    ])
    info = {"land_cover_years": [int(y) for y in years], "ndvi_months": int(len(nd))}
    return rows, info
