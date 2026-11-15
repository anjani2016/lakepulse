# LakePulse: Lake Trend Detective

A submission to the 2026 NASA Space Apps Challenge, "Be An Earth System Trend Detective!",
entered in a personal capacity.

**Team:** Anjani Duddukuru, with a team member under 18 (name withheld, as the Space Apps rules ask) who designed the LakePulse logo with OpenAI Codex, read the challenge rules, guidelines and challenge options, and created the presentation template.

> Status: working prototype with real data for Lake Simcoe, Ontario (2000–2025), built from
> NASA satellite and model products. A clearly labelled practice lake with made-up data is
> also included for learning; it is never mixed with the real lake.

## What it does

Pick a lake and a variable, see its long monthly record, and get a plain-words verdict on
whether it is trending: direction, Sen's slope per decade, 95% confidence range and a
Mann-Kendall p-value (significant when p < 0.05). Each year's open-water season (May to
October) is averaged into one value before testing.

## Main results (Lake Simcoe, May–October means, 2000–2025)

From `scripts/run_analysis.py` (`data/results/trends.csv`):

- **Lake surface temperature at night rose 0.649 °C per decade** (95% range 0.328 to
  0.921; p = 0.0009). This is the most robust lake result: the night-time pass is less
  affected by the satellite's drifting overpass time (see "Limits"), and the total change
  is larger than the sensor's 1 K accuracy.
- Day–night average: +0.493 °C per decade (p = 0.0036). Daytime only: +0.380 °C per decade
  (p = 0.022), which is **not** distinguishable from sensor accuracy over the record.
- Air temperature at 2 m (MERRA-2 model): +1.13 °C per decade (p < 0.001); humidity also
  rose significantly. Precipitation, sunlight, wind, pressure, NO₂ and aerosol show no
  significant trend.
- The lake surface warmed more slowly than the air above it: lake-minus-air temperature
  fell 0.592 °C per decade (p < 0.001).
- Correlations are reported as associations; one lake cannot establish cause.

## Limits (read before using the results)

- **Satellite pass-time drift.** The Terra satellite's daytime pass moved 7.7 minutes
  earlier per decade (p < 0.001). The page flags possible orbit drift; daytime lake
  temperatures are treated with caution and the night-time series is preferred.
- **MODIS measures skin temperature**, the top fraction of a millimetre of water, not the
  water column.
- **Catchment variables use a bounding box** (6,962 km²) about twice the area of the six
  watershed units used as the lake's catchment (3,383 km²). Precipitation, NDVI, aerosol,
  NO₂ and MODIS land cover cover that box, not the exact catchment.
- **Land cover: two sources disagree** (MODIS 500 m vs the 30 m land-cover-ca model, by
  11–25 percentage points over the same area). MODIS land cover is **not used** for
  analysis: its user guide warns against reading change from its yearly labels, and our
  check found 48.4% of the land in in-between classes. The land-cover-ca model is used for
  how much of each kind of land there is, but its 9-year record is too short to test a
  trend. Details: `docs/PLAN.md`.
- **Model values are not measurements.** MERRA-2 variables are labelled
  "Modeled (Simulation)"; air temperature has not yet been cross-checked against a
  Giovanni time series (planned).
- **Regional values.** NO₂ (0.25°), aerosol (0.5°–1°) and weather (0.5° × 0.625°) are
  regional, not readings at the lake. NO₂ is the amount in the whole air column, not the
  concentration people breathe.
- Thresholds such as "at least 10 valid days per month" for NO₂ are project choices, not
  NASA requirements.

## How AI was used

- **Claude Code (Anthropic)** wrote the code, data pipelines, tests, page and
  documentation, under the author's direction and decisions.
- **Codex (OpenAI)** reviewed the main changes against written review briefs and ran its own
  checks and probes. The LakePulse logo and icons were designed by the team member under 18
  using Codex.
- **The land-cover-ca track** (`landcover/`) has its own report, model card and review
  records; see `landcover/REPORT.md`.
- **The author** chose the scope, region, variables and every analysis decision (for
  example which land-cover source to use and which to exclude), set up the data and cloud
  accounts, and approved commits and pushes. Reviews were done by a second AI agent, not
  line by line by a person; the logo change was committed without review at the author's
  choice. Every number in the documentation comes from a command that was run; review
  records are in `docs/reviews/`.

## Layout

