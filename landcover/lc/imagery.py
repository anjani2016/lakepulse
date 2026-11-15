"""Sentinel-2 L2A reflectance helpers.

band_scaling, to_reflectance and invalid_mask are copied from cr-geo-models ml/fire/imagery.py (commit 16e58b5) so the
band set and reflectance handling match the fire work exactly. In particular: when Earth Search marks an item
`earthsearch:boa_offset_applied: true`, the -0.1 offset it still lists is NOT applied again.
"""
from __future__ import annotations

from typing import Any, Mapping, Optional, Sequence

import numpy as np


class ImageryError(ValueError):
    """A STAC item or array can't be turned into model input safely."""


def band_scaling(item: Mapping[str, Any], asset: str) -> tuple[float, float, Optional[float]]:
    """(scale, offset, nodata) for one asset, from the item's raster:bands. Fails closed if scale or offset is absent."""
    assets = item.get("assets") or {}
    if asset not in assets:
        raise ImageryError(f"{item.get('id')}: asset {asset!r} missing")
    bands = assets[asset].get("raster:bands") or []
    if len(bands) != 1:
        raise ImageryError(f"{item.get('id')}: asset {asset!r} needs exactly one raster:bands entry")
    band = bands[0]
    scale, offset = band.get("scale"), band.get("offset")
    for name, value in (("scale", scale), ("offset", offset)):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not np.isfinite(value):
            raise ImageryError(f"{item.get('id')}: asset {asset!r} has no usable {name} ({value!r})")
    if scale <= 0:
        raise ImageryError(f"{item.get('id')}: asset {asset!r} scale must be positive")
    applied = (item.get("properties") or {}).get("earthsearch:boa_offset_applied")
    if not (applied is True or applied is False or applied is None):  # identity: 1 == True must not pass
        raise ImageryError(f"{item.get('id')}: earthsearch:boa_offset_applied must be true or false, not {applied!r}")
    if applied is True:
        offset = 0.0
    elif applied is None and offset != 0:
        raise ImageryError(f"{item.get('id')}: offset {offset} listed but earthsearch:boa_offset_applied is missing; ambiguous")
    nodata = band.get("nodata")
    return float(scale), float(offset), (None if nodata is None else float(nodata))


def to_reflectance(dn: np.ndarray, scale: float, offset: float, nodata: Optional[float]) -> np.ndarray:
    """DN x scale + offset as float32; nodata pixels become NaN."""
    out = dn.astype(np.float32) * np.float32(scale) + np.float32(offset)
    if nodata is not None:
        out[dn == nodata] = np.nan
    return out


def invalid_mask(scl: np.ndarray, invalid_classes: Sequence[int], bands: np.ndarray) -> np.ndarray:
    """True where the scene classification is an invalid class or any band is NaN."""
    if bands.ndim != 3 or bands.shape[1:] != scl.shape:
        raise ImageryError(f"bands {bands.shape} and SCL {scl.shape} don't line up")
    return np.isin(scl, list(invalid_classes)) | np.isnan(bands).any(axis=0)
