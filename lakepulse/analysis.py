"""Open-water season means, trend table, correlations and the orbit-drift cross-check."""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from . import stats
from . import variables as V

SEASON_MONTHS = (5, 6, 7, 8, 9, 10)  # May to October
LATE_WINDOW = 10  # seasons used for the late-record drift check
CAUSE_CAVEAT = (
    "These are associations, not causes. One lake on its own cannot establish cause: "
    "many things change together over the same years."
)


# ---------------------------------------------------------------- season means
def season_means(table: pd.DataFrame, months=SEASON_MONTHS) -> pd.DataFrame:
    """One value per (lake, variable, source, year).

    Monthly variables: mean of May–October, only when all six months are present.
    Yearly variables: the yearly value as is.
    """
    df = table.copy()
    df["date"] = pd.to_datetime(df["date"])
    df["year"] = df["date"].dt.year
    freq = df["variable"].map(lambda v: V.get(v).frequency)
    keys = ["lake", "variable", "source", "tier", "unit", "year"]

    monthly = df[(freq == "monthly") & df["date"].dt.month.isin(months)]
    g = monthly.groupby(keys)["value"].agg(["mean", "count"]).reset_index()
    g = g[g["count"] == len(months)].rename(columns={"mean": "value", "count": "n_months"})

    yearly = df[freq == "yearly"][keys + ["value"]].assign(n_months=np.nan)
    return pd.concat([g, yearly], ignore_index=True).sort_values(keys).reset_index(drop=True)


# ---------------------------------------------------------------- formatting
def _fmt(x: float | None, sig: int = 3) -> str:
    if x is None or (isinstance(x, float) and not math.isfinite(x)):
        return "n/a"
    if x == 0:
        return "0"
    digits = max(0, sig - 1 - int(math.floor(math.log10(abs(x)))))
    return f"{x:.{min(digits, 4)}f}"


def _p(p: float | None) -> str:
    if p is None:
        return "n/a"
    return "< 0.001" if p < 0.001 else f"= {p:.3f}"


def _accuracy_for(var_id: str, source: str) -> dict | None:
    spec = V.get(var_id)
    return spec.accuracy if source == spec.source else None


def verdict(label: str, unit: str, res: stats.TrendResult, first: int | None, last: int | None,
            change: float | None, accuracy: dict | None) -> tuple[str, str]:
    """Return (accuracy_verdict, plain-words verdict)."""
    if res.status != "ok":
        return ("not assessed",
                f"Not enough open-water seasons yet ({res.n}). We need at least {stats.MIN_POINTS} "
                "to test for a trend.")
    per_dec = res.slope_per_year * 10
    lo, hi = res.ci_low_per_year * 10, res.ci_high_per_year * 10
    if res.direction == "no change":
        what = f"{label} showed no overall rise or fall over {first}–{last}."
    else:
        word = "rose" if per_dec > 0 else "fell"
        what = (f"{label} {word} by about {_fmt(abs(per_dec))} {unit} per decade over {first}–{last} "
                f"(95% confidence range {_fmt(lo)} to {_fmt(hi)} {unit} per decade).")
    if res.significant:
        sig = (f"This trend is statistically significant (Mann-Kendall p {_p(res.p_value)}, below 0.05): "
               "a trend this steady is unlikely to come from chance alone.")
    else:
        sig = (f"This is not statistically significant (Mann-Kendall p {_p(res.p_value)}, not below 0.05): "
               "ordinary year-to-year ups and downs could produce a pattern like this. A longer record might settle it.")
    acc_verdict = "no stated accuracy figure in the documentation read"
    acc = ""
    if accuracy is not None and change is not None:
        if stats.within_accuracy(change, accuracy["value"]):
            acc_verdict = "not distinguishable from sensor accuracy"
            acc = (f" The total change over the record ({_fmt(change)} {unit}) is smaller than the stated "
                   f"accuracy ({_fmt(accuracy['value'])} {accuracy['unit']}), so it is not distinguishable "
                   "from sensor accuracy.")
        else:
            acc_verdict = "larger than sensor accuracy"
            acc = (f" The total change over the record ({_fmt(change)} {unit}) is larger than the stated "
                   f"accuracy ({_fmt(accuracy['value'])} {accuracy['unit']}).")
    return acc_verdict, f"{what} {sig}{acc}"


# ---------------------------------------------------------------- trends
COMPARISON_ONLY_REASON = (
    "Shown for comparison only. For this variable the analysis uses one chosen source "
    "(see the notes), so no trend is tested on this one."
)


