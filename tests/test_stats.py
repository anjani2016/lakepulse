"""Known-answer tests for lakepulse.stats."""
import math

import numpy as np
import pytest

from lakepulse import stats

YEARS = np.arange(2000, 2020, dtype=float)  # 20 points


def test_flat_series_has_no_trend():
    r = stats.trend(YEARS, np.full(20, 5.0))
    assert r.status == "ok"
    assert r.s == 0
    assert r.var_s == 0  # all values tied
    assert r.p_value == 1.0
    assert r.slope_per_year == 0
    assert (r.ci_low_per_year, r.ci_high_per_year) == (0, 0)
    assert r.significant is False
    assert r.direction == "no change"


def test_perfect_linear_rise():
    y = 2.0 * (YEARS - 2000) + 1.0
    r = stats.trend(YEARS, y)
    n = 20
    assert r.s == n * (n - 1) / 2 == 190
    assert r.var_s == pytest.approx(n * (n - 1) * (2 * n + 5) / 18) == 950
    z = (190 - 1) / math.sqrt(950)
    assert r.z == pytest.approx(z)
    assert r.p_value == pytest.approx(2 * (1 - 0.5 * (1 + math.erf(z / math.sqrt(2)))), rel=1e-6)
    assert r.slope_per_year == pytest.approx(2.0)
    assert r.ci_low_per_year == pytest.approx(2.0)
    assert r.ci_high_per_year == pytest.approx(2.0)
    assert r.significant and r.direction == "rising"


def test_perfect_linear_fall_is_falling():
    r = stats.trend(YEARS, -0.5 * YEARS)
    assert r.slope_per_year == pytest.approx(-0.5)
    assert r.significant and r.direction == "falling"


def test_single_outlier_does_not_move_sens_slope():
    y = 2.0 * (YEARS - 2000) + 1.0
    y[-1] += 100.0  # last year: the point with most leverage on a least-squares line
    r = stats.trend(YEARS, y)
    assert r.slope_per_year == pytest.approx(2.0)  # 171 of 190 pair slopes are exactly 2
    assert r.significant
    assert stats.ols_slope(YEARS, y) > 3.0  # least squares is pulled well away from 2


def test_too_short_record_is_not_assessed():
    r = stats.trend(YEARS[:9], YEARS[:9])
    assert r.status == "too_short"
    assert r.p_value is None and r.slope_per_year is None
    assert r.significant is False and r.direction == "not assessed"
    assert stats.total_change(r, YEARS[:9]) is None


def test_missing_values_are_dropped_before_counting():
    y = YEARS.copy()
    y[[1, 4, 7]] = np.nan
    assert stats.trend(YEARS[:12], y[:12]).status == "too_short"  # 9 usable points
    assert stats.trend(YEARS, y).n == 17


def test_mann_kendall_small_hand_example():
    s, var = stats.mann_kendall_s([1, 3, 2, 4, 5])
    assert s == 8
    assert var == pytest.approx(5 * 4 * 15 / 18)


def test_mann_kendall_tie_correction():
    s, var = stats.mann_kendall_s([1, 1, 2])
    assert s == 2
    assert var == pytest.approx((3 * 2 * 11 - 2 * 1 * 9) / 18)


def test_confidence_interval_brackets_slope_on_noisy_series():
    rng = np.random.default_rng(42)
    y = 0.3 * (YEARS - 2000) + rng.normal(0, 1.0, size=20)
    r = stats.trend(YEARS, y)
    assert r.ci_low_per_year < r.slope_per_year < r.ci_high_per_year


def test_total_change_and_sensor_accuracy_rule():
    y = 0.02 * (YEARS - 2000)
    r = stats.trend(YEARS, y)
    change = stats.total_change(r, YEARS)
    assert change == pytest.approx(0.02 * 19)
    assert stats.within_accuracy(change, 1.0) is True
    assert stats.within_accuracy(2.5, 1.0) is False
    assert stats.within_accuracy(change, None) is None


def test_detrended_correlation_removes_shared_trend():
    rng = np.random.default_rng(7)
    x = 0.5 * (YEARS - 2000) + rng.normal(0, 0.3, 20)
    y = 0.5 * (YEARS - 2000) + rng.normal(0, 0.3, 20)
    c = stats.correlate(YEARS, x, y)
    assert c.r_raw > 0.9
    assert abs(c.r_detrended) < c.r_raw - 0.5


def test_correlation_too_short():
    c = stats.correlate(YEARS[:5], YEARS[:5], YEARS[:5])
    assert c.r_raw is None and c.r_detrended is None
