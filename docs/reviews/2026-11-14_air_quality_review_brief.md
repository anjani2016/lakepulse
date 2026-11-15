# Review brief: air-quality variables (uncommitted)

Gate: LakePulse air-quality variables — NO2, aerosol (satellite), aerosol (model).
Uncommitted; review `git diff` on branch `feat/lake-trend-detective`, HEAD `46c5e81`
(pushed). Repository: `~/dev/esg/lakepulse`. Author: Claude Code. Reviewer: Antigravity
(the owner had no time to review: "go ahead with your recommendatons. dont have enough time
to check"). The author must not review this change.

## Scope

Add two air-pollution variables for Lake Simcoe (catchment scope, same bounding box as
precipitation): OMI tropospheric NO2 (daily OMNO2d averaged to monthly) and aerosol optical
depth as two separate series, satellite (MODIS MOD08_M3) and model (MERRA-2 M2TMNXAER).
Registry entries, trend analysis, six correlation pairs with expectations written before
results, page changes, tests.

Owner decisions, verbatim:
- Brief: "Leave the work uncommitted and stop for my review. Do not push."
- Brief: "Do not change an expectation after seeing the result."
- Brief: "If a product is not reachable through the existing GES DISC client (MOD08_M3 may
  sit in a different archive), tell me which archive holds it and what access it needs
  before writing a new client."
- On MOD08_M3 access: "Try LAADS approval"; then "Approved, test it".
- "go ahead with your recommendatons. dont have enough time to check"

## Files in this gate

| File | What changed |
|---|---|
| `lakepulse/variables.py` | Three registry entries (`no2_trop_column`, `aod_satellite`, `aod_model`), new role `air`, three source strings |
| `lakepulse/sources/gesdisc.py` | `granules()` returns days (not months) and takes an OPeNDAP host; keeps only granules starting inside the range; `merra2_aer_rows`, `omno2d_box_value`, `monthly_from_daily`, `omno2d_rows`, `mod08_box_indices`, `mod08_rows` |
| `lakepulse/analysis.py` | Correlations rebuilt as one pair list: automatic lake pairs plus `data/expectations.json` pairs; every pair reported, including "not computed" |
| `data/expectations.json` | The six pairs and their expectations, dated 2026-11-14, written before any result |
| `scripts/fetch_gesdisc.py` | `--only aerosol`, `no2`, `mod08` options |
| `scripts/build_table.py` | `--skip-external` switch (see "Land-cover file" below) |
| `scripts/run_analysis.py` | Expectations and the trend note in the page data; prints every pair |
| `web/index.html` | "Air quality" picker group; pairs table with expected vs found; NO2 vs lake shown raw and detrended side by side |
| `tests/test_air_quality.py` | 17 tests (new) |
| `docs/PLAN.md` | Confirmed products, commands, access, screening |
| Data: `data/processed/simcoe_on_no2.csv`, `simcoe_on_merra2_aer.csv`, `simcoe_on_mod08.csv`, `data/qc/simcoe_on_no2_valid_days.csv` | Fetched series and NO2 valid-day counts |
| Generated: `data/lake_trend_table.csv`, `data/results/*.csv`, `web/site_data.js` | Rebuilt with `build_table.py --skip-external` and `run_analysis.py` |

## Not in this gate (leave alone)

- The land-cover track (`landcover/`, `data/external/land_cover_ca.csv`, `.gitignore`):
  committed separately by that track as `05b226c` after this brief was first written. Its
  CSV now uses the registry names (`forest_share`, `cropland_share`, `urban_share`) and
  tier "Modeled (Machine learning)" (27 rows), so the schema accepts it. Those rows are not
  part of this gate and have not been reviewed with it; this gate's table, results and page
  data are built with `--skip-external`.
- `data/results/drift.json`: unchanged by this gate.
- `web/assets/` (`lakepulse-logo.png`, `lakepulse-app-icon.png`) and `landcover/hf/`: untracked,
  not created by this author, not referenced by `web/index.html`; not part of this gate.

## Checks run (this session)

- `.venv/bin/python -m pytest -q tests` → `59 passed, 1 warning` (warning: numpy/netCDF4
  binary-size notice from `netCDF4`, not from project code). Bare `pytest` fails to collect
  `landcover/tests/test_lc.py` (`No module named 'yaml'`); that is the other track.