def _excluded(lake: str, var_id: str, source: str, chosen: dict) -> str | None:
    """Reason a series gets no statistics, or None. Fail closed: for a variable whose
    analysis source is chosen by tier, every other source on a real lake is excluded."""
    listed = V.excluded_reason(var_id, source)
    if listed:
        return listed
    if var_id in V.ANALYSIS_TIER and lake != "practice_lake" and chosen.get(lake, {}).get(var_id) != source:
        return COMPARISON_ONLY_REASON
    return None


def trend_table(seasonal: pd.DataFrame) -> pd.DataFrame:
    out = []
    chosen = {lake: analysis_sources(seasonal, lake) for lake in seasonal["lake"].unique()}
    for (lake, var_id, source), g in seasonal.groupby(["lake", "variable", "source"]):
        spec = V.get(var_id)
        g = g.sort_values("year")
        t, y = g["year"].to_numpy(float), g["value"].to_numpy(float)
        excluded = _excluded(lake, var_id, source, chosen)
        if excluded:
            # No statistics are presented for a series the project does not use.
            res = stats.TrendResult(n=len(y), status="excluded")
            change, acc, acc_verdict, text = None, None, "not assessed", excluded
        else:
            res = stats.trend(t, y)
            change = stats.total_change(res, t)
            acc = _accuracy_for(var_id, source)
            acc_verdict, text = verdict(spec.label, spec.unit, res,
                                        int(t.min()) if len(t) else None, int(t.max()) if len(t) else None, change, acc)
        out.append({
            "lake": lake, "variable": var_id, "label": spec.label, "source": source,
            "tier": g["tier"].iloc[0], "unit": spec.unit, "role": spec.role,
            "n_seasons": res.n, "first_year": int(t.min()) if len(t) else None, "last_year": int(t.max()) if len(t) else None,
            "status": res.status, "direction": res.direction,
            "slope_per_decade": None if res.slope_per_year is None else res.slope_per_year * 10,
            "ci_low_per_decade": None if res.ci_low_per_year is None else res.ci_low_per_year * 10,
            "ci_high_per_decade": None if res.ci_high_per_year is None else res.ci_high_per_year * 10,
            "sen_intercept": res.intercept,
            "mann_kendall_p": res.p_value, "significant": res.significant,
            "total_change": change,
            "accuracy_value": None if acc is None else acc["value"],
            "accuracy_citation": None if acc is None else acc["citation"],
            "accuracy_verdict": acc_verdict,
            "verdict": text,
        })
    return pd.DataFrame(out)


# ---------------------------------------------------------------- correlations
class AnalysisSourceError(ValueError):
    pass


def _analysis_rows(seasonal: pd.DataFrame, lake: str) -> pd.DataFrame:
    """The one series per variable that the analysis uses for a lake.

    - Variables in V.ANALYSIS_TIER use the rows with that tier (land cover: the land-cover-ca
      model); more than one source with that tier stops the analysis (fail closed).
    - Other variables use the registry source, or the practice source for the practice lake.
    - Series listed in V.EXCLUDED_FROM_ANALYSIS are never used.
    """
    s = seasonal[seasonal["lake"] == lake]
    keep = []
    for var_id, g in s.groupby("variable"):
        tier = V.ANALYSIS_TIER.get(var_id)
        if tier and lake != "practice_lake":
            g = g[g["tier"] == tier]
            if g["source"].nunique() > 1:
                raise AnalysisSourceError(f"{lake}/{var_id}: more than one '{tier}' source: {sorted(g['source'].unique())}")
        else:
            g = g[g["source"].isin([V.get(var_id).source, V.SOURCE_PRACTICE])]
        # Row mask as a Series: an empty Python list would select columns, not rows.
        g = g.loc[g["source"].map(lambda src: V.excluded_reason(var_id, src) is None).astype(bool)]
        keep.append(g)
    return pd.concat(keep) if keep else s.iloc[0:0]


def analysis_sources(seasonal: pd.DataFrame, lake: str) -> dict:
    """{variable: source} actually used for this lake (for the page and the record)."""
    r = _analysis_rows(seasonal, lake)
    return {v: g["source"].iloc[0] for v, g in r.groupby("variable")}


def _wide(seasonal: pd.DataFrame, lake: str) -> pd.DataFrame:
    """Season means for one lake, one column per variable, from the analysis series."""
    return _analysis_rows(seasonal, lake).pivot_table(index="year", columns="variable", values="value")


def _strength(r: float) -> str:
    a = abs(r)
    return "weak" if a < 0.3 else "moderate" if a < 0.6 else "strong"


