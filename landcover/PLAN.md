# Land-cover track (land-cover-ca): plan and decisions

A separate, discardable track for the 2026 NASA Space Apps entry. If it does not work in time it is dropped; nothing
else in LakePulse depends on it. Output: `data/external/land_cover_ca.csv` (same 7 columns as the main table).

## Purpose

MODIS land cover (500 m) already gives whole-catchment shares. This model's job is the land within **30 m each side**
of the Lake Simcoe shoreline and its streams, where runoff enters the lake.

## Owner decisions (verbatim, 2026-11-14)

- Strip width: "30 m (1 pixel)"
- Training area: "Wider ring (Recommended)" (the test block stays inside the Simcoe catchment)
- MLflow: "add it"
- Unit cap: "keep 200. we can increase if needed"; "200 units"
- GPU: "permission to go ahead with a stronger model that consumes more credits given"
- Laptop: "once i initiate the training here and close my laptp the training should work"
- Drive: "we go with this. i have 5tb gdrive capacity. we had a problem mounting gdrive to colab last time"
- Downloads, 2017 start: "ok with all"

## Data

| Item | Source | Licence | Notes |
|---|---|---|---|
| Labels | 2020 Land Cover of Canada, 30 m (Canada Centre for Remote Sensing) | Open Government Licence - Canada | Read as a window of the cloud-optimised GeoTIFF. A published map (stated 86.9% overall accuracy, 832 samples), **not field-checked ground truth** |
| Shoreline | OHN Waterbody (already in `data/geo/simcoe_on.geojson`) | Open Government Licence - Ontario | |
| Streams | OHN Watercourse, layer 26, features of type "Stream" | Open Government Licence - Ontario | |
| Watershed units | Ontario Watershed Boundaries (already in `data/geo/simcoe_on_owb_units.geojson`) | Open Government Licence - Ontario | |
| Imagery | Sentinel-2 L2A, Earth Search `sentinel-2-l2a` | Copernicus Sentinel data terms [verify exact wording] | Summer (06-15 to 09-15) median composite at 30 m, 6 bands, reflectance as in the fire work |
| Base model | `ibm-nasa-geospatial/Prithvi-EO-2.0-300M` @ `9eb1b11` | Apache-2.0 | Not the BurnScars fine-tune, not `burn-scar-ca` |

Years: 2017-2025. Earth Search returned no summer 2016 items under 20% cloud over the Simcoe box.

## Classes

forest (1, 2, 5, 6), cropland (15), built-up (17), water (18), wetland (14), other (8, 10-13, 16, 19). Map in `config.yaml`.

## Split (by area)

- Region = the 6 Simcoe catchment units + 7 neighbouring units (Ontario Watershed Boundaries).
- **Test block** = Holland River unit + the "Lake Simcoe" unit within 10 km of it (Cook's Bay shores). Needed because
  the "Lake Simcoe" unit holds almost all of the shoreline.
- **Val** = Pefferlaw River unit.
- Chips are 224 x 224 px (6.72 km) windows of one region grid. Non-test chips within one chip width of a test chip, and
  train chips within one chip width of a val chip, are dropped.
- Figures: `landcover/data/geometry/split_summary.json`, map `split_map.png` (rebuilt by `scripts/build_geometry.py`).

## Metrics

Per-class IoU and mean IoU on the test block, and again on test pixels inside the strip. Baselines: most common class;
per-pixel gradient boosting (scikit-learn `HistGradientBoostingClassifier`) on the same six bands. If the fine-tune
does not beat gradient boosting, the report says so. MODIS agreement: yearly catchment shares vs MCD12Q1 shares from the
main LakePulse table; differences reported per class, not tuned away. Probes: cloudy chip, catchment-edge chip, winter
scene, all-water chip, half water / half shore chip.

## Compute

Google Colab, cap **200 units** for this track. One ledger row per session in `landcover/colab_ledger.md`, balance read
with `colab usage` before and after. Data and checkpoints live on Google Drive (`My Drive/lakepulse-landcover`), so a
run can continue after the laptop closes and resume from the last checkpoint if Colab ends the runtime. MLflow:
experiment `lakepulse-land-cover` on the team server; metrics from Colab, weights registered from the Mac as
`land-cover-ca` (Colab cannot upload artifacts to that server yet). Credentials are removed from the VM before stop.

## Order of work

1. Geometry, labels, streams (done when `split_summary.json` exists).
2. 2020 composite and training chips, staged to Drive. **Day-1 cut-off: if chips are not staged by end of 2026-11-14, stop and report.**
3. Two-session Colab test; report before relying on it.
4. Baselines (Mac), fine-tune (Colab), test, probes.
5. Composites 2017-2025, yearly inference, shares table, MODIS agreement, report.

## v1 result (ft-l4-v1) and v2

- v1: 2020 composite, 13 units, 86 training chips, 60 epochs on an L4. Test block mean IoU 0.4724 vs gradient boosting
  0.4689; strip 0.3558 vs 0.3585. Does not clearly beat the simple classifier. Registered as `land-cover-ca` version 1
  (owner: "add relevant models to the model registry as well"), with tags saying so.
- v2 (owner: "Years and wider area"; "use a powerful gpu than the one being used"):
  - Training area + 22 Ontario Watershed Boundaries units within 15 km (12,529.4 km² region, 222 training chips per year).
    Inference and shares keep the 13-unit grid. Both grids sit on the same absolute 6.72 km chip lattice, so the 11 test
    chip windows are identical to v1.
  - Training and val chips from the 2019, 2020 and 2021 summer composites against the 2020 labels (the label map was made
    from 2019-2021 imagery); real change between those years becomes label noise. Test chips stay 2020-only.
  - Two runs at once on A100s: plain, and with class weights (inverse square root of class frequency) for wetland.
  - All models (v1, v2 runs, both baselines) are scored on the same v2 test chips.

## Outcome and LakePulse hand-off (2026-11-14 evening)

- Best model: v2 class-weighted (`ft-a100-v2cw`), registered `land-cover-ca` version 2; beats gradient boosting on the
  same test chips. Full results in `REPORT.md`.
- Hand-off contract (owner, pasted 2026-11-14): `data/external/land_cover_ca.csv` holds only the catchment forest,
  cropland and built-up shares as `forest_share`, `cropland_share`, `urban_share`, % of land (water excluded), dated
  1 January, tier "Modeled (Machine learning)" (this replaces the brief's "Modeled (Simulation)", which LakePulse
  reserves for MERRA-2). Other classes and all strip shares stay in `landcover/` pending an owner decision.
- "Catchment" here is the six-unit polygon; LakePulse's MODIS shares use the bounding box. Owner decides whether to align.
- Tests: `cd landcover && .venv/bin/python -m pytest -q` (file `tests/lc_checks.py`, so LakePulse's bare `pytest`
  does not collect it).
- Not run end to end: `colab/launch_train.sh` (sessions were started step by step with the same commands).
- Open: 2025 haze (aerosol filter), wetland quality, `[verify]` items in `REPORT.md`, Colab runtimes end when the
  laptop disconnects.

## Route

Coded by Claude Code at the owner's direct request (2026-11-14). Review by Antigravity or another reviewer the owner
names; the author does not review its own change.