- `scripts/fetch_gesdisc.py --only aerosol` → 312 monthly files, box 2 × 1 MERRA-2 cells.
- `scripts/fetch_gesdisc.py --only no2` → 7,713 daily files for 2004-10-01 to 2025-12-31;
  3,710 valid days; 219 of 255 months kept (threshold 10 valid days); box 3 × 4 cells.
- `scripts/fetch_gesdisc.py --only mod08` → 311 monthly files, 230 with a valid value;
  box 1 × 1 cell (44.5°N, 79.5°W). Check value June 2015 = 0.182 (ASCII subset raw 182).
- `scripts/build_table.py --skip-external` → 7,369 rows.
- `scripts/run_analysis.py` → 27 trend series (14 significant), 24 correlation rows.
- No typecheck or lint configured in this repo; none run.

Browser (`python3 -m http.server` on `web/`, preview pane, one viewport ~650 px wide, light
theme only): Air-quality picker group lists the three variables with tier, source,
definition and notes; satellite aerosol shows 26 season dots; pairs table shows 15 Simcoe
pairs with expected vs found; NO2–lake box shows raw r = 0.09 (p = 0.752) and detrended
r = 0.30 (p = 0.272); console had no errors; no horizontal scroll. Not checked: dark theme,
phone width, other browsers.

## Please check

1. Scope: nothing outside the files above; no edits to the land-cover track.
2. Product facts against NASA CMR (`collections.umm_json`, `granules.json`,
   `variables.umm_json`): OMNO2d 004 (0.25°, molec/cm², from 2004-10-01), M2TMNXAER 5.12.4
   `TOTEXTTAU` (0.5° × 0.625°, unitless), MOD08_M3 6.1
   `AOD_550_Dark_Target_Deep_Blue_Combined_Mean_Mean` (1°, provider LAADS).
3. Screening and citations: OMNO2 README v5.0 p. 32 Table 4 and p. 33 eq. 5 (Weight);
   p. 36 on uncertainty fields; MODIS L3 ATBD C6/C6.1 p. 24 section 3.1. Accuracy left
   empty for all three: confirm no figure was missed.
4. Judgement calls (proposed by the author, not yet confirmed by the owner):
   - NO2 month counts only with ≥ 10 valid days.
   - NO2 day is valid when ≥ 50% of the box's cells have data.
   - Satellite aerosol uses a single 1° cell; model aerosol two MERRA-2 cells.
   - MOD08_M3 monthly value used as delivered (no own day threshold).
5. Grid index arithmetic in `omno2d_rows`, `merra2_aer_rows`, `mod08_box_indices`
   (cell centres inside the box; OMNO2d first cell edge at 180°W, 90°S; MOD08 YDim runs
   north to south).
6. `granules()` change: now returns days and filters to granules starting inside the
   range. Existing MERRA-2 and IMERG fetches round to month at the call site; confirm no
   month can be double counted.
7. `data/expectations.json`: the owner gave no expectation for satellite vs model aerosol;
   the file says so (`expected_sign: null`). Confirm the other five match the owner's words.
8. Wording: "associated with"; no "caused by" or "affects" in results. The only "cause"
   on the page is the required caveat.
9. Adversarial probes, please run at least: a box with no cell centre (expect ValueError
   from `mod08_box_indices` / `merra2_aer_rows`); OMNO2d day with all fill values
   (expect NaN); `monthly_from_daily` on an empty series; a negative NO2 column (kept: the
   README does not say to drop it — is that right?). Corrected after review 1: with the
   fixed land-cover CSV present, `build_table.py` without `--skip-external` succeeds and
   adds its 27 rows (7,396 total); the earlier "expect SchemaError" no longer applies. A
   CSV with an unknown variable or tier still raises SchemaError (tests/test_schema.py).

Unsure, stated plainly:
- Negative tropospheric NO2 values are kept as delivered; no document read says to drop
  them. In this run no monthly value is negative (0 of 219; minimum 0.5696 × 10^15,
  checked with pandas on `data/processed/simcoe_on_no2.csv`), but daily values were not
  inspected.
