# Lake Trend Detective: products, region and two-day plan

Checked 2026-11-14. Each product name and date range below was read from the portal's
own catalog by a command run that day; the command is named in the "Checked with" column.

## Challenge

"Be An Earth System Trend Detective!" (2026 NASA Space Apps). The page asks for four
things: identify variables, acquire them for a region, generate and visualize a long
time series, and test the trend's significance (t-test, Mann-Kendall or confidence
intervals). It notes linear trends are "a great start", suggests simple variable
definitions for a student audience and "a couple of demonstration examples".
Read from the page's embedded content with `curl` (the page renders by script).

## Confirmed products

| Variable | Product (exact) | Layer / variable | Resolution | Date range on the portal | Checked with |
|---|---|---|---|---|---|
| Lake surface (skin) temperature, day & night | MOD11A2.061 (Terra MODIS, LST&E) | LST_Day_1km, LST_Night_1km, QC_Day, QC_Night, Day_view_time | 1000 m, 8-day | 2000-02-18 to Present | AppEEARS `GET /api/product` and `/api/product/MOD11A2.061` |
| Vegetation greenness | MOD13A3.061 (Terra MODIS, VI) | _1_km_monthly_NDVI, _1_km_monthly_pixel_reliability | 1000 m, monthly | 2000-02-01 to Present | AppEEARS `GET /api/product` |
| Land cover (forest, cropland, urban) | MCD12Q1.061 (combined MODIS) | LC_Type1 (IGBP) | 500 m, yearly | 2001-01-01 to Present | AppEEARS `GET /api/product` |
| Air temperature 2 m, surface pressure, humidity | M2TMNXSLV 5.12.4 (MERRA-2 tavgM_2d_slv_Nx) | T2M (K), PS (Pa), QV2M (kg kg-1) | 0.5° × 0.625°, monthly | 1980-01-01 onward (ends-at-present flag set); latest granule 2026-09 | CMR `collections.umm_json`, `granules.json`, `variables.umm_json` |
| Wind speed | M2TMNXFLX 5.12.4 (MERRA-2 tavgM_2d_flx_Nx) | SPEED (m s-1) | 0.5° × 0.625°, monthly | 1980-01-01 onward | CMR |
| Solar radiation | M2TMNXRAD 5.12.4 (MERRA-2 tavgM_2d_rad_Nx) | SWGDN (W m-2) | 0.5° × 0.625°, monthly | 1980-01-01 onward | CMR |
| Precipitation | GPM_3IMERGM 07 (IMERG Final, 1 month) | Grid/precipitation (mm/hr) | 0.1° × 0.1°, monthly | 1998-01-01 to 2025-09-30 (collection end in CMR; latest granule 2025-09) | CMR |

Other products seen in the AppEEARS catalog but not used: MYD11A2.061 (Aqua, from
2002-07-04), MOD11A1.061 (daily), MOD21A2.061, MOD44W.061 (water mask, 250 m), MOD13Q1.061.

Consequences:
- Common analysis period is 2000–2025. IMERG Final V07 stops at 2025-09, so its 2025
  open-water season is incomplete and is dropped by the six-month rule.
- **Giovanni**: the catalog and `api.giovanni.earthdata.nasa.gov` returned 403 / "Missing
  Authentication Token" without a login, and no public spec for the time-series call
  was found. We read the same GES DISC monthly files through the Earthdata cloud OPeNDAP
  server (`opendap.earthdata.nasa.gov`), asking only for the grid cells we need. Streaming
  whole files took over 10 minutes for one month; a subset request takes about a second.
  Access needs the "NASA GESDISC DATA ARCHIVE" application approved in the Earthdata
  profile, and a bearer token (fetched in memory from the same credentials).
  Not done yet (planned): one Giovanni area-averaged T2M time series over the Simcoe box,
  compared with ours. Stated as a limit in README.md.
