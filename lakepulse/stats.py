"""Small statistics module: Mann-Kendall test, Sen's slope with confidence interval,
detrending and correlation.

Plain-words summary
- Mann-Kendall asks: across every pair of years, does the later value tend to be higher
  (or lower) than the earlier one more often than chance would give? It uses only the
  order of the values, so one wild value cannot dominate it.
- Sen's slope is the median of the slopes between every pair of points. It is the
  trend rate that matches the Mann-Kendall test, and it shrugs off outliers.
- The 95% confidence interval for Sen's slope follows Gilbert (1987), Statistical Methods
  for Environmental Pollution Monitoring, section 16.5: it picks ranked pair-slopes using
  the Mann-Kendall variance.

Times are in decimal years, so slopes come out "per year"; the analysis multiplies by 10
for "per decade".
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
from scipy import stats as sps

ALPHA = 0.05
MIN_POINTS = 10  # fewer points than this: we do not report a trend (see TrendResult.status)


@dataclass
class TrendResult:
    n: int
    status: str  # "ok" or "too_short"
    s: float | None = None
    var_s: float | None = None
    z: float | None = None
    p_value: float | None = None
    slope_per_year: float | None = None
    ci_low_per_year: float | None = None
    ci_high_per_year: float | None = None
    intercept: float | None = None  # Sen intercept at t = 0 (median of y - slope * t)
    significant: bool = False
    direction: str = "not assessed"  # "rising", "falling", "no change", "not assessed"

    def to_dict(self) -> dict:
        return asdict(self)


def _clean(t, y):
    t = np.asarray(t, dtype=float)
    y = np.asarray(y, dtype=float)
    if t.shape != y.shape:
        raise ValueError("t and y must have the same length")
    keep = np.isfinite(t) & np.isfinite(y)
    t, y = t[keep], y[keep]
    order = np.argsort(t, kind="stable")
    return t[order], y[order]


def mann_kendall_s(y) -> tuple[float, float]:
    """Return (S, variance of S) with the standard tie correction."""
    y = np.asarray(y, dtype=float)
    n = len(y)
    diff = y[None, :] - y[:, None]
    s = float(np.sign(diff[np.triu_indices(n, k=1)]).sum())
    _, counts = np.unique(y, return_counts=True)
    ties = counts[counts > 1]
    var_s = (n * (n - 1) * (2 * n + 5) - np.sum(ties * (ties - 1) * (2 * ties + 5))) / 18.0
    return s, float(var_s)


def pair_slopes(t, y) -> np.ndarray:
    t = np.asarray(t, dtype=float)
    y = np.asarray(y, dtype=float)
    i, j = np.triu_indices(len(t), k=1)
    dt = t[j] - t[i]
    ok = dt != 0
    return np.sort((y[j] - y[i])[ok] / dt[ok])


def trend(t, y, alpha: float = ALPHA, min_points: int = MIN_POINTS) -> TrendResult:
    """Mann-Kendall test and Sen's slope with a (1 - alpha) confidence interval."""
    t, y = _clean(t, y)
    n = len(y)
    if n < min_points:
        return TrendResult(n=n, status="too_short")
    s, var_s = mann_kendall_s(y)
    if var_s <= 0:  # every value identical
        z, p = 0.0, 1.0
    else:
        z = (s - np.sign(s)) / np.sqrt(var_s)  # continuity correction; 0 when s == 0
        p = float(2 * sps.norm.sf(abs(z)))
    slopes = pair_slopes(t, y)
    slope = float(np.median(slopes))
    n_pairs = len(slopes)
    c = sps.norm.ppf(1 - alpha / 2) * np.sqrt(max(var_s, 0.0))
    m1 = (n_pairs - c) / 2.0  # 1-based rank of the lower limit
    m2 = (n_pairs + c) / 2.0 + 1  # 1-based rank of the upper limit
    ranks = np.arange(1, n_pairs + 1)
    lo = float(np.interp(np.clip(m1, 1, n_pairs), ranks, slopes))
    hi = float(np.interp(np.clip(m2, 1, n_pairs), ranks, slopes))
    intercept = float(np.median(y - slope * t))
    significant = p < alpha
    if slope == 0 and not significant:
        direction = "no change"
    else:
        direction = "rising" if slope > 0 else "falling" if slope < 0 else "no change"
    return TrendResult(
        n=n,
        status="ok",
        s=s,
        var_s=var_s,
        z=float(z),
        p_value=p,
        slope_per_year=slope,
        ci_low_per_year=lo,
        ci_high_per_year=hi,
        intercept=intercept,
        significant=bool(significant),
        direction=direction,
    )


def total_change(result: TrendResult, t) -> float | None:
    """Sen's slope times the length of the record (last time minus first time)."""
    if result.status != "ok":
        return None
    t = np.asarray(t, dtype=float)
    t = t[np.isfinite(t)]
    return float(result.slope_per_year * (t.max() - t.min()))


def within_accuracy(change: float | None, accuracy: float | None) -> bool | None:
    """True when the total change over the record is smaller than the stated accuracy."""
    if change is None or accuracy is None:
        return None
    return abs(change) < accuracy


def linear_detrend(t, y) -> np.ndarray:
    """Remove the least-squares straight line; returns residuals (NaNs kept in place)."""
    t = np.asarray(t, dtype=float)
    y = np.asarray(y, dtype=float)
    out = np.full_like(y, np.nan)
    ok = np.isfinite(t) & np.isfinite(y)
    if ok.sum() < 3:
        return out
    b, a = np.polyfit(t[ok], y[ok], 1)
    out[ok] = y[ok] - (a + b * t[ok])
    return out


@dataclass
class CorrelationResult:
    n: int
    r_raw: float | None
    p_raw: float | None
    r_detrended: float | None
    p_detrended: float | None

    def to_dict(self) -> dict:
        return asdict(self)


def correlate(t, x, y, min_points: int = MIN_POINTS) -> CorrelationResult:
    """Pearson correlation of x and y on the raw series and after removing each series'
    own straight-line trend. Only time points where both are present are used."""
    t = np.asarray(t, dtype=float)
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    ok = np.isfinite(t) & np.isfinite(x) & np.isfinite(y)
    n = int(ok.sum())
    if n < min_points:
        return CorrelationResult(n, None, None, None, None)
    t, x, y = t[ok], x[ok], y[ok]

    def _r(a, b):
        if np.std(a) == 0 or np.std(b) == 0:
            return None, None
        r, p = sps.pearsonr(a, b)
        return float(r), float(p)

    r1, p1 = _r(x, y)
    r2, p2 = _r(linear_detrend(t, x), linear_detrend(t, y))
    return CorrelationResult(n, r1, p1, r2, p2)


def ols_slope(t, y) -> float:
    t, y = _clean(t, y)
    return float(np.polyfit(t, y, 1)[0])
