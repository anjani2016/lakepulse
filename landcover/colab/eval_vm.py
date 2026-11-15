"""Score the best land-cover-ca weights on the held-out test chips and on the probe chips. Runs ON the Colab GPU machine.

Uses the same IoU code as the Mac baselines (code/lc/metrics.py on Drive). Test chips come from /content/work/chips
(staged by train_vm.py, SHA-256 checked); probes from MyDrive/lakepulse-landcover/probes/.
Writes MyDrive/lakepulse-landcover/runs/<run>/eval.json.

Normalisation matches training: no-data reflectance 0, then (x - mean) / std with the train-chip statistics.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

import os

# On Colab the mounted Drive; on the Mac set LC_DRIVE to the local Drive sync folder.
DRIVE = Path(os.environ.get("LC_DRIVE", "/content/drive/MyDrive/lakepulse-landcover"))
sys.path.insert(0, str(DRIVE / "code"))
from lc import metrics  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-name", required=True)
    ap.add_argument("--chips", default="chips_v1", help="manifest the run trained on (normalisation)")
    ap.add_argument("--test-dir", default="/content/work/chips/v1/test", help="test chips to score")
    ap.add_argument("--out-name", default="eval.json", help="result file in the run folder")
    args = ap.parse_args()
    import rasterio
    import torch
    import yaml
    from lightning.pytorch.cli import instantiate_class

    run = DRIVE / "runs" / args.run_name
    manifest = json.loads((DRIVE / args.chips / "manifest.json").read_text())
    names, ign = manifest["classes"], manifest["ignore_index"]
    mean = np.array(manifest["band_stats"]["mean"], dtype=np.float32)[:, None, None]
    std = np.array(manifest["band_stats"]["std"], dtype=np.float32)[:, None, None]
    tt = yaml.safe_load((run / "terratorch_config.yaml").read_text())
    tt["model"]["init_args"]["model_args"]["backbone_pretrained"] = False
    tt["model"]["init_args"]["model_args"].pop("backbone_ckpt_path", None)
    model = instantiate_class((), tt["model"])
    state = torch.load(run / "best_weights_fp16.pt", map_location="cpu")
    model.load_state_dict({k: v.float() for k, v in state.items()}, strict=True)
    dev = "cuda" if torch.cuda.is_available() else ("mps" if torch.backends.mps.is_available() else "cpu")
    model = model.to(dev).eval()

    def predict(img: np.ndarray) -> np.ndarray:
        x = (np.nan_to_num(img, nan=0.0) - mean) / std
        with torch.no_grad(), torch.autocast(dev if dev != "mps" else "cpu", dtype=torch.bfloat16, enabled=dev == "cuda"):
            res = model(torch.from_numpy(x[None].astype(np.float32)).to(dev))
        return (res.output if hasattr(res, "output") else res).argmax(1)[0].cpu().numpy()

    def score(folder: Path, stems: list[str]) -> dict:
        cm_all = np.zeros((len(names), len(names)), dtype=np.int64)
        cm_strip = cm_all.copy()
        per = {}
        for stem in stems:
            with rasterio.open(folder / f"{stem}_img.tif") as a, rasterio.open(folder / f"{stem}_label.tif") as b, \
                    rasterio.open(folder / f"{stem}_strip.tif") as c:
                img, lab, strip = a.read().astype(np.float32), b.read(1), c.read(1)
            pred = predict(img)
            cm = metrics.confusion(lab, pred, len(names), ign)
            cm_all += cm
            cm_strip += metrics.confusion(lab, pred, len(names), ign, mask=strip == 1)
            per[stem] = metrics.iou(cm, names)
        return {"all": metrics.iou(cm_all, names), "strip": metrics.iou(cm_strip, names), "per_chip": per}

    test_dir = Path(args.test_dir)
    test = score(test_dir, sorted(p.name[:-len("_img.tif")] for p in test_dir.glob("*_img.tif")))
    out = {"run": args.run_name, "test_dir": str(test_dir), "chips": args.chips, "weights": json.loads((run / "best_weights_fp16.json").read_text()),
           "test_block": test["all"], "test_strip": test["strip"]}
    probe_dir = DRIVE / "probes"
    if (probe_dir / "probes.json").exists():
        stems = sorted(p.name[:-len("_img.tif")] for p in probe_dir.glob("*_img.tif"))
        out["probes"] = score(probe_dir, stems)["per_chip"]
    (run / args.out_name).write_text(json.dumps(out, indent=1))
    print(json.dumps({k: out[k] for k in ("test_block", "test_strip")}, indent=1))


if __name__ == "__main__":
    main()