| Path | What |
|---|---|
| `lakepulse/stats.py` | Mann-Kendall, Sen's slope + CI, detrending, correlation |
| `lakepulse/schema.py` | The one table: lake, variable, date, value, unit, source, tier |
| `lakepulse/variables.py` | Variable registry: units, tiers, sources, student definitions |
| `lakepulse/analysis.py` | Season means, trend table, verdicts, correlations, drift check |
| `lakepulse/sources/` | AppEEARS and OPeNDAP clients and processing |
| `scripts/` | Geometry, fetch/process, build table, run analysis, practice data |
| `web/index.html` | The page (reads `web/site_data.js`) |
| `data/lake_trend_table.csv` | The table |
| `data/external/` | Rows from the land-cover-ca model (same 7 columns, own source name) |
| `landcover/` | The land-cover-ca model track (its own README, report and tests) |
| `docs/PLAN.md` | Products, date ranges, methods, decisions; `docs/reviews/` review records |

## Run it

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest -q
```

Put your Earthdata Login in `~/.netrc` (`machine urs.earthdata.nasa.gov login … password …`,
`chmod 600`), then:

```bash
.venv/bin/python scripts/submit_appeears.py      # first: AppEEARS requests queue
.venv/bin/python scripts/fetch_gesdisc.py        # MERRA-2, IMERG, aerosol, NO2
.venv/bin/python scripts/fetch_appeears.py       # when AppEEARS says done
.venv/bin/python scripts/process_appeears.py
.venv/bin/python scripts/build_table.py
.venv/bin/python scripts/run_analysis.py
python3 -m http.server 8765 --directory web      # open http://127.0.0.1:8765
```

The Earthdata account needs the "NASA GESDISC DATA ARCHIVE", "LAADS Web" and "LAADS DAAC
Cumulus (PROD)" applications approved. In a cloud session without `~/.netrc`, set
`EARTHDATA_USERNAME` and `EARTHDATA_PASSWORD` as secrets; the scripts never print them.

## References

NASA data (DOIs confirmed in NASA CMR, 2026-11-14):
- MODIS/Terra Land Surface Temperature/Emissivity 8-Day L3 Global 1 km, MOD11A2 v061.
  doi:10.5067/MODIS/MOD11A2.061
- MODIS/Terra Vegetation Indices Monthly L3 Global 1 km, MOD13A3 v061.
  doi:10.5067/MODIS/MOD13A3.061
- MODIS/Terra+Aqua Land Cover Type Yearly L3 Global 500 m, MCD12Q1 v061.
  doi:10.5067/MODIS/MCD12Q1.061
- MODIS/Terra Aerosol Cloud Water Vapor Ozone Monthly L3 Global 1Deg, MOD08_M3 v061.
  doi:10.5067/MODIS/MOD08_M3.061
- MERRA-2 tavgM_2d_slv_Nx (M2TMNXSLV) 5.12.4. doi:10.5067/AP1B0BA5PD2K
- MERRA-2 tavgM_2d_flx_Nx (M2TMNXFLX) 5.12.4. doi:10.5067/0JRLVL8YV2Y4
- MERRA-2 tavgM_2d_rad_Nx (M2TMNXRAD) 5.12.4. doi:10.5067/OU3HJDS973O0
- MERRA-2 tavgM_2d_aer_Nx (M2TMNXAER) 5.12.4. doi:10.5067/FH9A0MLJPC7N
- GPM IMERG Final Precipitation L3 1 month 0.1°, GPM_3IMERGM V07.
  doi:10.5067/GPM/IMERG/3B-MONTH/07
- OMI/Aura NO₂ Cloud-Screened Total and Tropospheric Column L3 Global Gridded 0.25°,
  OMNO2d Collection 004. doi:10.5067/AURA/OMI/DATA3407

Product documentation used for screening and accuracy: MOD11 User Guide V6.1 and ATBD;
MOD13 User Guide V6.1; MCD12 User Guide V6.1; OMNO2 README v5.0 (Dec 2024); MERRA-2
README; MODIS Atmosphere L3 ATBD C6/C6.1 (2019-02-20). Page references are in
`docs/PLAN.md` and `lakepulse/variables.py`.

Other data and models:
- Ontario Hydro Network — Waterbody; Ontario Watershed Boundaries (Land Information
  Ontario). Contains information licensed under the Open Government Licence – Ontario.
- land-cover-ca track: Prithvi-EO-2.0-300M (Apache-2.0), 2020 Land Cover of Canada (Open
  Government Licence – Canada), Copernicus Sentinel-2 L2A via Earth Search; full list and
  attribution in `landcover/REPORT.md`.

Software: NumPy, pandas, SciPy, Shapely, pyproj, xarray, netCDF4, h5netcdf, h5py,
requests, pytest; nginx in the deployment image. Licences are listed in `NOTICE`.

Methods: Mann (1945) and Kendall (1975) trend test; Sen (1968) slope; confidence interval
after Gilbert (1987), *Statistical Methods for Environmental Pollution Monitoring*, §16.5.

Use of NASA data does not imply NASA endorsement.

## Licence

Copyright 2026 Anjani Duddukuru. Licensed under the Apache License, Version 2.0; see
`LICENSE`. Third-party data, models and software keep their own terms; see `NOTICE`.
