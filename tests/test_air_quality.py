"""NO2 daily-to-monthly averaging, air-quality registry entries and the new correlation pairs."""
import numpy as np
import pandas as pd
import pytest

from lakepulse import analysis, schema
from lakepulse import variables as V
from lakepulse.sources import gesdisc


def _days(month: str, values):
    idx = pd.date_range(month, periods=len(values), freq="D")
    return pd.Series(values, index=idx, dtype=float)


# ------------------------------------------------------------ daily to monthly
def test_month_with_enough_valid_days_is_their_mean():
    m = gesdisc.monthly_from_daily(_days("2015-07-01", [2.0] * 12 + [np.nan] * 19), min_days=10)
    assert m["n_valid_days"].tolist() == [12]
    assert m["value"].tolist() == [2.0]


def test_month_with_too_few_valid_days_is_missing_but_counted():
    m = gesdisc.monthly_from_daily(_days("2015-01-01", [3.0] * 9 + [np.nan] * 22), min_days=10)
    assert m["n_valid_days"].tolist() == [9]
    assert np.isnan(m["value"].iloc[0])


def test_all_missing_month_still_appears_with_zero_days():
    daily = pd.concat([_days("2015-01-01", [np.nan] * 31), _days("2015-02-01", [1.0] * 28)])
    m = gesdisc.monthly_from_daily(daily, min_days=10)
    assert m["month"].dt.strftime("%Y-%m").tolist() == ["2015-01", "2015-02"]
    assert m["n_valid_days"].tolist() == [0, 28]
    assert np.isnan(m["value"].iloc[0]) and m["value"].iloc[1] == 1.0


def test_single_extreme_day_moves_the_mean_and_is_not_dropped():
    vals = [1.0] * 19 + [41.0]  # 20 valid days, one extreme
    m = gesdisc.monthly_from_daily(_days("2015-07-01", vals), min_days=10)
    assert m["value"].iloc[0] == pytest.approx(3.0)  # (19 * 1 + 41) / 20
    assert m["n_valid_days"].iloc[0] == 20


def test_gaps_between_months_are_not_filled():
    daily = pd.concat([_days("2015-01-01", [1.0] * 31), _days("2015-03-01", [2.0] * 31)])
    m = gesdisc.monthly_from_daily(daily, min_days=10)
    assert m["n_valid_days"].tolist() == [31, 0, 31]
    assert np.isnan(m["value"].iloc[1])


# ------------------------------------------------------------ one day's box (README eq. 5)
def test_box_value_is_weighted_and_drops_fill_cells():
    no2 = np.array([[1e15, 3e15], [-1.2676506e30, 5e15]])
    w = np.array([[1.0, 3.0], [2.0, 0.0]])  # last cell has no weight
    # valid cells: 1e15 (w1) and 3e15 (w3) -> 2 of 4 cells = 0.5, meets the 0.5 rule
    assert gesdisc.omno2d_box_value(no2, w) == pytest.approx((1e15 + 9e15) / 4)


def test_box_value_missing_when_under_half_the_cells_have_data():
    no2 = np.array([[1e15, np.nan], [np.nan, np.nan]])
    assert np.isnan(gesdisc.omno2d_box_value(no2, np.ones((2, 2))))


# ------------------------------------------------------------ registry and schema
@pytest.mark.parametrize("var_id, tier", [
    ("no2_trop_column", V.TIER_SATELLITE),
    ("aod_satellite", V.TIER_SATELLITE),
    ("aod_model", V.TIER_MODEL),
])
def test_new_registry_entries_pass_schema(var_id, tier):
    spec = V.get(var_id)
    assert spec.tier == tier and spec.scope == "catchment" and spec.frequency == "monthly" and spec.role == "air"
    assert spec.accuracy is None  # no figure found in the documentation read
    assert any("regional" in n and "not a reading at the lake" in n for n in spec.notes)
    assert any("°" in n for n in spec.notes)  # grid size stated
    df = schema.validate(schema.rows("simcoe_on", var_id, ["2015-06-01", "2015-07-01"], [0.1, 0.2]))
    assert set(df["unit"]) == {spec.unit} and set(df["tier"]) == {tier}


def test_definitions_say_what_students_need():
    no2 = V.get("no2_trop_column").definition.lower()
    assert "column of air" in no2 and "not the concentration" in no2
    for v in ("aod_satellite", "aod_model"):
        d = V.get(v).definition.lower()
        assert "no units" in d and "sunlight" in d and "haze" in d


