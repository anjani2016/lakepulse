"""The one tidy table: lake, variable, date, value, unit, source, tier.

One row = one value of one variable for one lake on one date.
- Monthly values use the first day of the month as the date (2014-07-01).
- Yearly values use 1 January (2014-01-01).
- Rows from a separate model-training track (for example yearly land-cover shares) go in
  the same table with their own `source` name and the tier "Modeled (Machine learning)".
  The analysis keeps each (lake, variable, source) as its own series, so the two tracks
  never mix.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from . import variables as V

COLUMNS = ["lake", "variable", "date", "value", "unit", "source", "tier"]
KEY = ["lake", "variable", "date", "source"]


class SchemaError(ValueError):
    pass


def validate(df: pd.DataFrame) -> pd.DataFrame:
    """Check the table and return a cleaned copy (date parsed, columns in order).

    Raises SchemaError on any problem. It never fills or guesses missing values.
    """
    missing = [c for c in COLUMNS if c not in df.columns]
    if missing:
        raise SchemaError(f"missing columns: {missing}")
    extra = [c for c in df.columns if c not in COLUMNS]
    if extra:
        raise SchemaError(f"unexpected columns: {extra}")
    out = df[COLUMNS].copy()
    for col in ("lake", "variable", "unit", "source", "tier"):
        if out[col].isna().any() or (out[col].astype(str).str.strip() == "").any():
            raise SchemaError(f"column '{col}' has empty values")
    try:
        out["date"] = pd.to_datetime(out["date"], format="%Y-%m-%d")
    except (ValueError, TypeError) as exc:
        raise SchemaError(f"dates must be YYYY-MM-DD: {exc}") from exc
    if (out["date"].dt.day != 1).any():
        raise SchemaError("dates must be the first of the month (monthly) or 1 January (yearly)")
    out["value"] = pd.to_numeric(out["value"], errors="coerce")
    if out["value"].isna().any():
        raise SchemaError("column 'value' has missing or non-numeric values; drop the row instead")
    bad_tier = sorted(set(out["tier"]) - set(V.TIERS))
    if bad_tier:
        raise SchemaError(f"unknown tier(s): {bad_tier}; allowed: {list(V.TIERS)}")
    unknown_var = sorted(set(out["variable"]) - set(V.VARIABLES))
    if unknown_var:
        raise SchemaError(f"unknown variable(s): {unknown_var}")
    for var_id, grp in out.groupby("variable"):
        spec = V.get(var_id)
        units = set(grp["unit"])
        if units != {spec.unit}:
            raise SchemaError(f"variable '{var_id}' must use unit '{spec.unit}', found {sorted(units)}")
        if spec.frequency == "yearly" and (grp["date"].dt.month != 1).any():
            raise SchemaError(f"yearly variable '{var_id}' must be dated 1 January")
        if spec.unit == "%" and ((grp["value"] < 0) | (grp["value"] > 100)).any():
            raise SchemaError(f"variable '{var_id}' has percentages outside 0–100")
    dup = out.duplicated(KEY, keep=False)
    if dup.any():
        raise SchemaError(f"{int(dup.sum())} duplicate rows on {KEY}")
    return out.sort_values(KEY).reset_index(drop=True)


def read(path: str | Path) -> pd.DataFrame:
    return validate(pd.read_csv(path, dtype={"lake": str, "variable": str, "unit": str, "source": str, "tier": str}))


def write(df: pd.DataFrame, path: str | Path) -> None:
    out = validate(df)
    out["date"] = out["date"].dt.strftime("%Y-%m-%d")
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(path, index=False)


def combine(*frames: pd.DataFrame) -> pd.DataFrame:
    """Stack several tables (e.g. NASA rows + model-training-track rows) and validate."""
    parts = [f for f in frames if f is not None and len(f)]
    if not parts:
        return pd.DataFrame(columns=COLUMNS)
    stacked = pd.concat([p[COLUMNS].assign(date=pd.to_datetime(p["date"]).dt.strftime("%Y-%m-%d")) for p in parts])
    return validate(stacked)


def rows(lake: str, variable: str, dates, values, source: str | None = None, tier: str | None = None) -> pd.DataFrame:
    """Build table rows for one series, taking unit/source/tier from the registry by default."""
    spec = V.get(variable)
    df = pd.DataFrame({"date": pd.to_datetime(list(dates)), "value": list(values)})
    df = df.dropna(subset=["value"])
    df["lake"] = lake
    df["variable"] = variable
    df["unit"] = spec.unit
    df["source"] = source or spec.source
    df["tier"] = tier or spec.tier
    df["date"] = df["date"].dt.strftime("%Y-%m-%d")
    return df[COLUMNS]
