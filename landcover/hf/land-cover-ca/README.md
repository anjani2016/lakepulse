---
license: apache-2.0
library_name: terratorch
base_model: ibm-nasa-geospatial/Prithvi-EO-2.0-300M
pipeline_tag: image-segmentation
tags:
  - earth-observation
  - remote-sensing
  - sentinel-2
  - land-cover
  - semantic-segmentation
  - canada
  - lake-simcoe
  - prithvi
---

# land-cover-ca v2: land cover around Lake Simcoe, Ontario, at 30 m

Labels each 30 m pixel of a Sentinel-2 L2A **summer median composite** as forest, cropland, built-up, water, wetland or
other. Fine-tuned from [Prithvi-EO-2.0-300M](https://huggingface.co/ibm-nasa-geospatial/Prithvi-EO-2.0-300M)
(revision `9eb1b1102806593963daa333bcc491b1c6f8562f`) for LakePulse, an entry to the 2026 NASA Space Apps Challenge.
Its job is the land within 30 m of the Lake Simcoe shoreline and its streams, where runoff enters the lake, which
500 m MODIS land cover cannot resolve.

**A model estimate, not a measurement.** The training labels are the 2020 Land Cover of Canada, a published map
(stated overall accuracy 86.9%, 832 samples), not field-checked ground truth. Every score below measures agreement
with that map.

Made by Centauri Research (Alpha Centauri Ventures Inc.).

## Held-out test (split by area, never by pixel)

The test block is the Holland River watershed plus the Lake Simcoe shore within 10 km of it (541.3 km², 43.2 km of
shoreline, 11 chips of 224 x 224 pixels, 474,703 labelled pixels, 44,745 of them in the 30 m strip). Chips within one
chip width (6.72 km) of a test chip were kept out of training and validation. All models below were scored on the same
chips. Mean IoU over the six classes.

| Model | Whole test block | 30 m shoreline and stream strip |
|---|---|---|
| **land-cover-ca v2 (this model; class-weighted loss)** | **0.5145** | **0.4040** |
| v2 without class weights | 0.4983 | 0.3860 |
| Gradient boosting, per pixel, same six bands and training data | 0.4794 | 0.3684 |
| v1 (2020 imagery only, 86 training chips) | 0.4724 | 0.3558 |
| Always the most common class (forest) | 0.0293 | 0.0384 |

Per-class IoU, whole test block: forest 0.655, cropland 0.801, built-up 0.5727, water 0.9044, **wetland 0.0846**,
other 0.069. Wetland and "other" are poorly mapped.

Adversarial probes (one chip each, mean IoU): cloudy scene without cloud masking 0.2117, winter scene 0.0484, chip at
the catchment edge 0.3211, mostly water (96.5%) 0.386, half water and half shore 0.4875. **Use cloud-masked summer
composites only.**

## Training

- **Data:** 636 training chips and 30 validation chips from the 2019, 2020 and 2021 summer composites, all against the
  2020 labels (the label map was made from 2019 to 2021 imagery). Area: 13 watershed units around Lake Simcoe plus 22
  neighbouring units within 15 km (12,529.4 km²), Ontario Watershed Boundaries. Validation: Pefferlaw River unit.
- **Loss:** cross-entropy weighted by the inverse square root of each class's share of training pixels, scaled to a
  mean of 1: forest 0.3479, cropland 0.4308, built-up 0.8362, water 0.6651, wetland 2.5612, other 1.1588.
- **Setup:** TerraTorch 1.2.14, UNet decoder on backbone layers 5, 11, 17 and 23, AdamW at 1e-4, batch 8,
  bf16 mixed precision, Google Colab A100. Training ran in two attempts: Colab ended the first runtime at epoch 24,
  and training resumed from the epoch-19 best weights with a fresh optimizer. These weights are the best by validation
  loss in the second attempt.

## Input

Six Sentinel-2 L2A bands in this order: BLUE, GREEN, RED, NIR_NARROW (B8A), SWIR_1, SWIR_2, as surface reflectance
(digital number x scale + offset, with Earth Search's offset left out where it is already applied), resampled to 30 m.
No-data reflectance is set to 0, then each band is normalised with `norm_stats.json` (means and standard deviations of
the training chips). Output classes in index order: forest, cropland, built_up, water, wetland, other.

## Loading

`land_cover_ca_v2_fp16.safetensors` is the fp16 state dict of a TerraTorch `SemanticSegmentationTask`. Build the task
from `terratorch_config.yaml` with `backbone_pretrained: false` (and without `backbone_ckpt_path`), then load the state
dict with `strict=True` after converting tensors to float32.

## Limits

- Agreement is with a 2020 published map, not with the ground.
- Trained and tested only around Lake Simcoe, southern Ontario. Scores elsewhere are unknown.
- Hazy composites bias results: the 2025 summer composite (likely wildfire smoke) lowers forest and raises built-up.
- Against MODIS MCD12Q1 land cover for 2017 to 2025, this model's forest, cropland and urban shares are on average
  23.42, 15.16 and 11.59 percentage points higher. It follows the 2020 federal map it learned from; MODIS is far below
  that map too.

## Files

| File | What |
|---|---|
| `land_cover_ca_v2_fp16.safetensors` | Weights (fp16) |
| `terratorch_config.yaml` | Model and data module settings used in training |
| `norm_stats.json` | Band means and standard deviations, class names, ignore index |
| `config.yaml` | The track's full configuration (data sources, classes, split) |
| `eval.json` | Test and probe scores of this model |
| `NOTICE`, `LICENSE`, `SHA256SUMS` | Attribution, licence, checksums |
| `ablations/` | The two comparison models from the table above, for checking the comparison only |

## Ablations (for comparison, not for use)

`ablations/` holds the two other models in the test table, so the comparison can be rerun:

- `ablations/v1/`: 2020 imagery only, 13 watershed units, 86 training chips, no class weights. Did not beat gradient
  boosting (0.4724 vs 0.4689 on v1's own baseline data; 0.4724 vs 0.4794 here). Normalised with its own
  `norm_stats.json`, which differs from this model's.
- `ablations/v2_no_class_weights/`: the same data as this model, without class weights. Wetland IoU 0.0114 against
  this model's 0.0846: the class weights account for most of the wetland gain.

Each folder has its weights, `terratorch_config.yaml`, `norm_stats.json` and `eval.json`. Load each with its own
config: this model's state dict holds one more tensor (its loss weights) than the two ablations.
In the project's MLflow registry these are `land-cover-ca` versions 1 (v1), 2 (this model) and 3 (v2 without class
weights).