- **Tiers**: MERRA-2 rows are "Modeled (Simulation)". MODIS and IMERG rows are
  "Satellite-derived". Lake-minus-air is "Derived (satellite minus model)".
- **MODIS measures skin temperature**, the top fraction of a millimetre, not the water column.

## Air-quality variables (added 2026-11-14)

Checked in NASA CMR on 2026-11-14 with: `collections.umm_json?short_name=…` (name, version,
date range, provider), `granules.json?short_name=…&version=…&sort_key=±start_date` (first and
latest granule, access links) and `variables.umm_json` for the collection's associated
variables (name, units, dimensions).

| Variable | Product (exact) | Variable in file | Grid | Units | Date range | Archive |
|---|---|---|---|---|---|---|
| NO2 tropospheric column | OMNO2d 004 (OMI/Aura, v5.0, Col 004), daily | `ColumnAmountNO2TropCloudScreened`, `Weight` | 0.25° × 0.25° (720 × 1440) | molec/cm² (stored as 10^15 molecules/cm²) | 2004-10-01 to 2026-11-12 (latest granule) | GES DISC |
| Aerosol optical depth, model | M2TMNXAER 5.12.4 (MERRA-2 tavgM_2d_aer_Nx), monthly | `TOTEXTTAU` (total aerosol extinction AOT, 550 nm) | 0.5° × 0.625° (361 × 576) | 1 (unitless) | 1980-01 to 2026-09 | GES DISC |
| Aerosol optical depth, satellite | MOD08_M3 6.1 (Terra MODIS), monthly | `AOD_550_Dark_Target_Deep_Blue_Combined_Mean_Mean` | 1° × 1° (180 × 360) | none | 2000-02-01 to 2026-10-01 | **LAADS DAAC** |

Also seen: OMNO2d 003 (V3), 2004-10-01 to 2026-03-15; not used (004 is the newer release).

Access:
- OMNO2d and M2TMNXAER: Earthdata cloud OPeNDAP with the existing client (subset requests).
- MOD08_M3: not on the GES DISC/cloud OPeNDAP route. Before approval, LAADS OPeNDAP
  returned "403 Access Denied by OAuth2 Provider"; LAADS cloud HTTPS serves whole files only
  (HDF4; one file measured 393,401,536 bytes; about 122.3 GB for 311 months). After the
  owner approved the LAADS application in Earthdata Login (2026-11-14), LAADS OPeNDAP
  (`ladsweb.modaps.eosdis.nasa.gov/opendap`) answered with 200 and accepts the same DAP4
  subset request the existing client sends, so no new client was written; the CMR granule
  lookup takes the OPeNDAP host as a parameter. One 1° cell centre lies in the catchment
  box: 44.5°N, 79.5°W. Check value: June 2015 = 0.182 (raw 182 × 0.001).
  Earthdata Login → Applications → Authorized Apps (owner's screenshot, 2026-11-14) lists
  "LAADS Web" and "LAADS DAAC Cumulus (PROD)", alongside "AppEEARS" and "NASA GESDISC DATA
  ARCHIVE". "LAADS Web" matches the OPeNDAP host (ladsweb.modaps.eosdis.nasa.gov); the
  Cumulus cloud HTTPS route already answered before the approval. Which of the two LAADS
  approvals the OPeNDAP route needs was not tested separately; keep both approved.
- MOD08_M3 screening: the product's own (MODIS Atmosphere L3 ATBD C6/C6.1, 2019-02-20, p. 24,
  section 3.1: L2 QA flags aggregate and QA-weight the L3 statistics; file attributes
  Statistic_Type "Simple_MND", Weighting "MinNumDays", QA set "Quality_Assurance_Land").
  We drop fill (−9999) and values outside the valid range (0–5000 raw, 0–5 scaled).

