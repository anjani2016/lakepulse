# Retained land-cover evidence

These are the small, final machine-readable outputs behind `../REPORT.md`. They were copied unchanged from the
git-ignored `landcover/data/` workspace on 2026-11-14 so the completed, frozen model can be reviewed without rerunning
training or depending on the original Colab/Drive workspace.

| File | Produced by / purpose |
|---|---|
| `eval_v2_selected.json` | `eval_vm.py`; selected class-weighted v2 test and probe scores |
| `eval_v2_plain.json` | `eval_vm.py`; plain v2 comparison scores |
| `eval_v1_own_test.json` | `eval_vm.py`; v1 on its original test package |
| `eval_v1_on_v2_test.json` | `eval_vm.py`; v1 on the common v2 test windows |
| `baselines_v1.json`, `baselines_v2.json` | `baselines.py`; most-common and gradient-boosting comparisons |
| `split_summary_v2.json` | `build_geometry.py --v2`; area and split counts |
| `chips_v2_manifest.json` | `stage_chips.py --v2`; train-only normalization statistics, counts and file hashes |
| `aot_survey.json` | retained AOT survey behind the smoke-filter decision |
| `infer_summary_aot.json` | `infer_vm.py`; final AOT-filtered yearly inference summary |
| `shares_all.csv`, `shares_coverage.json` | `build_shares.py`; all areas/classes and coverage checks |
| `modis_agreement.csv`, `modis_agreement.json` | `modis_agreement.py`; same-box comparison with MODIS |

The large rasters, chip archives, maps, checkpoints and run logs remain ignored. Model weights and their checksums are
published at `anjanid/land-cover-ca`; the selected weights' SHA-256 is recorded in `../README.md` and `../REPORT.md`.
