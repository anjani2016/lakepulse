"""Cut training chips (label year 2020) from the composite, the label map and the masks; pack them for Drive.

For every chip in data/geometry/chips.json with a split, writes:
  chips/v1/<split>/<id>_img.tif    6 bands float32 reflectance (NaN -> 0, like the fire work)
  chips/v1/<split>/<id>_label.tif  int16 merged class, -1 = ignore (no clear observation, outside region, outside the
                                   test block for test chips)
  chips/v1/<split>/<id>_strip.tif  uint8 1 = inside the 30 m shoreline/stream strip
Chips with less than min_valid_fraction labelled pixels are skipped and logged. Then writes manifest.json (sha256 per
file, band statistics from the TRAIN chips only) and packs each split into tar parts of at most --part-mb.

Run:  landcover/.venv/bin/python landcover/scripts/stage_chips.py [--drive "<My Drive path>/lakepulse-landcover"]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tarfile
from datetime import date
from pathlib import Path

import numpy as np
import rasterio

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lc import classes, config  # noqa: E402

YEAR = 2020


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def pack(files: list[Path], root: Path, dest: Path, stem: str, part_mb: int) -> list[str]:
    parts, cur, size, n = [], [], 0, 0
    for f in files + [None]:
        if f is None or (cur and size + f.stat().st_size > part_mb * 1e6):
            name = f"{stem}_part{n:02d}.tar"
            with tarfile.open(dest / name, "w") as t:
                for c in cur:
                    t.add(c, arcname=str(c.relative_to(root)))
            parts.append(name)
            cur, size, n = [], 0, n + 1
        if f is not None:
            cur.append(f)
            size += f.stat().st_size
    return parts


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--drive", type=Path, help="Folder in the Google Drive sync folder to copy the tar parts into")
    ap.add_argument("--part-mb", type=int, default=250)
    ap.add_argument("--v2", action="store_true", help="wider grid; train/val chips from each v2 train year, test from test_year")
    args = ap.parse_args()
    cfg = config.load()
    D = config.dirs(args.v2)
    tag = "v2" if args.v2 else "v1"
    train_years = cfg["v2"]["train_years"] if args.v2 else [YEAR]
    test_year = cfg["v2"]["test_year"] if args.v2 else YEAR
    chip_px, ignore = cfg["chips"]["chip_px"], cfg["classes"]["ignore_index"]
    names = cfg["classes"]["names"]
    geo = json.loads((D["geometry"] / "chips.json").read_text())
    with rasterio.open(D["labels"] / "lcc2020_region.tif") as src:
        lab_base = classes.merge(src.read(1), classes.lookup(cfg))
    with rasterio.open(D["geometry"] / "masks.tif") as src:
        masks = src.read()
    lab_base[masks[0] == 0] = ignore

    out = D["chips"]
    if out.exists():
        shutil.rmtree(out)
    log, files = [], {"train": [], "val": [], "test": []}
    n_px, s1, s2 = 0, np.zeros(6), np.zeros(6)  # running sums for train band statistics
    class_px = np.zeros(len(names), dtype=np.int64)
    for year in sorted(set(train_years) | {test_year}):
        with rasterio.open(D["composites"] / f"s2_summer_{year}.tif") as src:
            comp, prof = src.read(), src.profile
        if comp.shape[1:] != lab_base.shape:
            raise SystemExit(f"{year}: composite, labels and masks are not on the same grid")
        lab_all = lab_base.copy()
        lab_all[~np.isfinite(comp).all(axis=0)] = ignore
        for ch in geo["chips"]:
            s = ch["split"]
            if not s or (s == "test" and year != test_year) or (s != "test" and year not in train_years):
                continue
            stem = ch["id"] if (s == "test" or not args.v2) else f"{ch['id']}_y{year}"
            r, c = ch["row"], ch["col"]
            win = (slice(r, r + chip_px), slice(c, c + chip_px))
            img = comp[(slice(None),) + win]
            lab = lab_all[win].copy()
            if s == "test":
                lab[masks[3][win] == 0] = ignore
            frac = float((lab != ignore).mean())
            if frac < cfg["chips"]["min_valid_fraction"]:
                log.append({"id": stem, "split": s, "status": "too few labelled pixels", "fraction": round(frac, 3)})
                continue
            transform = rasterio.windows.transform(rasterio.windows.Window(c, r, chip_px, chip_px), prof["transform"])
            d = out / s
            d.mkdir(parents=True, exist_ok=True)
            base = dict(driver="GTiff", height=chip_px, width=chip_px, crs=prof["crs"], transform=transform, compress="deflate")
            for suffix, arr, dtype in (("img", np.nan_to_num(img, nan=0.0), "float32"), ("label", lab[None], "int16"),
                                       ("strip", masks[2][win][None], "uint8")):
                p = d / f"{stem}_{suffix}.tif"
                with rasterio.open(p, "w", count=arr.shape[0], dtype=dtype, **base) as dst:
                    dst.write(arr.astype(dtype))
                files[s].append(p)
            if s == "train":
                ok = lab != ignore
                v = img[:, ok].astype(np.float64)
                n_px += v.shape[1]
                s1 += v.sum(axis=1)
                s2 += (v * v).sum(axis=1)
                class_px += np.bincount(lab[ok].astype(np.int64), minlength=len(names))[: len(names)]
            log.append({"id": stem, "split": s, "year": year, "status": "written", "fraction": round(frac, 3),
                        "strip_px": int(((masks[2][win] == 1) & (lab != ignore)).sum())})
        del comp
    mean = s1 / n_px
    stats = {"mean": [float(v) for v in mean], "std": [float(v) for v in np.sqrt(s2 / n_px - mean * mean)],
             "bands": [b["model"] for b in cfg["imagery"]["model_bands"]], "from": "train chips, labelled pixels only",
             "train_class_px": {n: int(class_px[i]) for i, n in enumerate(names)}}
    tars = D["tars"]
    if tars.exists():
        shutil.rmtree(tars)
    tars.mkdir(parents=True)
    parts = {s: pack(sorted(fs), out.parent, tars, f"chips_{tag}_{s}", args.part_mb) for s, fs in files.items()}
    manifest = {"dataset": f"LakePulse land-cover chips {tag} (2020 Land Cover of Canada on Sentinel-2 L2A summer medians "
                           f"{train_years} for train/val, {test_year} for test)",
                "label_year": YEAR, "tag": tag, "train_years": train_years, "test_year": test_year, "chip_px": chip_px, "res_m": cfg["chips"]["res_m"], "classes": cfg["classes"]["names"],
                "ignore_index": ignore, "band_stats": stats, "created_on": date.today().isoformat(),
                "labels_licence": cfg["labels"]["licence"], "labels_caveat": cfg["labels"]["caveat"],
                "counts": {s: len(fs) // 3 for s, fs in files.items()},
                "files": {str(p.relative_to(out.parent)): sha256(p) for fs in files.values() for p in fs},
                "tar_parts": {s: {name: sha256(tars / name) for name in names} for s, names in parts.items()},
                "log": log}
    (tars / "manifest.json").write_text(json.dumps(manifest, indent=1))
    print(json.dumps({k: manifest[k] for k in ("counts", "band_stats", "tar_parts")}, indent=1))
    print("skipped:", [e for e in log if e["status"] != "written"])
    if args.drive:
        dest = args.drive / f"chips_{tag}"
        dest.mkdir(parents=True, exist_ok=True)
        for p in tars.iterdir():
            shutil.copy2(p, dest / p.name)
        print("copied to", dest)


if __name__ == "__main__":
    main()
