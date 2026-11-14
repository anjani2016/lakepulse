"""Processing of AppEEARS MOD11A2 output, on a tiny made-up file with the same layout."""
import numpy as np
import pandas as pd
import pytest
import xarray as xr

from lakepulse.sources import appeears_process as ap

CELL = 926.625433055833


def _qc(mandatory: int, error_bits: int) -> int:
    return (error_bits << 6) | mandatory


def test_qc_keeps_only_produced_pixels_with_error_at_most_1k():
    qc = xr.DataArray(np.array([_qc(0, 0), _qc(1, 0), _qc(0, 1), _qc(2, 0), _qc(3, 0), _qc(1, 3)], dtype="uint8"))
    assert ap._qc_ok(qc).values.tolist() == [True, True, False, False, False, False]


def _write_lst(path, x, y, times, day_k, night_k, qc_day, qc_night, view):
    ds = xr.Dataset(
        {
            "LST_Day_1km": (("time", "ydim", "xdim"), day_k),
            "LST_Night_1km": (("time", "ydim", "xdim"), night_k),
            "QC_Day": (("time", "ydim", "xdim"), qc_day.astype("uint8")),
            "QC_Night": (("time", "ydim", "xdim"), qc_night.astype("uint8")),
            "Day_view_time": (("time", "ydim", "xdim"), view),
        },
        coords={"time": times, "xdim": x, "ydim": y},
    )
    ds.to_netcdf(path)


def test_lake_rows_use_clean_cells_and_good_qc_only(tmp_path):
    x = np.array([0, 1, 2]) * CELL + CELL / 2 - 6_000_000
    y = 5_000_000 - (np.array([0, 1]) * CELL + CELL / 2)
    times = pd.to_datetime(["2010-07-04", "2010-07-12", "2010-08-05"])
    shape = (3, 2, 3)
    day = np.full(shape, 293.15)  # 20 °C
    day[:, :, 2] = 400.0  # shore column: not a clean cell, must be ignored
    day[1, 0, 0] = 303.15  # 30 °C but QC says error > 1 K, must be ignored
    night = np.full(shape, 288.15)  # 15 °C
    qc_day = np.zeros(shape)
    qc_day[1, 0, 0] = _qc(0, 2)
    qc_night = np.zeros(shape)
    view = np.full(shape, 10.5)
    f = tmp_path / "MOD11A2.061_1km_aid0001.nc"
    _write_lst(f, x, y, times, day, night, qc_day, qc_night, view)

    clean = [[float(x[0]), float(y[0])], [float(x[1]), float(y[0])], [float(x[0]), float(y[1])], [float(x[1]), float(y[1])]]
    rows, info = ap.lake_lst_rows([f], "simcoe_on", clean)
    assert info["clean_cells_matched"] == 4
    v = rows.pivot_table(index="date", columns="variable", values="value")
    assert v.loc["2010-07-01", "lake_skin_temp_day"] == pytest.approx(20.0)
    assert v.loc["2010-07-01", "lake_skin_temp_night"] == pytest.approx(15.0)
    assert v.loc["2010-07-01", "lake_skin_temp"] == pytest.approx(17.5)
    assert v.loc["2010-08-01", "modis_day_view_time"] == pytest.approx(10.5)
    assert set(rows["tier"]) == {"Satellite-derived"}


def test_composite_with_too_few_valid_cells_is_dropped(tmp_path):
    x = np.arange(10) * CELL + CELL / 2
    y = 1_000_000 - (np.arange(1) * CELL + CELL / 2)
    times = pd.to_datetime(["2010-07-04", "2010-07-12"])
    day = np.full((2, 1, 10), 293.15)
    qc = np.zeros((2, 1, 10))
    qc[1, 0, :] = _qc(2, 0)  # second composite: nothing produced
    f = tmp_path / "MOD11A2.061_1km_aid0001.nc"
    _write_lst(f, x, y, times, day, day - 5, qc, np.zeros_like(qc), np.full_like(day, 10.4))
    rows, info = ap.lake_lst_rows([f], "simcoe_on", [[float(v), float(y[0])] for v in x])
    assert info["day_composites_kept"] == 1 and info["day_composites_total"] == 2


def test_no_matching_cells_fails_loudly(tmp_path):
    x = np.array([CELL / 2])
    y = np.array([-CELL / 2])
    f = tmp_path / "MOD11A2.061_1km_aid0001.nc"
    one = np.full((1, 1, 1), 290.0)
    _write_lst(f, x, y, pd.to_datetime(["2010-07-04"]), one, one, np.zeros((1, 1, 1)), np.zeros((1, 1, 1)), one * 0 + 10)
    with pytest.raises(ValueError, match="none of the clean water cells matched"):
        ap.lake_lst_rows([f], "simcoe_on", [[1e6, 1e6]])


def test_catchment_shares_and_ndvi_exclude_water(tmp_path):
    # 500 m land cover, 2 x 4: forest, forest, crop, urban / water, water, grass, forest
    lc_x = np.array([0, 1, 2, 3]) * CELL / 2 + CELL / 4
    lc_y = 1000.0 - (np.array([0, 1]) * CELL / 2 + CELL / 4)
    lc = np.array([[[1, 5, 12, 13], [17, 17, 10, 4]]], dtype="float32")
    xr.Dataset({"LC_Type1": (("time", "ydim", "xdim"), lc)},
               coords={"time": pd.to_datetime(["2010-01-01"]), "xdim": lc_x, "ydim": lc_y}).to_netcdf(tmp_path / "MCD12Q1.061_500m_aid0001.nc")
    # 1 km NDVI, 1 x 2: left cell centre falls on forest, right on crop
    nd_x = np.array([0, 1]) * CELL + CELL / 2
    nd_y = np.array([1000.0 - CELL / 4])
    ndvi = np.array([[[0.8, 0.4]], [[0.6, 0.2]]], dtype="float32")
    rel = np.array([[[0, 0]], [[0, 3]]], dtype="float32")  # 2nd month, right cell unreliable
    xr.Dataset({"_1_km_monthly_NDVI": (("time", "ydim", "xdim"), ndvi),
                "_1_km_monthly_pixel_reliability": (("time", "ydim", "xdim"), rel)},
               coords={"time": pd.to_datetime(["2010-06-01", "2010-07-01"]), "xdim": nd_x, "ydim": nd_y}).to_netcdf(tmp_path / "MOD13A3.061_1km_aid0001.nc")
    rows, info = ap.catchment_rows(sorted(tmp_path.glob("*.nc")), "simcoe_on")
    v = rows.pivot_table(index="date", columns="variable", values="value")
    # land pixels = 6 (two water excluded): forest 3, crop 1, urban 1, grass 1
    assert v.loc["2010-01-01", "forest_share"] == pytest.approx(50.0)
    assert v.loc["2010-01-01", "cropland_share"] == pytest.approx(100 / 6, abs=0.01)
    assert v.loc["2010-01-01", "urban_share"] == pytest.approx(100 / 6, abs=0.01)
    assert v.loc["2010-06-01", "ndvi"] == pytest.approx(0.6)
    assert v.loc["2010-07-01", "ndvi"] == pytest.approx(0.6)  # unreliable cell dropped
