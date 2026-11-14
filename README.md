# LakePulse: Lake Trend Detective

A Centauri Research project. A submission to the 2026 NASA Space Apps Challenge,
"Be An Earth System Trend Detective!".

> Status: code built and tested on a labelled practice lake. Real Lake Simcoe data is not
> downloaded yet; it needs Earthdata Login credentials (see "Run it").

## What it does

Pick a lake and a variable, see its long monthly record, and get a plain-words verdict on
whether it is trending: direction, Sen's slope per decade, 95% confidence range and a
Mann-Kendall p-value (significant when p < 0.05).

- **Lake:** Lake Simcoe, Ontario (water pixels only, 500 m from shore).
- **Variables:** lake surface skin temperature (MODIS), air temperature, wind, pressure,
  sunlight and humidity (MERRA-2, a model), precipitation (GPM IMERG), forest, cropland and
  urban share and greenness (MODIS), and lake-minus-air temperature.
- **Labels:** every value carries a tier: "Satellite-derived", "Modeled (Simulation)" or
  "Derived (satellite minus model)".
- **Extra checks:** a sensor-accuracy check, correlations with drivers (raw and with trends
  removed, worded as associations), and a satellite orbit-drift cross-check.

Products, date ranges, accuracy figures and the two-day plan are in [docs/PLAN.md](docs/PLAN.md).

## Layout

| Path | What |
|---|---|
| `lakepulse/stats.py` | Mann-Kendall, Sen's slope + CI, detrending, correlation |
| `lakepulse/schema.py` | The one table: lake, variable, date, value, unit, source, tier |
| `lakepulse/variables.py` | Variable registry: units, tiers, sources, student definitions |
| `lakepulse/analysis.py` | Season means, trend table, verdicts, correlations, drift check |
| `lakepulse/sources/` | AppEEARS and GES DISC clients and processing |
| `scripts/` | Geometry, submit/fetch/process, build table, run analysis, practice data |
| `web/index.html` | The page (reads `web/site_data.js`) |
| `data/lake_trend_table.csv` | The table |
| `data/external/` | Drop-in CSVs from the model-training track (same 7 columns, own source name) |

## Run it

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
```

Put your Earthdata Login in `~/.netrc` (`machine urs.earthdata.nasa.gov login … password …`,
`chmod 600`), then:

```bash
.venv/bin/python scripts/submit_appeears.py      # first: AppEEARS requests queue
.venv/bin/python scripts/fetch_gesdisc.py        # MERRA-2 and IMERG
.venv/bin/python scripts/fetch_appeears.py       # when AppEEARS says done
.venv/bin/python scripts/process_appeears.py
.venv/bin/python scripts/build_table.py
.venv/bin/python scripts/run_analysis.py
python3 -m http.server 8765 --directory web      # open http://127.0.0.1:8765
```

## Data and attribution

MODIS MOD11A2, MOD13A3 and MCD12Q1 Version 6.1 (NASA LP DAAC, via AppEEARS); MERRA-2
M2TMNXSLV, M2TMNXFLX and M2TMNXRAD (NASA GES DISC); GPM IMERG Final V07 monthly (NASA GES
DISC). Lake outlines and watershed units: contains information licensed under the Open
Government Licence – Ontario.

## Licence

[verify: licence terms]

© Alpha Centauri Ventures Inc.