EXPECTATIONS_FILE = Path(__file__).resolve().parents[1] / "data" / "expectations.json"
SPURIOUS_TREND_NOTE = (
    "Two series that both drift up (or down) over the years will look correlated even when "
    "nothing links them; removing each one's straight-line trend shows whether they still "
    "move together from one year to the next."
)


def load_expectations(path: Path = EXPECTATIONS_FILE) -> dict:
    return json.loads(path.read_text()) if path.exists() else {"pairs": []}


def correlation_pairs(available: list[str], response: str = "lake_skin_temp", expectations: dict | None = None) -> list[dict]:
    """One list of (x, y) pairs to test: the lake response against every driver and landscape
    variable, plus the pairs written in data/expectations.json. A pair appears once; when it
    is in both, the version carrying the written expectation is kept."""
    expectations = expectations if expectations is not None else load_expectations()
    pairs = {}
    for d in available:
        if V.get(d).role in ("driver", "landscape"):
            pairs[frozenset((d, response))] = {"x": d, "y": response, "expected_sign": None, "expectation": None}
    for p in expectations.get("pairs", []):
        pairs[frozenset((p["x"], p["y"]))] = {"x": p["x"], "y": p["y"], "expected_sign": p.get("expected_sign"),
                                              "expectation": p.get("expectation")}
    return list(pairs.values())


def _pair_text(xl: str, yl: str, c: stats.CorrelationResult) -> str:
    sign = "higher" if c.r_raw > 0 else "lower"
    sig = "statistically significant" if c.p_raw < 0.05 else "not statistically significant"
    text = (f"In years when {xl} was higher, {yl} tended to be {sign}: a {_strength(c.r_raw)} association "
            f"(r = {c.r_raw:.2f}, p {_p(c.p_raw)}, {sig}).")
    if c.r_detrended is not None:
        sig2 = "significant" if c.p_detrended < 0.05 else "not significant"
        text += (f" After removing each series' own straight-line trend, r = {c.r_detrended:.2f} "
                 f"(p {_p(c.p_detrended)}, {sig2}). This second number shows whether the two move "
                 "together from year to year, not just in the same long-term direction.")
    return text


def _found_sign(r: float | None, p: float | None) -> str | None:
    if r is None:
        return None
    if p is None or p >= 0.05:
        return "none (not significant)"
    return "positive" if r > 0 else "negative"


def correlations(seasonal: pd.DataFrame, response: str = "lake_skin_temp", expectations: dict | None = None) -> pd.DataFrame:
    """Every pair is reported, including pairs that cannot be computed yet (status says why)."""
    expectations = expectations if expectations is not None else load_expectations()
    out = []
    for lake in sorted(seasonal["lake"].unique()):
        w = _wide(seasonal, lake)
        for pair in correlation_pairs(list(w.columns), response, expectations):
            x, y = pair["x"], pair["y"]
            xl, yl = V.get(x).label.lower(), V.get(y).label.lower()
            row = {"lake": lake, **pair, "expectation_written_on": expectations.get("written_on") if pair["expectation"] else None}
            missing = [v for v in (x, y) if v not in w]
            if missing:
                out.append({**row, "status": "not computed: no data for " + ", ".join(missing), "n": 0,
                            "r_raw": None, "p_raw": None, "r_detrended": None, "p_detrended": None,
                            "found_raw": None, "found_detrended": None,
                            "text": f"Not computed yet: no {', '.join(V.get(m).label.lower() for m in missing)} data."})
                continue
            c = stats.correlate(w.index.to_numpy(float), w[x].to_numpy(float), w[y].to_numpy(float))
            if c.r_raw is None:
                text, status = f"Too few shared years ({c.n}) to compare {yl} with {xl}.", "too few shared years"
            else:
                text, status = _pair_text(xl, yl, c), "ok"
            out.append({**row, "status": status, **c.to_dict(),
                        "found_raw": _found_sign(c.r_raw, c.p_raw),
                        "found_detrended": _found_sign(c.r_detrended, c.p_detrended), "text": text})
    return pd.DataFrame(out)


