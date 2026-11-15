# Ablations: for comparison only

These two models are here so the comparison in the main README can be rerun. **Use the model at the top level of this
repository** (`land_cover_ca_v2_fp16.safetensors`), which scores best on the held-out test.

| Folder | What changed | Test block mean IoU | 30 m strip mean IoU | Wetland IoU |
|---|---|---|---|---|
| `v1/` | 2020 imagery only, 13 watershed units, 86 training chips, no class weights | 0.4724 | 0.3558 | 0.0 |
| `v2_no_class_weights/` | Same data as the main model, no class weights | 0.4983 | 0.3860 | 0.0114 |
| (main model) | v2 data with class-weighted loss | 0.5145 | 0.4040 | 0.0846 |

Scores are on the same 11 held-out test chips (`eval.json` in each folder). Each folder has its own
`norm_stats.json`; v1's differs from the others because it was normalised with its own training chips. Load each model
with its own `terratorch_config.yaml`.
