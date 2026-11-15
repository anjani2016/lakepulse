# land-cover-ca: land cover around Lake Simcoe from a fine-tuned Prithvi-EO-2.0 model

Short report, 2026-11-14. A separate, discardable track of the LakePulse entry for the 2026 NASA Space Apps Challenge.
Every number below comes from a script in `landcover/scripts/` or `landcover/colab/` run on 2026-11-14; the script is
named next to each table. Result files are in `landcover/data/results/` (git-ignored, rebuilt by the scripts).

## Why

MODIS land cover (500 m) already gives whole-catchment shares in LakePulse. This model maps land cover at 30 m so the
**strip within 30 m of the Lake Simcoe shoreline and its streams**, where runoff enters the lake, can be measured.

## Data

| Item | Source | Licence |
|---|---|---|
| Labels | 2020 Land Cover of Canada, 30 m (Canada Centre for Remote Sensing), merged to forest, cropland, built-up, water, wetland, other | Open Government Licence - Canada |
| Imagery | Sentinel-2 L2A from Earth Search, summer (15 June - 15 September) median composites at 30 m, 6 bands, clouds/shadow/snow masked with the scene classification | Copernicus Sentinel data [verify: exact attribution wording] |
| Shoreline, streams | Ontario Hydro Network waterbody and watercourse (36,697 stream features fetched; "Stream" type kept: 2,914.1 km in the catchment) | Open Government Licence - Ontario |
| Watershed units | Ontario Watershed Boundaries, quaternary | Open Government Licence - Ontario |
| Base model | `ibm-nasa-geospatial/Prithvi-EO-2.0-300M` at revision `9eb1b11…` (not the BurnScars fine-tune) | Apache-2.0 |

**The labels are a published map (stated overall accuracy 86.9% from 832 samples), not field-checked ground truth.**
Every score below measures agreement with that map.

Composites (`build_composite.py`): every year 2017-2025 covers at least 99.88% of the 13-unit region with a clear
observation, no scene failed to read; the median pixel has 2-5 clear observations. Earth Search returned no summer 2016
scenes under 20% cloud, so the series starts in 2017.

## Split (by area, never by pixel)