- LAADS applications approved (owner's screenshot): "LAADS Web" and "LAADS DAAC Cumulus
  (PROD)". Which one the OPeNDAP route needs was not tested separately; recorded in
  `docs/PLAN.md`.

## Results the gate produced (`scripts/run_analysis.py`)

| Series | Per decade (95% range) | p | Seasons |
|---|---|---|---|
| NO2 | −0.0983 (−0.629 to 0.158) × 10^15 molecules/cm² | 0.322 | 15 |
| Aerosol, satellite | +0.0065 (−0.0227 to 0.0252) | 0.597 | 26 |
| Aerosol, model | −0.0091 (−0.0218 to 0.0050) | 0.146 | 26 |

| Pair | Expected | Raw r (p) | Detrended r (p) |
|---|---|---|---|
| aerosol (satellite) vs solar | negative | 0.014 (0.945) | −0.013 (0.950) |
| aerosol (model) vs solar | negative | −0.229 (0.261) | −0.200 (0.328) |
| solar vs lake temperature | positive | 0.657 (< 0.001) | 0.661 (< 0.001) |
| aerosol (satellite) vs lake temperature | weak negative | 0.093 (0.651) | 0.032 (0.878) |
| NO2 vs lake temperature | none | 0.089 (0.752) | 0.303 (0.272) |
| aerosol (satellite) vs aerosol (model) | none stated | 0.827 (< 0.001) | 0.864 (< 0.001) |

## Record

Gate record: this file. Commit SHA: see "Sign-off" at the end.
Verdict format: APPROVED / CHANGES REQUESTED, with file:line for each item.

### Review 1 (2026-11-14, Antigravity), verbatim as relayed by the owner

CHANGES REQUESTED

1. [P1] Generated table includes the excluded land-cover track.
[data/lake_trend_table.csv (line 3681)](/Users/anjanid/dev/esg/lakepulse/data/lake_trend_table.csv:3681) contains 27 `Modeled (Machine learning)` rows, producing 7,396 rows instead of the documented 7,369. Meanwhile, the results and page were generated from the smaller dataset, so the committed artifacts are not mutually reproducible. Also, the expected `SchemaError` in the [review brief (line 98)](/Users/anjanid/dev/esg/lakepulse/docs/reviews/2026-11-14_air_quality_review_brief.md:98) does not occur because the schema intentionally accepts these rows. Rebuild with `scripts/build_table.py --skip-external`, rerun analysis, and correct that probe expectation.
2. [P2] The page’s data attribution omits all three new products.
[web/index.html (line 283)](/Users/anjanid/dev/esg/lakepulse/web/index.html:283) still lists only the pre-existing MODIS, MERRA-2, and IMERG products. Add OMNO2d 004, M2TMNXAER 5.12.4, and MOD08_M3 6.1/LAADS.

Verification completed:

* Fresh isolated virtualenv: `59 passed, 1 warning` in 13.14 seconds.
* All-fill NO₂ returned `NaN`; empty daily series returned an empty monthly table.
* No-cell MOD08 and MERRA-2 boxes raised the expected `ValueError`.
* Exactly 50% cell coverage was accepted; below 50% was rejected.
* Negative NO₂ values were retained, consistent with the README.
* NASA CMR confirmed all three products, variables, grids, units, providers, and start dates.
* Screening, weighting, and accuracy documentation were correctly interpreted.
* Grid arithmetic and monthly granule handling checked out.
* Phone-width layout had no page overflow; browser console had no warnings or errors.
* `git diff --check` passed.
* The four proposed screening/grid judgment calls are reasonable; I recommend accepting them, while documenting that the 10-day and 50% thresholds are project policy rather than NASA requirements.

### Fixes for review 1 (author, 2026-11-14; please re-review these)

Cause of item 1: the land-cover session, following the owner's prompt, ran
`scripts/build_table.py` without `--skip-external` in the shared folder after its CSV was
fixed (committed by that track as `05b226c`), which rewrote `data/lake_trend_table.csv`.

1. Rebuilt with `.venv/bin/python scripts/build_table.py --skip-external` → 7,369 rows,
   0 "Modeled (Machine learning)" rows; then `scripts/run_analysis.py` → 27 trend series,
   24 correlation rows. Check (pandas): table rows 7,369 = points in `web/site_data.js`
   7,369; 0 model-training rows in `data/results/season_means.csv`.
   Probe expectation corrected in this brief (item 9 above) and the "Not in this gate"
   entry updated for the land-cover commit.
2. Attribution: `web/index.html` footer and `README.md` now list MODIS MOD08_M3 6.1
   (LAADS DAAC), MERRA-2 M2TMNXAER 5.12.4 and OMI/Aura OMNO2d 004 (GES DISC). README cloud
   note also names "LAADS Web" and "LAADS DAAC Cumulus (PROD)".
3. Recommendation adopted: the 10-valid-day and 50%-of-cells thresholds are labelled
   "project policy, not NASA requirements" in `lakepulse/sources/gesdisc.py`,
   `lakepulse/variables.py` (NO2 note, shown on the page) and `docs/PLAN.md`.

Checks after the fixes:
- `.venv/bin/python -m pytest -q tests` → 59 passed, 1 warning. The "bare `pytest -q` → 59
  passed" claim first recorded here was wrong: the author had run `.venv/bin/python -m
  pytest -q`, which puts the repo root on the import path; plain `pytest` does not.
  Corrected after review 2 (see below).
- `git diff --check` → clean.
- Browser: footer lists all three new products; 15 Simcoe pairs; console clean; at a
  375 × 812 viewport no horizontal scroll.

### Review 2 (2026-11-14, Antigravity), verbatim as relayed by the owner

CHANGES REQUESTED

1. [P2] Bare `pytest -q` claim is not reproducible.
[air_quality_review_brief.md (line 181)](/Users/anjanid/dev/esg/lakepulse/docs/reviews/2026-11-14_air_quality_review_brief.md:181) records `59 passed`, but both the global command and `.venv/bin/pytest -q` fail collection with five `ModuleNotFoundError` errors. `.venv/bin/python -m pytest -q tests` succeeds. Either make bare pytest work—likely through root pytest configuration—or correct the recorded claim and required check.

All three review fixes otherwise pass:

* Generated artifacts: 7,369 rows, zero machine-learning rows, 7,369 site points.
* Rebuild hashes were byte-for-byte unchanged.
* Default build succeeded with 7,396 rows, including exactly 27 land-cover rows; scoped rebuild restored 7,369.
* Unknown tier and variable remain rejected: `tests/test_schema.py` → 14 passed.
* Attribution and LAADS application names are present.
* Both NO₂ thresholds are clearly labelled project policy.
* `.venv/bin/python -m pytest -q tests` → 59 passed, 1 warning in 4.48s.
* `git diff --check` is clean.
* No gate edits to `.gitignore`, `landcover/`, or `data/external/`.

### Fix for review 2 (author, 2026-11-14; please re-review)

- New `pytest.ini` at the repo root: `testpaths = tests`, `pythonpath = .`. Plain `pytest`
  now imports `lakepulse` from the root and collects only LakePulse's tests. The land-cover
  track's own `landcover/pytest.ini` still applies when run from `landcover/`.
- Results (each command run after the change):
  - `.venv/bin/pytest -q` → 59 passed, 1 warning
  - `.venv/bin/python -m pytest -q` → 59 passed, 1 warning
  - `.venv/bin/python -m pytest -q tests` → 59 passed, 1 warning
  - `cd landcover && .venv/bin/python -m pytest -q` → 16 passed (land-cover track, unchanged)
  - Global `pytest -q` (pyenv 3.10.13 shim) → 4 collection errors, none from the repo:
    three are the global SciPy 1.15.3 `dlopen ... __thread_bss` failure already logged in
    `~/dev/TASKS.md`, one is `No module named 'xarray'` (not installed globally). Tests are
    supported in the project venv only (workspace rule: verify in a clean, isolated
    virtualenv); the global interpreter is not a supported test environment.
- Required check from now on: `.venv/bin/pytest -q` (or `.venv/bin/python -m pytest -q`).

### Review 3 (2026-11-14, Antigravity / Codex), verbatim as relayed by the owner

APPROVED
The review-2 fix is correct:

* [pytest.ini (line 5)](/Users/anjanid/dev/esg/lakepulse/pytest.ini:5) sets `testpaths = tests` and `pythonpath = .`.
* `.venv/bin/pytest -q` → 59 passed, 1 warning.
* `.venv/bin/python -m pytest -q` → 59 passed, 1 warning.
* `cd landcover && .venv/bin/python -m pytest -q` → 16 passed.
* Global pytest produced exactly four dependency-related collection errors: three from the global SciPy binary and one missing `xarray`; no repository import/configuration failures.
* The corrected claims in [the review brief (line 212)](/Users/anjanid/dev/esg/lakepulse/docs/reviews/2026-11-14_air_quality_review_brief.md:212) are accurate.
* `git diff --check` is clean.
* The logo, app icon, and `landcover/hf` files were treated as outside this gate.
* No commit or push performed.

### Sign-off

Owner, verbatim: "approved, commit it".
Change commit: `cc71a8a` (Add air-quality variables: OMI NO2, MODIS and MERRA-2 aerosol optical depth).
Not pushed; the owner confirms pushes.