Screening and handling:
- OMNO2d: the product's own screening applies (OMNO2 README v5.0, Dec 2024, p. 32, Table 4):
  solar zenith < 85°, effective cloud fraction < 30% for the cloud-screened field,
  XTrackQualityFlagsModified 0 or 255, ascending orbit, VCD summary flags not set. Fill
  value −1.26765e30 dropped. Cells combined with the `Weight` field (p. 33, eq. 5).
  A day counts when at least half the box's cells have data; a month counts with at least
  **10 valid days**; otherwise the month is missing. Both thresholds are **project policy,
  not NASA requirements** (the README sets neither). Proposed by the author; review 1
  (2026-11-14) recommends accepting them; owner's standing instruction: "go ahead with your
  recommendatons". Valid-day counts per
  month are in `data/qc/simcoe_on_no2_valid_days.csv`. Winter gaps are not filled.
- M2TMNXAER: model output, no screening; cos(latitude)-weighted mean of cells in the box.
- Accuracy: none filled. OMNO2 README p. 36 says its uncertainty fields "should not be used
  for data quality assessments"; the MERRA-2 README (TOTEXTTAU listed p. 27) gives no
  accuracy figure. MOD08_M3: no figure found in the MODIS Atmosphere L3 ATBD read
  (2019-02-20); the Level-2 aerosol ATBD was not read. Accuracy left empty for all three.

Correlation pairs and the expectations written before results are in `data/expectations.json`.

## Land cover: which source the analysis uses (decided 2026-11-14)

Owner, verbatim: "we use the guideline and our own assessment and exclude it for analysis";
"go ahead, but we choose one and say why?"; on showing both sources flagged: "ok".

- **The disagreement, same area.** Bounding box (6,961.6 km²), share of land excluding
  water, 2020: MODIS MCD12Q1 forest 7.22%, cropland 35.02%, urban 2.96%; land-cover-ca v2
  31.587%, 48.767%, 14.329%. Over 2017–2025 in the box the model is 22.0–25.1 points above
  MODIS on forest, 12.1–18.0 on cropland, 11.2–11.7 on urban. Source:
  `landcover/data/results/modis_agreement.csv` / `.json` (land-cover track,
  `landcover/scripts/modis_agreement.py`; git-ignored, rebuilt by that script).
- **Area difference (corrected after review A1).** The MODIS series in the table covers the
  bounding box; the land-cover-ca rows in `data/external/land_cover_ca.csv` (used by the
  analysis) cover the six watershed units (3,382.6 km², `data/geo/study_regions.json`),
  2020: 29.738%, 49.553%, 14.368%. The first version of this record said "same box" and
  compared the box with the units; that was wrong. The choice of source stands: the gap is
  as large in the same box.
- **Why (checked, not assumed).** MODIS 2020 class breakdown in the box, from the MCD12Q1
  file: woody savanna 16.9%, cropland/natural-vegetation mosaic 16.3%, savanna 15.2%
  (48.4% together, counted as neither forest nor cropland); mixed forest 4.1%, deciduous
  broadleaf 3.2%, urban 3.0%. MCD12 User Guide V6.1 Table 3 (p. 9): forest needs > 60% tree
  cover, woody savanna 30–60%, urban ≥ 30% impervious, mosaic 40–60% cultivation, all within
  a 500 m pixel. Simcoe's mixed farm, woodlot and small-town landscape falls between classes.
- **What the analysis uses.** land-cover-ca (30 m) for land-cover levels, selected by tier
  "Modeled (Machine learning)" (`V.ANALYSIS_TIER`); more than one such source stops the
  analysis. Its record is 9 years (2017–2025), under the 10-season rule, so it gets no trend
  verdict and its correlations report "too few shared years".
- **MODIS land cover** is excluded from trend verdicts and correlations
  (`V.EXCLUDED_FROM_ANALYSIS`): its user guide (p. 3) warns against reading change from its
  yearly labels, and the class check above agrees. It stays on the page as "comparison
  only". MODIS NDVI (MOD13A3) is not affected.