# ---------------------------------------------------------------- orbit drift
def drift_check(seasonal: pd.DataFrame, lake: str) -> dict:
    """Compare the MODIS lake trend with the MERRA-2 air trend; flag possible orbit drift.

    Rule (stated in the output): flag when either
      (a) the satellite's daytime pass time shows a significant trend, or
      (b) the gap 'lake daytime skin temperature minus air temperature' has a significant
          trend over the last LATE_WINDOW seasons, i.e. the two sources diverge late in the record.
    """
    w = _wide(seasonal, lake)
    need = {"lake_skin_temp_day", "air_temp_2m"}
    if not need.issubset(w.columns):
        return {"lake": lake, "status": "missing inputs", "flag": None,
                "text": "The drift check needs both the MODIS lake temperature and the MERRA-2 air temperature."}

    def _tr(series: pd.Series):
        series = series.dropna()
        r = stats.trend(series.index.to_numpy(float), series.to_numpy(float))
        return r, series

    rep = {"lake": lake, "status": "ok", "late_window_seasons": LATE_WINDOW}
    for key, col in (("lake_day", "lake_skin_temp_day"), ("lake_night", "lake_skin_temp_night"), ("air", "air_temp_2m")):
        if col in w:
            r, s = _tr(w[col])
            rep[f"{key}_slope_per_decade"] = None if r.slope_per_year is None else r.slope_per_year * 10
            rep[f"{key}_p"] = r.p_value
    gap = (w["lake_skin_temp_day"] - w["air_temp_2m"]).dropna()
    r_full, _ = _tr(gap)
    r_late, _ = _tr(gap.iloc[-LATE_WINDOW:])
    rep.update({
        "gap_day_full_slope_per_decade": None if r_full.slope_per_year is None else r_full.slope_per_year * 10,
        "gap_day_full_p": r_full.p_value,
        "gap_day_late_slope_per_decade": None if r_late.slope_per_year is None else r_late.slope_per_year * 10,
        "gap_day_late_p": r_late.p_value,
        "gap_day_late_years": [int(gap.index[-LATE_WINDOW:].min()), int(gap.index.max())] if len(gap) else None,
    })
    view_flag = False
    if "modis_day_view_time" in w:
        r_v, _ = _tr(w["modis_day_view_time"])
        rep["view_time_slope_minutes_per_decade"] = None if r_v.slope_per_year is None else r_v.slope_per_year * 600
        rep["view_time_p"] = r_v.p_value
        view_flag = bool(r_v.significant)
    late_flag = bool(r_late.significant)
    rep["flag"] = view_flag or late_flag
    reasons = []
    if view_flag:
        reasons.append(f"the daytime pass time changed by {_fmt(rep['view_time_slope_minutes_per_decade'])} minutes per decade "
                       f"(p {_p(rep['view_time_p'])})")
    if late_flag:
        reasons.append(f"over {rep['gap_day_late_years'][0]}–{rep['gap_day_late_years'][1]} the lake-minus-air gap moved by "
                       f"{_fmt(rep['gap_day_late_slope_per_decade'])} °C per decade (p {_p(r_late.p_value)})")
    lake_t, air_t = rep.get("lake_day_slope_per_decade"), rep.get("air_slope_per_decade")
    practice = bool((seasonal[seasonal["lake"] == lake]["source"] == V.SOURCE_PRACTICE).any())
    sat, mod = ("Practice 'satellite'", "practice 'model'") if practice else ("MODIS", "MERRA-2")
    head = (f"{sat} daytime lake trend {_fmt(lake_t)} °C/decade vs {mod} air trend {_fmt(air_t)} °C/decade. ")
    if rep["flag"]:
        rep["text"] = head + ("Possible satellite orbit drift: " + "; ".join(reasons) +
                              ". Treat late-record daytime lake temperatures with caution; the night-time series is less sensitive to pass time.")
    else:
        rep["text"] = head + ("No sign of orbit drift in this check: the pass time shows no significant trend and the "
                              "lake and air series do not diverge significantly late in the record.")
    return rep


def add_lake_minus_air(table: pd.DataFrame) -> pd.DataFrame:
    """Derived monthly rows: lake skin temperature (day–night average) minus MERRA-2 T2M."""
    from . import schema

    t = table.copy()
    t["date"] = pd.to_datetime(t["date"])
    frames = []
    for lake in t["lake"].unique():
        lk = t[(t.lake == lake) & (t.variable == "lake_skin_temp") & (t.source == V.SOURCE_MOD11)].set_index("date")["value"]
        air = t[(t.lake == lake) & (t.variable == "air_temp_2m") & (t.source == V.SOURCE_MERRA_SLV)].set_index("date")["value"]
        d = (lk - air).dropna()
        if len(d):
            frames.append(schema.rows(lake, "lake_minus_air", d.index, d.values.round(3)))
    return pd.concat(frames) if frames else pd.DataFrame(columns=schema.COLUMNS)
