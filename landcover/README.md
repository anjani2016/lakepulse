# land-cover-ca in LakePulse

This directory records the completed model-development track for LakePulse. The selected model is
**land-cover-ca v2**, the class-weighted `ft-a100-v2cw` run. It is frozen: LakePulse consumes its
published weights and committed yearly shares; retraining is not part of the project workflow.

## What LakePulse uses

- `../data/external/land_cover_ca.csv` contains the 27 values used by LakePulse: forest, cropland and
  built-up (`urban_share`) shares for 2017–2025.
- Values are percentages of predicted **land** pixels in the six Lake Simcoe watershed polygons.
  Predicted water and pixels without a clear observation are excluded from the denominator.
- The rows are model estimates, not measurements or field-checked ground truth. The model learned to
  reproduce a published 2020 Land Cover of Canada map.
- These nine annual values are used as land-cover levels. LakePulse does not infer a land-cover trend
  from them because its minimum series length is ten years.

The model shares and the MODIS MCD12Q1 shares are not interchangeable. The model rows cover the six
watershed polygons (about 3,381.5 km²); LakePulse's MODIS rows cover a larger bounding box. The model
also disagrees substantially with MODIS even when both are calculated over the same box. See
[`REPORT.md`](REPORT.md#agreement-with-modis-same-years-same-box-same-denominator).

## Frozen artifact

- Public model: [`anjanid/land-cover-ca`](https://huggingface.co/anjanid/land-cover-ca)
- Selected weights: `land_cover_ca_v2_fp16.safetensors`
- SHA-256: `9f2b3656a0fd5d97b0d763e8182793e36a069c0d54c39e7ed5d980d9fc857135`
- Base model: `ibm-nasa-geospatial/Prithvi-EO-2.0-300M`, revision
  `9eb1b1102806593963daa333bcc491b1c6f8562f`
- Output classes, in index order: `forest`, `cropland`, `built_up`, `water`, `wetland`, `other`
- Licence: Apache-2.0 for the model; input data retain the terms listed in
  [`hf/land-cover-ca/NOTICE`](hf/land-cover-ca/NOTICE)

The Hugging Face repository also holds the exact normalization statistics, TerraTorch configuration,
evaluation JSON, checksums and two comparison-only ablations. Use the selected v2 weights above for
LakePulse; the ablations are not deployment candidates.

## Inference contract

The model expects a 30 m Sentinel-2 L2A summer median composite with bands in this exact order:
`BLUE`, `GREEN`, `RED`, `NIR_NARROW` (B8A), `SWIR_1`, `SWIR_2`. Apply the Earth Search scale and offset
metadata once, mask cloud, shadow and snow with SCL, replace no-data reflectance with zero, and then
normalize with the selected model's `norm_stats.json`.

The production yearly maps additionally discard observations whose L2A aerosol optical thickness is
above 0.4 before taking the median. The model itself was trained on the earlier unfiltered composites;
the AOT rule is an input-quality filter and did not change the weights. Only use cloud-masked summer
composites: the retained winter and unmasked-cloud probes fail badly.

`colab/infer_vm.py` documents the historical Drive layout used to create the yearly maps. It does not
download the public safetensors file by itself. A new inference deployment must stage the selected
weights, `terratorch_config.yaml` and `norm_stats.json` from the public model repository in the layout
expected by that script, or provide an equivalent loader following the model card. No training command
is required.

## Repository map

- [`REPORT.md`](REPORT.md) — results, claims, limitations and published-artifact record
- [`PLAN.md`](PLAN.md) — historical choices and execution plan
- [`hf/land-cover-ca/README.md`](hf/land-cover-ca/README.md) — committed copy of the public model card
- [`evidence/README.md`](evidence/README.md) — retained machine-readable results behind the report
- `lc/`, `scripts/`, `colab/` — historical preparation, evaluation and inference code
- `tests/lc_checks.py` — land-cover-specific checks; run with
  `cd landcover && .venv/bin/python -m pytest -q`

Large intermediate rasters, chips and run outputs under `landcover/data/` are intentionally ignored. The small final
evaluation, split, normalization, AOT, share and agreement outputs needed to audit the report are retained in
`evidence/`. The large intermediates are not needed to run LakePulse with the committed CSV. The training code remains
for provenance, not as an instruction to train the model again.