- **What land-cover-ca is.** Prithvi-EO-2.0-300M (Apache-2.0; model card: "jointly developed
  by IBM, NASA, and Jülich Supercomputing Centre", pretrained on NASA HLS V2, 4.2M samples)
  fine-tuned by this project's land-cover track on Sentinel-2 summer composites against the
  2020 Land Cover of Canada map (86.9% accurate by its own assessment, per
  `landcover/REPORT.md`). Prithvi alone does not label land cover.
- Effect: significant trend series fell from 14 to 11 (the three MODIS land-cover trends).
  The table is now built without `--skip-external` (7,396 rows).

## Accuracy figures used

- MODIS LST: 1 K (= 1 °C for differences). MOD11 User Guide V6.1, p. 21, QC table:
  "average LST error <= 1K". We keep only pixels with that flag, so the bound applies.
  The MOD11 ATBD (p. 4) mentions a possible 0.5 K for calm lake water in dry air; we use
  the documented flag, not that aim.
- MERRA-2, IMERG, NDVI: no single accuracy figure was found in the documentation read,
  so the "not distinguishable from sensor accuracy" test is not applied to them.
  MERRA-2 README read: no usable figure. IMERG documentation not read. Accuracy left empty;
  the sensor-accuracy test is not applied to these variables.
- MCD12Q1 land cover: the User Guide V6.1 (p. 3) warns against using the product to
  detect land-cover change, because label uncertainty in any one year is too high.
  The page carries this warning on every land-cover share.

## Region

- Lake Simcoe sample point 44.42139, -79.42556; surface 722 km² (OHN outline 722.4 km²);
  model catchment 2,990 km² from the lake twin's catchment areas file, which records it
  as a stored lake record with no registry source. No source is on record; the figure is
  shown on the page only as the lake twin's value, labelled that way, and is not used in any
  calculation.
- Water pixels: `scripts/prepare_geometry.py` keeps MODIS 1 km cells lying wholly inside
  the outline after a 500 m shore margin: **502 cells** (642 with no margin).
- Catchment box: around the six watershed units the lake twin assigns to Simcoe
  (3,382.6 km², matching the lake twin's figure). Box W -79.790, S 43.942, E -78.811,
  N 44.745 = 6,961.6 km², about twice the unit area.
- **Big Rideau Lake: not used.** Same script: 0 MODIS 1 km cells fit wholly inside its
  outline (45.9 km²); the widest open water is 1.45 km. Every pixel would mix shore and
  land, so a lake temperature would not be clean. Owner decides whether to pick another
  contrast lake.

## Method

- Open-water season: May–October mean per year, kept only when all six months exist.
- Per series: direction, Sen's slope per decade, Mann-Kendall p (tie-corrected, two-sided),
  95% CI (Gilbert 1987). Significant when p < 0.05. Minimum 10 seasons.
- Correlation of lake temperature with each driver on season means, raw and after removing
  each series' least-squares line. Wording: "associated with", plus the caveat that one
  lake cannot establish cause.
- Orbit-drift cross-check: flag when the MODIS daytime pass time trends significantly, or
  when lake-day-minus-air trends significantly over the last 10 seasons.

## Order of work (two days)

Day 1
1. Owner puts Earthdata credentials in `~/.netrc` (never in chat).
2. `scripts/submit_appeears.py`: submit both AppEEARS requests first (they queue).
3. `scripts/fetch_gesdisc.py`: MERRA-2 (≈ 3 × 312 monthly files) and IMERG while AppEEARS runs.
4. `scripts/build_table.py` and `scripts/run_analysis.py` on the MERRA-2 and IMERG rows; check the page.

Day 2
5. `scripts/fetch_appeears.py`, then `scripts/process_appeears.py`; check matched water
   cells and kept composites in `data/processed/appeears_processing_report.json`.
6. Rebuild the table and analysis; the demos switch to real Simcoe results automatically.
7. Giovanni cross-check for one variable; browser check; peer review; write-up.

## Route

Coded by Claude Code at the owner's direct request (2026-11-14). Review by Antigravity or
another reviewer the owner names; the author does not review its own change.