`build_geometry.py --v2`:
- **Test block:** Holland River unit plus the Lake Simcoe shore unit within 10 km of it (Cook's Bay): 541.3 km², 43.2 km
  of shoreline, 11 chips of 224 x 224 px (474,703 labelled pixels; 44,745 of them in the 30 m strip).
- **Validation:** Pefferlaw River unit (10 chip windows).
- **Training:** the rest of the 13-unit region plus 22 neighbouring watershed units within 15 km (12,529.4 km² in all).
- Any training or validation chip within one chip width (6.72 km) of a test chip is dropped, and any training chip within
  one chip width of a validation chip, so no neighbouring chips sit on both sides.
- v2 training and validation chips come from the 2019, 2020 and 2021 composites, all against the 2020 labels (the map
  was made from 2019-2021 imagery): 636 training chips, 30 validation (`stage_chips.py --v2`). Real change between those
  years becomes label noise. Test chips are 2020 only.

## Results on the held-out test block

All models scored on the same 11 test chips (`eval_vm.py` for the fine-tunes, `baselines.py --v2` for the baselines).
Mean IoU over the six classes.

| Model | Test block mean IoU | Test pixels in the 30 m strip, mean IoU |
|---|---|---|
| **Fine-tune v2, class-weighted** (`ft-a100-v2cw`, registered `land-cover-ca` v2) | **0.5145** | **0.4040** |
| Fine-tune v2, plain (`ft-a100-v2`, v3) | 0.4983 | 0.3860 |
| Gradient boosting, per pixel, 6 bands, v2 training data | 0.4794 | 0.3684 |
| Fine-tune v1, 2020 only, 13 units (`ft-l4-v1`, v1) | 0.4724 | 0.3558 |
| Always the most common class (forest) | 0.0293 | 0.0384 |

- **The fine-tune beats the simple classifier only in v2.** v1 (86 training chips) did not: 0.4724 against gradient
  boosting's 0.4689 on its own training data, and 0.3558 against 0.3585 in the strip. More area, more imagery years and
  class weights made the difference.
- Per-class IoU, v2 class-weighted, test block: forest 0.655, cropland 0.801, built-up 0.5727, water 0.9044,
  **wetland 0.0846**, other 0.069. In the strip: forest 0.5959, cropland 0.7408, built-up 0.4204, water 0.5138,
  wetland 0.0991, other 0.0542. Wetland and "other" stay poor in every model; they are rare (wetland is 0.8% of v2
  training pixels).

### Adversarial probes (one chip each; `build_probes.py`, scored by `eval_vm.py`)

| Probe | v2 class-weighted: mean IoU / pixel accuracy |
|---|---|
| Cloudy scene (91.1% cloud, no masking) | 0.2117 / 0.6898 |
| Winter scene (7 March 2020, no masking) | 0.0484 / 0.2398 |
| Catchment edge (60.2% of the chip inside the region) | 0.3211 / 0.8242 |
| Mostly water (96.5%; no 100% water chip exists outside the training area) | 0.386 / 0.9844 |
| Half water, half shore (48.6% water) | 0.4875 / 0.9111 |

The model must only see summer, cloud-masked composites: a single winter or cloudy scene fails.

## Yearly shares

`build_shares.py --version v2 --run ft-a100-v2cw`, on maps from `infer_vm.py`. Shares are **percent of land pixels**
(water and pixels without a clear observation excluded), the same denominator as LakePulse's MODIS shares.

- **Hand-off to LakePulse** (`data/external/land_cover_ca.csv`, 27 rows): `forest_share`, `cropland_share`,
  `urban_share` (= built-up), 2017-2025, unit "%", tier "Modeled (Machine learning)", source
  "land-cover-ca v2 (fine-tuned Prithvi-EO-2.0-300M, run ft-a100-v2cw; Sentinel-2 L2A summer median)".
  Checked with LakePulse's `schema.read` and `scripts/build_table.py` (no `--skip-external`): 27 rows accepted.
- **Area of the "catchment" shares: the six Lake Simcoe watershed units as polygons (3,381.5 km²), NOT the bounding box
  LakePulse's MODIS shares use** (W -79.790, S 43.942, E -78.811, N 44.745). The owner decides whether to align them;
  the same shares over that box are in `landcover/data/results/shares_all.csv` (`lcml_bbox_*`).
- Kept in `landcover/` only, pending an owner decision: water, wetland and "other" shares, and every 30 m strip share
  (`lcml_strip30m_*`).
- Catchment forest 29.2-31.4% and cropland 48.7-50.7% in 2017-2024. **2025 is an outlier** (forest 26.1%, built-up
  17.3%): the 2025 composite is hazy (forest-pixel blue reflectance 0.087 against 0.024-0.031 in 2019, 2023, 2024),
  likely wildfire smoke [verify: smoke dates over Simcoe, summer 2025], which the cloud mask does not remove. A fix would
  drop high-aerosol pixels (Sentinel-2 L2A AOT layer) and rebuild the composites; not done.

## Agreement with MODIS (same years, same box, same denominator)

`modis_agreement.py`, against LakePulse's MODIS MCD12Q1 rows. Model minus MODIS, 2017-2025, percentage points:

| Variable | Mean | Range | 2020: MODIS / model / 2020 label map |
|---|---|---|---|
| forest_share | +23.42 | +18.98 to +25.11 | 7.22 / 31.587 / 34.735 |
| cropland_share | +15.16 | +12.12 to +18.02 | 35.02 / 48.767 / 48.998 |
| urban_share | +11.59 | +11.13 to +13.28 | 2.96 / 14.329 / 11.363 |

**Large disagreement, reported, not tuned away.** The model stays close to the map it was trained on; MODIS is far
lower on all three classes. Likely reasons, not tested here: MODIS's IGBP scheme puts mixed farm-and-woodlot land into
"woody savanna" and "cropland/natural vegetation mosaic", which count as neither forest nor cropland, and 500 m pixels
miss most built-up land [verify: MODIS class breakdown for the box]. The model runs about 3 points above its own labels
on built-up land. MODIS's own guide warns against reading change from its yearly labels; the same caution applies here.

## Limits

- Labels are a 2020 published map; agreement is with that map, not with the ground.
- Wetland and "other" are poorly mapped (IoU under 0.1).
- Trained and tested only around Lake Simcoe; summer composites only; hazy years (2025) bias the shares.
- The test block is one area (11 chips); scores could differ elsewhere in the catchment.
- v2 runs were each trained in two attempts: Colab ended both runtimes when the laptop disconnected, and training
  resumed from the epoch-19 best weights with a fresh optimizer (`landcover/colab_ledger.md`).

## Compute used

Google Colab, from `colab usage` before and after each session (`landcover/colab_ledger.md`): **20.40 units** of the
200-unit cap (balance 594.03 → 573.63). L4 at 1.94 units/hour; two A100s together at 13.46 units/hour. Two sessions
ran in parallel without connection errors. Model tracking: MLflow experiment `lakepulse-land-cover`; registered model
`land-cover-ca` versions 1-3.

Alpha Centauri Ventures Inc. (Centauri Research)