def test_unit_mismatch_is_rejected_for_new_variable():
    bad = schema.rows("simcoe_on", "no2_trop_column", ["2015-06-01"], [1.0]).assign(unit="molec/cm2")
    with pytest.raises(schema.SchemaError, match="must use unit"):
        schema.validate(bad)


# ------------------------------------------------------------ correlation pairs
EXPECTED_PAIRS = {
    ("aod_satellite", "solar_radiation"), ("aod_model", "solar_radiation"),
    ("solar_radiation", "lake_skin_temp"), ("aod_satellite", "lake_skin_temp"),
    ("no2_trop_column", "lake_skin_temp"), ("aod_satellite", "aod_model"),
}


def _seasonal(vars_and_values: dict, years=range(2005, 2025)):
    rows = []
    for v, f in vars_and_values.items():
        for y in years:
            for m in range(5, 11):
                rows.append(schema.rows("simcoe_on", v, [pd.Timestamp(y, m, 1)], [f(y)]))
    return analysis.season_means(schema.combine(*rows))


def test_expectation_file_holds_the_six_pairs_and_is_dated():
    e = analysis.load_expectations()
    assert e["written_before_results"] is True and e["written_on"] == "2026-11-14"
    assert {(p["x"], p["y"]) for p in e["pairs"]} == EXPECTED_PAIRS


def test_all_new_pairs_appear_in_correlations_with_expectations():
    rng = np.random.default_rng(5)
    noise = {v: {y: rng.normal() for y in range(2005, 2025)} for v in ("a", "b", "c", "d", "e")}
    s = _seasonal({
        "lake_skin_temp": lambda y: 18 + 0.05 * (y - 2005) + noise["a"][y],
        "solar_radiation": lambda y: 220 + noise["b"][y],
        "aod_satellite": lambda y: 0.15 + 0.01 * noise["c"][y],
        "aod_model": lambda y: 0.14 + 0.01 * noise["d"][y],
        "no2_trop_column": lambda y: 3.0 - 0.05 * (y - 2005) + 0.1 * noise["e"][y],
    })
    c = analysis.correlations(s)
    found = {(r.x, r.y) for r in c.itertuples()}
    assert EXPECTED_PAIRS <= found
    # solar vs lake appears once, carrying the written expectation
    solar = c[(c.x == "solar_radiation") & (c.y == "lake_skin_temp")]
    assert len(solar) == 1 and solar.iloc[0]["expected_sign"] == "positive"
    ok = c[c["status"] == "ok"]
    assert ok[["r_raw", "r_detrended"]].notna().all().all()
    # air variables are not added automatically against the lake beyond the written pairs
    assert not ((c.x == "aod_model") & (c.y == "lake_skin_temp")).any()


def test_pairs_without_data_are_reported_not_dropped():
    s = _seasonal({"solar_radiation": lambda y: 200.0 + (y % 3), "aod_model": lambda y: 0.1 + 0.01 * (y % 4)})
    c = analysis.correlations(s)
    assert EXPECTED_PAIRS <= {(r.x, r.y) for r in c.itertuples()}
    lake_pairs = c[c.y == "lake_skin_temp"]
    assert (lake_pairs["status"].str.startswith("not computed")).all()


def test_mod08_box_picks_the_one_cell_centred_in_the_simcoe_box():
    import json
    from pathlib import Path
    bbox = json.loads((Path(__file__).resolve().parents[1] / "data/geo/study_regions.json").read_text())["simcoe_on"]["catchment_bbox"]
    i0, i1, j0, j1 = gesdisc.mod08_box_indices(bbox)
    assert (i0, i1, j0, j1) == (45, 45, 100, 100)
    assert (89.5 - i0, -179.5 + j0) == (44.5, -79.5)


def test_granules_keep_only_those_starting_in_range(monkeypatch):
    class R:
        status_code = 200
        def raise_for_status(self): pass
        def json(self):
            mk = lambda t: {"time_start": t, "links": [{"href": "https://ladsweb.modaps.eosdis.nasa.gov/opendap/x/" + t[:7] + ".hdf.html"}]}
            return {"feed": {"entry": [mk("2015-04-01T00:00:00Z"), mk("2015-05-01T00:00:00Z")]}}
    monkeypatch.setattr(gesdisc.requests, "get", lambda *a, **k: R())
    g = gesdisc.granules("MOD08_M3", "6.1", "2015-05-01", "2015-05-31", opendap_host=gesdisc.OPENDAP_LAADS)
    assert [d.strftime("%Y-%m") for d, _ in g] == ["2015-05"]
    assert g[0][1].endswith(".hdf")  # '.html' suffix removed
