"""Yearly land-cover maps from the trained land-cover-ca weights. Runs ON a Colab GPU machine, detached.

Reads  MyDrive/lakepulse-landcover/composites/s2_summer_<year>.tif  (from landcover/scripts/build_composite.py)
       MyDrive/lakepulse-landcover/runs/<run>/best_weights_fp16.pt and terratorch_config.yaml
       MyDrive/lakepulse-landcover/chips_v1/manifest.json  (band statistics, classes)
Writes MyDrive/lakepulse-landcover/runs/<run>/maps/lc_<year>.tif   uint8 class index, 255 = no clear observation
       MyDrive/lakepulse-landcover/runs/<run>/maps/infer_summary.json

Tiles of 224 px with 32 px overlap; each output pixel takes the prediction from the tile whose centre is nearest
(the inner part of each tile), so tile edges don't show.

Run on the VM:  nohup python3 .../code/colab/infer_vm.py --run-name NAME --years 2017 2018 ... &
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np

import os

# On Colab the mounted Drive; on the Mac set LC_DRIVE to the local Drive sync folder.
DRIVE = Path(os.environ.get("LC_DRIVE", "/content/drive/MyDrive/lakepulse-landcover"))
TILE, OVERLAP = 224, 32


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-name", required=True)
    ap.add_argument("--years", nargs="+", type=int, required=True)
    ap.add_argument("--chips", default="chips_v1", help="manifest the run trained on (normalisation)")
    args = ap.parse_args()
    import rasterio
    import torch
    import yaml
    from lightning.pytorch.cli import instantiate_class

    run = DRIVE / "runs" / args.run_name
    out = run / "maps"
    out.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((DRIVE / args.chips / "manifest.json").read_text())
    mean = np.array(manifest["band_stats"]["mean"], dtype=np.float32)[:, None, None]
    std = np.array(manifest["band_stats"]["std"], dtype=np.float32)[:, None, None]
    tt = yaml.safe_load((run / "terratorch_config.yaml").read_text())
    tt["model"]["init_args"]["model_args"]["backbone_pretrained"] = False  # weights come from our state dict
    tt["model"]["init_args"]["model_args"].pop("backbone_ckpt_path", None)
    model = instantiate_class((), tt["model"])
    state = torch.load(run / "best_weights_fp16.pt", map_location="cpu")
    model.load_state_dict({k: v.float() for k, v in state.items()}, strict=True)
    dev = "cuda" if torch.cuda.is_available() else ("mps" if torch.backends.mps.is_available() else "cpu")
    model = model.to(dev).eval()
    note = json.loads((run / "best_weights_fp16.json").read_text())
    summary = {"run": args.run_name, "weights_epoch": note.get("epoch"), "years": {}}
    step = TILE - OVERLAP
    for year in args.years:
        t0 = time.time()
        with rasterio.open(DRIVE / f"composites/s2_summer_{year}.tif") as src:
            img, prof = src.read().astype(np.float32), src.profile
        valid = np.isfinite(img).all(axis=0)
        # match training: no-data reflectance replaced by 0 (chips: nan_to_num 0; datamodule no_data_replace 0), then normalised
        x = (np.where(np.isfinite(img), img, 0.0) - mean) / std
        H, W = valid.shape
        pred = np.full((H, W), 255, dtype=np.uint8)
        rows = list(range(0, max(H - TILE, 0) + 1, step)) + ([H - TILE] if (H - TILE) % step else [])
        cols = list(range(0, max(W - TILE, 0) + 1, step)) + ([W - TILE] if (W - TILE) % step else [])
        half = OVERLAP // 2
        with torch.no_grad(), torch.autocast(dev if dev != "mps" else "cpu", dtype=torch.bfloat16, enabled=dev == "cuda"):
            for r in rows:
                batch, where = [], []
                for c in cols:
                    batch.append(x[:, r:r + TILE, c:c + TILE])
                    where.append(c)
                t = torch.from_numpy(np.stack(batch).astype(np.float32)).to(dev)
                res = model(t)
                logits = res.output if hasattr(res, "output") else res
                cls = logits.argmax(1).to(torch.uint8).cpu().numpy()
                r0 = 0 if r == 0 else half
                r1 = TILE if r + TILE >= H else TILE - half
                for c, k in zip(where, cls):
                    c0 = 0 if c == 0 else half
                    c1 = TILE if c + TILE >= W else TILE - half
                    pred[r + r0:r + r1, c + c0:c + c1] = k[r0:r1, c0:c1]
        pred[~valid] = 255
        p = dict(prof, count=1, dtype="uint8", nodata=255)
        with rasterio.open(out / f"lc_{year}.tif", "w", **p) as dst:
            dst.write(pred, 1)
        summary["years"][year] = {"valid_px": int(valid.sum()), "seconds": round(time.time() - t0)}
        (out / "infer_summary.json").write_text(json.dumps(summary, indent=1))
        print(year, summary["years"][year], flush=True)


if __name__ == "__main__":
    main()
