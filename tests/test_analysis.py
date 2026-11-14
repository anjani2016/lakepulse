import numpy as np
import pandas as pd
import pytest

from lakepulse import analysis, schema
from lakepulse import variables as V


def _monthly(var, values_by_month, lake="simcoe_on", years=range(2000, 2020)):
    dates, vals = [], []
    for y in years:
        for m in range(1, 13):
            v = values_by_month(y, m)
            if v is not None:
                dates.append(pd.Timestamp(y, m, 1))
                vals.append(v)
    return schema.rows(lake, var, dates, vals)


def test_season_mean_uses_may_to_october_only():
    t = _monthly("air_temp_2m", lambda y, m: 10.0 if 5 <= m <= 10 else -50.0)
    s = analysis.season_means(t)
    assert (s["value"] == 10.0).all() and len(s) == 20


def test_season_with_a_missing_month_is_dropped():
    t = _monthly("air_temp_2m", lambda y, m: None if (y == 2005 and m == 7) else 10.0)
    s = analysis.season_means(t)
    assert 2005 not in set(s["year"]) and len(s) == 19


def test_yearly_values_pass_through():
    t = schema.rows("simcoe_on", "urban_share", [f"{y}-01-01" for y in range(2001, 2011)], np.linspace(5, 6, 10))
    s = analysis.season_means(t)
    assert s["year"].tolist() == list(range(2001, 2011))


def test_small_lake_temperature_change_is_flagged_as_within_sensor_accuracy():
    t = _monthly("lake_skin_temp", lambda y, m: 15 + 0.02 * (y - 2000))  # 0.38 °C over 19 years
    tr = analysis.trend_table(analysis.season_means(t)).iloc[0]
    assert tr["accuracy_verdict"] == "not distinguishable from sensor accuracy"
    assert "not distinguishable from sensor accuracy" in tr["verdict"]
    assert tr["accuracy_value"] == V.MOD11_ACCURACY["value"]


def test_large_change_is_larger_than_accuracy_and_significant():
    t = _monthly("lake_skin_temp", lambda y, m: 15 + 0.1 * (y - 2000))
    tr = analysis.trend_table(analysis.season_means(t)).iloc[0]
    assert tr["significant"] and tr["accuracy_verdict"] == "larger than sensor accuracy"
    assert tr["slope_per_decade"] == pytest.approx(1.0)


def test_model_track_rows_get_no_sensor_accuracy_and_stay_separate():
    nasa = _monthly("lake_skin_temp", lambda y, m: 15 + 0.1 * (y - 2000))
    other = schema.rows("simcoe_on", "forest_share", [f"{y}-01-01" for y in range(2001, 2015)], [40.0] * 14,
                        source="Model-training track: test", tier=V.TIER_ML)
    tr = analysis.trend_table(analysis.season_means(schema.combine(nasa, other)))
    assert set(tr["source"]) == {V.SOURCE_MOD11, "Model-training track: test"}
    assert pd.isna(tr.set_index("source").loc["Model-training track: test", "accuracy_value"])


def test_verdicts_and_correlations_never_claim_cause():
    rng = np.random.default_rng(1)
    noise = {y: rng.normal() for y in range(2000, 2020)}
    t = schema.combine(
        _monthly("lake_skin_temp", lambda y, m: 15 + 0.05 * (y - 2000) + noise[y]),
        _monthly("air_temp_2m", lambda y, m: 18 + 0.04 * (y - 2000) + noise[y]),
    )
    s = analysis.season_means(t)
    texts = list(analysis.trend_table(s)["verdict"]) + list(analysis.correlations(s)["text"])
    assert texts
    import re

    for txt in texts:
        assert not re.search(r"\bcaus(e|ed|es|ing|al)\b", txt.lower()), txt
    assert "associat" in " ".join(analysis.correlations(s)["text"])
    assert "cannot establish cause" in analysis.CAUSE_CAVEAT


def test_drift_flag_raised_by_pass_time_trend():
    t = schema.combine(
        _monthly("lake_skin_temp_day", lambda y, m: 15.0 + 0.01 * ((y * 7) % 5)),
        _monthly("air_temp_2m", lambda y, m: 18.0 + 0.01 * ((y * 3) % 5)),
        _monthly("modis_day_view_time", lambda y, m: 10.5 - 0.02 * (y - 2000)),
    )
    d = analysis.drift_check(analysis.season_means(t), "simcoe_on")
    assert d["flag"] is True and "Possible satellite orbit drift" in d["text"]


def test_no_drift_flag_when_sources_agree():
    rng = np.random.default_rng(3)
    common = {y: rng.normal() for y in range(2000, 2020)}
    jitter = {y: rng.normal(0, 0.01) for y in range(2000, 2020)}
    t = schema.combine(
        _monthly("lake_skin_temp_day", lambda y, m: 15.0 + common[y] + jitter[y]),
        _monthly("air_temp_2m", lambda y, m: 18.0 + common[y]),
        _monthly("modis_day_view_time", lambda y, m: 10.5 + jitter[y]),
    )
    d = analysis.drift_check(analysis.season_means(t), "simcoe_on")
    assert d["flag"] is False and "No sign of orbit drift" in d["text"]


def test_lake_minus_air_is_lake_minus_air():
    t = schema.combine(
        _monthly("lake_skin_temp", lambda y, m: 20.0),
        _monthly("air_temp_2m", lambda y, m: 18.5),
    )
    d = analysis.add_lake_minus_air(t)
    assert set(d["value"]) == {1.5} and set(d["tier"]) == {V.TIER_DERIVED}
