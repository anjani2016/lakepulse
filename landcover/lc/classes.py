"""Merge the 2020 Land Cover of Canada classes into the six-class set."""
from __future__ import annotations

from typing import Any, Mapping

import numpy as np


class ClassError(ValueError):
    pass


def lookup(cfg: Mapping[str, Any]) -> np.ndarray:
    """256-entry table: source pixel value -> merged class index, ignore_index for anything unmapped (0 = no data)."""
    names = list(cfg["classes"]["names"])
    ignore = int(cfg["classes"]["ignore_index"])
    table = np.full(256, ignore, dtype=np.int16)
    for value, name in cfg["classes"]["from_lcc2020"].items():
        value = int(value)
        if not 0 < value < 256:
            raise ClassError(f"source value {value} out of range")
        if name not in names:
            raise ClassError(f"source value {value} maps to unknown class {name!r}")
        table[value] = names.index(name)
    return table


def merge(raw: np.ndarray, table: np.ndarray) -> np.ndarray:
    if raw.dtype != np.uint8:
        raise ClassError(f"label raster must be uint8, got {raw.dtype}")
    return table[raw]
