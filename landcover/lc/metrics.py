"""Per-class IoU and mean IoU from a confusion matrix. Pure numpy; used on the Mac and on Colab."""
from __future__ import annotations

from typing import Sequence

import numpy as np


def confusion(truth: np.ndarray, pred: np.ndarray, n_classes: int, ignore: int = -1, mask: np.ndarray | None = None) -> np.ndarray:
    """Rows = truth, columns = prediction, over pixels where truth != ignore (and mask, if given)."""
    keep = truth != ignore
    if mask is not None:
        keep &= mask.astype(bool)
    t, p = truth[keep].astype(np.int64), pred[keep].astype(np.int64)
    if t.size and (t.min() < 0 or t.max() >= n_classes or p.min() < 0 or p.max() >= n_classes):
        raise ValueError("class index out of range")
    return np.bincount(t * n_classes + p, minlength=n_classes * n_classes).reshape(n_classes, n_classes)


def iou(cm: np.ndarray, names: Sequence[str]) -> dict:
    """Per-class IoU (None when the class is absent from both truth and prediction), mean over classes present in the
    truth, pixel accuracy and pixel counts."""
    tp = np.diag(cm).astype(float)
    fp, fn = cm.sum(axis=0) - tp, cm.sum(axis=1) - tp
    denom = tp + fp + fn
    per = {n: (round(float(tp[i] / denom[i]), 4) if denom[i] > 0 else None) for i, n in enumerate(names)}
    present = [i for i in range(len(names)) if cm[i].sum() > 0]
    miou = float(np.mean([tp[i] / denom[i] for i in present])) if present else None
    total = int(cm.sum())
    return {"per_class_iou": per, "mean_iou": None if miou is None else round(miou, 4),
            "pixel_accuracy": round(float(tp.sum() / total), 4) if total else None, "pixels": total,
            "truth_pixels": {n: int(cm[i].sum()) for i, n in enumerate(names)}}
