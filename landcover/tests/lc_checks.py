"""Unit tests for the land-cover track: class merge, offset handling, split rules, strip."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest
from shapely.geometry import LineString, Point, box

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lc import classes, config, geometry, imagery  # noqa: E402

CFG = config.load()


# --- classes -------------------------------------------------------------------------------------------------------
def test_every_lcc_class_is_mapped_and_nodata_is_ignored():
    t = classes.lookup(CFG)
    names = CFG["classes"]["names"]
    for v in (1, 2, 5, 6, 8, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19):
        assert t[v] >= 0
    assert t[0] == -1 and t[3] == -1 and t[255] == -1  # no data and tropical classes absent from Canada
    assert names[t[14]] == "wetland" and names[t[17]] == "built_up" and names[t[18]] == "water" and names[t[15]] == "cropland"


def test_unknown_class_name_fails_closed():
    bad = {"classes": {**CFG["classes"], "from_lcc2020": {1: "trees"}}}
    with pytest.raises(classes.ClassError):
        classes.lookup(bad)


def test_merge_rejects_non_uint8():
    with pytest.raises(classes.ClassError):
        classes.merge(np.zeros((2, 2), dtype=np.int16), classes.lookup(CFG))


# --- reflectance offset (must match the fire work) -------------------------------------------------------------------
def _item(applied, offset=-0.1):
    return {"id": "x", "properties": {} if applied == "absent" else {"earthsearch:boa_offset_applied": applied},
            "assets": {"red": {"raster:bands": [{"scale": 0.0001, "offset": offset, "nodata": 0}]}}}


def test_offset_not_applied_twice():
    assert imagery.band_scaling(_item(True), "red")[1] == 0.0
    assert imagery.band_scaling(_item(False), "red")[1] == pytest.approx(-0.1)


def test_ambiguous_offset_fails_closed():
    with pytest.raises(imagery.ImageryError):
        imagery.band_scaling(_item("absent"), "red")
    assert imagery.band_scaling(_item("absent", offset=0), "red")[1] == 0.0  # pre-04.00 items list no offset
    with pytest.raises(imagery.ImageryError):
        imagery.band_scaling(_item(1), "red")  # 1 is not True


# --- split -----------------------------------------------------------------------------------------------------------
def _toy():
    g = geometry.Grid("EPSG:32617", 0.0, 100.0, 1.0, 100, 100)  # 10 x 10 chips of 10 px
    chips = geometry.chip_boxes(g, 10)
    blk = {"region": box(0, 0, 100, 100), "test": box(0, 0, 30, 30), "val": box(70, 70, 100, 100)}
    return geometry.assign_split(chips, blk, gap_m=10.0)


def test_no_train_or_val_chip_touches_a_test_chip():
    chips = _toy()
    test = [c["geom"] for c in chips if c["split"] == "test"]
    assert test
    for c in chips:
        if c["split"] in ("train", "val"):
            assert all(c["geom"].distance(t) >= 10.0 for t in test), c["id"]


def test_no_train_chip_touches_a_val_chip():
    chips = _toy()
    val = [c["geom"] for c in chips if c["split"] == "val"]
    assert val
    for c in chips:
        if c["split"] == "train":
            assert all(c["geom"].distance(v) >= 10.0 for v in val), c["id"]


def test_chip_outside_region_is_dropped():
    g = geometry.Grid("EPSG:32617", 0.0, 100.0, 1.0, 100, 100)
    chips = geometry.assign_split(geometry.chip_boxes(g, 10),
                                  {"region": box(0, 0, 50, 100), "test": box(0, 0, 10, 10), "val": box(40, 90, 50, 100)}, 10.0)
    assert all(c["split"] is None for c in chips if c["geom"].centroid.x > 50)


def test_real_split_has_shoreline_in_test_and_no_overlap():
    units = geometry.load_units(CFG)
    blk = geometry.blocks(CFG, units)
    lake = geometry.load_lake(CFG)
    assert blk["test"].intersection(lake.boundary).length > 10_000  # at least 10 km of shoreline held out
    assert blk["test"].intersection(blk["val"]).area < 1.0


def test_missing_unit_fails_closed():
    bad = {**CFG, "region": {**CFG["region"], "ring_units": CFG["region"]["ring_units"] + ["Nowhere Creek"]}}
    with pytest.raises(geometry.GeometryError):
        geometry.load_units(bad)


# --- strip -----------------------------------------------------------------------------------------------------------
def test_strip_width_and_catchment_clip():
    lake = Point(0, 0).buffer(1000)
    stream = LineString([(1000, 0), (3000, 0)])
    catch = box(-5000, -5000, 2000, 5000)
    s = geometry.strip(CFG, lake, [stream], catch)
    w = CFG["region"]["strip_m"]
    assert s.contains(Point(1000 + w / 2, 0)) and s.contains(Point(0, 1000 - w / 2))
    assert not s.contains(Point(0, 1000 + 2 * w))
    assert not s.intersects(Point(2500, 0))  # outside the catchment


def test_zero_strip_fails_closed():
    bad = {**CFG, "region": {**CFG["region"], "strip_m": 0}}
    with pytest.raises(geometry.GeometryError):
        geometry.strip(bad, Point(0, 0).buffer(10), [], box(-20, -20, 20, 20))


# --- metrics ---------------------------------------------------------------------------------------------------------
def test_iou_ignores_ignore_and_handles_absent_class():
    from lc import metrics
    names = ["a", "b", "c"]
    t = np.array([0, 0, 1, 1, -1, -1])
    p = np.array([0, 1, 1, 1, 2, 2])
    r = metrics.iou(metrics.confusion(t, p, 3), names)
    assert r["per_class_iou"]["a"] == 0.5 and r["per_class_iou"]["b"] == pytest.approx(2 / 3, abs=1e-4)
    assert r["per_class_iou"]["c"] is None  # predicted only on ignored pixels
    assert r["pixels"] == 4


def test_confusion_rejects_out_of_range_prediction():
    from lc import metrics
    with pytest.raises(ValueError):
        metrics.confusion(np.array([0, 1]), np.array([0, 7]), 3)


# --- shares (LakePulse hand-off: % of land, water and unmapped excluded) --------------------------------------------
def test_shares_exclude_water_and_unmapped_from_denominator():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    from build_shares import shares
    names = CFG["classes"]["names"]
    f, c, w = names.index("forest"), names.index("cropland"), names.index("water")
    pred = np.array([[f, f, c, w], [w, 255, c, c]], dtype=np.uint8)
    s, cov = shares(pred, np.ones(pred.shape, bool), names)
    assert s["forest"] == pytest.approx(40.0) and s["cropland"] == pytest.approx(60.0)  # 2 and 3 of 5 land pixels
    assert s["water_share_of_all"] == pytest.approx(100 * 2 / 7)                       # 2 of 7 predicted pixels
    assert cov == {"area_px": 8, "predicted_px": 7, "land_px": 5, "cover": 0.875}


def test_export_names_match_lakepulse():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    from build_shares import EXPORT, TIER
    assert EXPORT == {"forest": "forest_share", "cropland": "cropland_share", "built_up": "urban_share"}
    assert TIER == "Modeled (Machine learning)"
