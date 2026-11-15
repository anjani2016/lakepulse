"""Two baselines on the staged chips, scored on the test chips (whole test block, and test pixels inside the strip).

  most_common - always predict the most common class among TRAIN labelled pixels
  gbm         - scikit-learn HistGradientBoostingClassifier on the six band values per pixel, trained on a random
                sample of TRAIN labelled pixels (sample size and seed below), early stopping on VAL pixels

Writes landcover/data/results/baselines.json.

Run:  landcover/.venv/bin/python landcover/scripts/baselines.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import rasterio

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lc import config, metrics  # noqa: E402

SAMPLE = 400_000  # gate choice: training pixels for the GBM
SEED = 42


def load(split: str, v2: bool = False):
    root = config.dirs(v2)["chips"] / split
    X, y, s = [], [], []
    for img in sorted(root.glob("*_img.tif")):
        stem = img.name[: -len("_img.tif")]
        with rasterio.open(img) as a, rasterio.open(root / f"{stem}_label.tif") as b, rasterio.open(root / f"{stem}_strip.tif") as c:
            X.append(a.read().reshape(a.count, -1).T)
            y.append(b.read(1).ravel())
            s.append(c.read(1).ravel())
    return np.concatenate(X), np.concatenate(y), np.concatenate(s)


def score(y, pred, strip, names):
    return {"test_block": metrics.iou(metrics.confusion(y, pred, len(names)), names),
            "test_strip": metrics.iou(metrics.confusion(y, pred, len(names), mask=strip == 1), names)}


def main() -> None:
    from sklearn.ensemble import HistGradientBoostingClassifier

    import argparse
    ap = argparse.ArgumentParser(); ap.add_argument("--v2", action="store_true"); args = ap.parse_args()
    cfg = config.load()
    names = cfg["classes"]["names"]
    Xtr, ytr, _ = load("train", args.v2)
    Xva, yva, _ = load("val", args.v2)
    Xte, yte, ste = load("test", args.v2)
    keep = ytr >= 0
    Xtr, ytr = Xtr[keep], ytr[keep]
    common = int(np.bincount(ytr, minlength=len(names)).argmax())
    out = {"most_common": {"class": names[common], **score(yte, np.full_like(yte, common), ste, names)}}

    rng = np.random.default_rng(SEED)
    idx = rng.choice(len(ytr), size=min(SAMPLE, len(ytr)), replace=False)
    kv = yva >= 0
    t0 = time.time()
    # Number of boosting rounds chosen on the VAL block (an area split), not on a random split of training pixels.
    gbm = HistGradientBoostingClassifier(max_iter=400, learning_rate=0.1, early_stopping=False, random_state=SEED)
    gbm.fit(Xtr[idx], ytr[idx])
    va_scores = [float((p == yva[kv]).mean()) for p in gbm.staged_predict(Xva[kv])]
    best_iter = int(np.argmax(va_scores)) + 1
    gbm = HistGradientBoostingClassifier(max_iter=best_iter, learning_rate=0.1, early_stopping=False, random_state=SEED)
    gbm.fit(Xtr[idx], ytr[idx])
    pred = gbm.predict(Xte)
    out["gbm"] = {"train_pixels_sampled": int(len(idx)), "seed": SEED, "iterations_chosen_on_val": best_iter,
                  "val_pixel_accuracy_at_best": round(max(va_scores), 4), "fit_seconds": round(time.time() - t0), **score(yte, pred, ste, names)}
    out["test_pixels"] = int((yte >= 0).sum())
    out["test_strip_pixels"] = int(((yte >= 0) & (ste == 1)).sum())
    d = config.DATA / "results"
    d.mkdir(parents=True, exist_ok=True)
    (d / ("baselines_v2.json" if args.v2 else "baselines.json")).write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
