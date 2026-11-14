"""Make a clearly labelled practice lake with made-up data, so students (and we) can try the
page before the real downloads arrive. Every row carries the tier
"Synthetic (practice data, not real)". It is never mixed with a real lake.

Two series are built to teach the two outcomes:
  - lake surface temperature: a built-in rise of 0.5 °C per decade plus noise
  - precipitation: no built-in trend, only noise
Fixed random seed, so the file is the same every run.

Usage: .venv/bin/python scripts/make_practice_data.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lakepulse import schema  # noqa: E402
from lakepulse import variables as V  # noqa: E402

LAKE = "practice_lake"


def main() -> None:
    rng = np.random.default_rng(2026)
    months = pd.date_range("2000-01-01", "2025-12-01", freq="MS")
    yrs = (months.year + (months.month - 1) / 12 - 2000).to_numpy()
    season = np.cos(2 * np.pi * (months.month.to_numpy() - 7.5) / 12)  # peaks mid-summer
    year_noise = rng.normal(0, 0.6, size=26)[months.year - 2000]

    air = 7 + 14 * season + 0.04 * yrs + year_noise + rng.normal(0, 0.8, len(months))
    lake_day = np.maximum(0.5, 9 + 13 * season + 0.05 * yrs + 0.8 * year_noise + rng.normal(0, 0.7, len(months)))
    lake_night = np.maximum(0.3, lake_day - 1.5 + rng.normal(0, 0.4, len(months)))
    lake = (lake_day + lake_night) / 2
    precip = np.clip(75 + 10 * np.sin(2 * np.pi * months.month.to_numpy() / 12) + rng.normal(0, 22, len(months)), 5, None)
    wind = 4.2 - 0.6 * season + rng.normal(0, 0.3, len(months))
    sun = np.clip(150 + 110 * season + rng.normal(0, 12, len(months)), 10, None)
    view = 10.6 + rng.normal(0, 0.05, len(months))

    P = dict(source=V.SOURCE_PRACTICE, tier=V.TIER_PRACTICE)
    frames = [
        schema.rows(LAKE, "lake_skin_temp", months, lake.round(3), **P),
        schema.rows(LAKE, "lake_skin_temp_day", months, lake_day.round(3), **P),
        schema.rows(LAKE, "lake_skin_temp_night", months, lake_night.round(3), **P),
        schema.rows(LAKE, "modis_day_view_time", months, view.round(3), **P),
        schema.rows(LAKE, "air_temp_2m", months, air.round(3), **P),
        schema.rows(LAKE, "precipitation", months, precip.round(2), **P),
        schema.rows(LAKE, "wind_speed", months, wind.round(3), **P),
        schema.rows(LAKE, "solar_radiation", months, sun.round(2), **P),
        schema.rows(LAKE, "lake_minus_air", months, (lake - air).round(3), **P),
    ]
    out = ROOT / "data" / "practice" / "practice_lake.csv"
    schema.write(pd.concat(frames), out)
    print(f"wrote {sum(len(f) for f in frames)} practice rows to data/practice/practice_lake.csv")


if __name__ == "__main__":
    main()
