# Review: land-cover-ca track

Review date: 2026-11-14  
Range reviewed: `46c5e81..16313b7`, limited to `landcover/`, `data/external/land_cover_ca.csv` and the track's
`.gitignore` entry. The already-trained model and its weights were treated as immutable; no retraining was attempted or
recommended.

## Verdict: CHANGES REQUESTED

The spatial split, common v1/v2 test windows, train-only normalization statistics, reflectance offset guard, IoU
implementation, baseline validation selection, land-share denominator, registry-name guard and published claims were
checked. The retained outputs support the reported values. Three non-training code/metadata issues remain:

1. **AOT metadata is not fully validated** (`lc/composite.py:89-96`). The filter accepts Python booleans, `NaN` and
   infinite values as scales, uses only the first entry when `raster:bands` has multiple entries, and ignores a listed
   offset and nodata value. This is weaker than the documented fail-closed contract. Validate exactly one band and a
   finite, positive, non-boolean scale; validate/apply a finite offset (normally zero); and honor nodata before comparing
   with `max_aot`.
2. **Share generation can write invalid values instead of failing closed** (`scripts/build_shares.py:58-66`). An empty
   area, no predicted pixels, or no predicted land produces division by zero/`NaN`; class values outside
   `0..len(names)-1` and `255` are silently included in the denominator but dropped from class numerators. Reject an
   invalid prediction domain and fail with a clear error when any required denominator is zero.
3. **The selected artifact is v2 but the shared config says v1** (`config.yaml:4-6`). That field was also used in the
   MLflow run tag (`colab/train_vm.py:217-220`), so changing historical evidence in place would be misleading. Clarify
   whether it is a configuration-schema version or a model version; for future packaging, derive artifact identity from
   the frozen run/model metadata rather than this stale value.

None of these findings requires retraining or changing the selected weights or committed LakePulse values.

## Checks and adversarial probes

- `cd landcover && .venv/bin/python -m pytest -q` — 18 passed.
- `.venv/bin/python -m pytest -q tests` — 64 passed, one existing binary-compatibility warning.
- Confirmed the 11 v1 and v2 test windows have identical projected bounds on the same absolute chip lattice.
- Confirmed all 2,031 files represented in the v2 chip archives match the retained manifest SHA-256 values.
- Confirmed v2 manifest statistics say `train chips, labelled pixels only` and record 636 train, 30 validation and 11
  test chips.
- Traced selected v2, plain v2, v1, baseline, split, share, AOT and MODIS-agreement claims to the retained outputs in
  `evidence/`.
- Malformed AOT metadata probe demonstrated that a boolean scale and nonzero offset are accepted.
- All-water share probe returned `NaN` for every land class instead of rejecting the input.
- Original commit scope check found no track change outside `landcover/`, `data/external/land_cover_ca.csv` and
  `.gitignore`.

## Documentation added during review

- `README.md` now states that v2 is frozen, records its public artifact and checksum, distinguishes inference from
  training, and documents the model/input/share contract and limitations.
- `evidence/` retains the small machine-readable outputs needed to audit the report without Colab or retraining.
- Attribution placeholders were resolved, and `REPORT.md` now labels possible MODIS explanations as untested.
