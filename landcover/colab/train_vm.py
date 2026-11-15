"""land-cover-ca fine-tune. Runs ON the Colab GPU machine, detached (nohup), so it keeps going after the laptop closes.

Inputs on Google Drive (mounted at /content/drive by `colab drivemount`, which the owner signs in to once):
  MyDrive/lakepulse-landcover/chips_v1/        tar parts + manifest.json from landcover/scripts/stage_chips.py
  MyDrive/lakepulse-landcover/code/            landcover/ copied by the launcher (config.yaml, colab/)
Outputs on Drive (MyDrive/lakepulse-landcover/runs/<run_name>/):
  best_weights_fp16.pt (+ .json)   written whenever val/loss improves
  last.ckpt                         full Lightning checkpoint every `ckpt_every` epochs, for resuming
  summary.json, train.log           progress; the Mac reads these
If last.ckpt exists the run resumes from it (Colab ended earlier runtimes after about an hour).

MLflow: credentials read from /root/.mlflow/credentials (mode 600, copied by the launcher, never printed); the file is
deleted when this script ends, success or not.

Run on the VM:  nohup python /content/drive/MyDrive/lakepulse-landcover/code/colab/train_vm.py --run-name NAME &
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tarfile

import numpy as np
import time
import traceback
from pathlib import Path

DRIVE = Path("/content/drive/MyDrive/lakepulse-landcover")
WORK = Path("/content/work")
CREDS = Path("/root/.mlflow/credentials")


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def stage_chips(src: Path, dst: Path) -> dict:
    """Copy tar parts from Drive, check SHA-256 against the manifest, extract, check every chip file. Fails closed."""
    manifest = json.loads((src / "manifest.json").read_text())
    dst.mkdir(parents=True, exist_ok=True)
    for split, parts in manifest["tar_parts"].items():
        for name, digest in parts.items():
            local = WORK / name
            if not local.exists() or sha256(local) != digest:
                subprocess.run(["cp", str(src / name), str(local)], check=True)
            if sha256(local) != digest:
                raise RuntimeError(f"{name}: SHA-256 mismatch after copy")
            with tarfile.open(local) as t:
                t.extractall(dst, filter="data")
    bad = [rel for rel, digest in manifest["files"].items() if sha256(dst / rel) != digest]
    if bad:
        raise RuntimeError(f"{len(bad)} chip files fail their SHA-256, e.g. {bad[:3]}")
    return manifest


def terratorch_config(cfg: dict, manifest: dict, chips: Path, ckpt_file: str, args) -> dict:
    stats = manifest["band_stats"]
    bands = stats["bands"]
    return {
        "model": {"class_path": "terratorch.tasks.SemanticSegmentationTask", "init_args": {
            "model_factory": "EncoderDecoderFactory",
            "model_args": {
                "backbone": "prithvi_eo_v2_300", "backbone_pretrained": True,
                "backbone_ckpt_path": ckpt_file,  # the pinned base checkpoint, not a registry download
                "backbone_bands": bands,
                "necks": [{"name": "SelectIndices", "indices": [5, 11, 17, 23]}, {"name": "ReshapeTokensToImage"},
                          {"name": "LearnedInterpolateToPyramidal"}],
                "decoder": "UNetDecoder", "decoder_channels": [512, 256, 128, 64],
                "num_classes": len(manifest["classes"])},
            "loss": "ce", "ignore_index": manifest["ignore_index"], "freeze_backbone": False, "plot_on_val": False,
            "class_weights": class_weights(manifest) if args.class_weights else None,
            "class_names": manifest["classes"]}},
        "data": {"class_path": "terratorch.datamodules.GenericNonGeoSegmentationDataModule", "init_args": {
            "batch_size": args.batch_size, "num_workers": 4, "dataset_bands": bands, "output_bands": bands,
            "rgb_indices": [2, 1, 0],
            "train_data_root": str(chips / manifest.get("tag", "v1") / "train"), "val_data_root": str(chips / manifest.get("tag", "v1") / "val"),
            "test_data_root": str(chips / manifest.get("tag", "v1") / "test"),
            "img_grep": "*_img.tif", "label_grep": "*_label.tif",
            "means": stats["mean"], "stds": stats["std"], "num_classes": len(manifest["classes"]),
            "train_transform": [{"class_path": "albumentations.D4"}, {"class_path": "ToTensorV2"}],
            "test_transform": [{"class_path": "ToTensorV2"}],
            "no_data_replace": 0, "no_label_replace": manifest["ignore_index"]}},
    }


def class_weights(manifest: dict) -> list[float]:
    """Inverse square root of each class's share of labelled train pixels, scaled to mean 1 (gate choice)."""
    px = np.array([manifest["band_stats"]["train_class_px"][c] for c in manifest["classes"]], dtype=float)
    w = 1.0 / np.sqrt(np.maximum(px, 1.0) / px.sum())
    return [round(float(v), 4) for v in w / w.mean()]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-name", required=True)
    ap.add_argument("--max-epochs", type=int, default=60)
    ap.add_argument("--patience", type=int, default=12)
    ap.add_argument("--batch-size", type=int, default=8)
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--ckpt-every", type=int, default=3)
    ap.add_argument("--max-hours", type=float, required=True, help="Hard wall-clock cap, set by the launcher from the unit cap")
    ap.add_argument("--chips", default="chips_v1", help="Drive folder with tar parts and manifest")
    ap.add_argument("--class-weights", action="store_true", help="weight the loss by inverse sqrt class frequency")
    ap.add_argument("--smoke", action="store_true", help="2 epochs, few batches; checks the pipeline end to end")
    ap.add_argument("--init-from-best", action="store_true",
                    help="when last.ckpt is missing or unreadable, start from this run's best_weights_fp16.pt (fresh optimizer)")
    args = ap.parse_args()

    out = DRIVE / "runs" / args.run_name
    out.mkdir(parents=True, exist_ok=True)
    summary = {"run_name": args.run_name, "started": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "args": vars(args), "steps": {}}
    if (out / "summary.json").exists():  # keep earlier attempts of this run (a runtime that ended keeps its epochs here)
        try:
            prev = json.loads((out / "summary.json").read_text())
            summary["previous_attempts"] = prev.pop("previous_attempts", []) + [prev]
        except ValueError:
            summary["previous_attempts"] = [{"error": "earlier summary.json unreadable"}]

    def save():
        (out / "summary.json").write_text(json.dumps(summary, indent=1, default=str))

    try:
        import yaml
        cfg = yaml.safe_load((DRIVE / "code/config.yaml").read_text())
        gpu = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
                             capture_output=True, text=True).stdout.strip()
        summary["gpu"] = gpu
        manifest = stage_chips(DRIVE / args.chips, WORK / "chips")
        summary["steps"]["chips"] = manifest["counts"]
        save()

        from huggingface_hub import hf_hub_download
        bm = cfg["model"]["base_model"]
        if "burnscars" in bm["id"].lower() or "burn-scar" in bm["id"].lower():
            raise RuntimeError("base model must be the bare Prithvi-EO-2.0-300M, not a burn-scar model")
        ckpt_file = hf_hub_download(bm["id"], bm["checkpoint_file"], revision=bm["revision"], local_dir=str(WORK / "base"))
        summary["steps"]["base_model"] = {"id": bm["id"], "revision": bm["revision"], "sha256": sha256(Path(ckpt_file))}
        save()

        import torch
        from lightning.pytorch import Trainer, seed_everything
        from lightning.pytorch.callbacks import Callback, EarlyStopping, LearningRateMonitor, ModelCheckpoint
        from lightning.pytorch.loggers import MLFlowLogger
        from lightning.pytorch.cli import instantiate_class

        seed_everything(42, workers=True)
        tt = terratorch_config(cfg, manifest, WORK / "chips", ckpt_file, args)
        (out / "terratorch_config.yaml").write_text(yaml.safe_dump(tt))
        model = instantiate_class((), tt["model"])
        dm = instantiate_class((), tt["data"])

        def configure_optimizers():
            opt = torch.optim.AdamW(model.parameters(), lr=args.lr)
            sched = torch.optim.lr_scheduler.ReduceLROnPlateau(opt, factor=0.5, patience=4)
            return {"optimizer": opt, "lr_scheduler": {"scheduler": sched, "monitor": "val/loss"}}

        model.configure_optimizers = configure_optimizers

        class BestWeightsToDrive(Callback):
            """fp16 weights to Drive whenever val/loss improves (pattern from the fire work's BestWeightsExport)."""

            def __init__(self):
                super().__init__()
                self.best = None

            def on_validation_end(self, trainer, pl_module):
                if trainer.sanity_checking:
                    return
                v = trainer.callback_metrics.get("val/loss")
                if v is None or (self.best is not None and float(v) >= self.best):
                    return
                self.best = float(v)
                state = {k: t.half() if t.is_floating_point() else t for k, t in pl_module.state_dict().items()}
                tmp = WORK / "best.tmp"
                torch.save(state, tmp)
                digest = sha256(tmp)
                subprocess.run(["cp", str(tmp), str(out / "best_weights_fp16.pt")], check=True)
                metrics = {k: float(t) for k, t in trainer.callback_metrics.items() if k.startswith("val/")}
                # sha256 lets a later run check the .pt on Drive is the one this note describes (Drive uploads lag)
                (out / "best_weights_fp16.json").write_text(json.dumps({"epoch": trainer.current_epoch, "sha256": digest,
                                                                         "attempt": len(summary.get("previous_attempts", [])) + 1, **metrics}))

        class Progress(Callback):
            def on_train_epoch_end(self, trainer, pl_module):
                summary.setdefault("epochs", []).append({"epoch": trainer.current_epoch, "time": time.strftime("%H:%M:%S"),
                    **{k: round(float(t), 5) for k, t in trainer.callback_metrics.items()}})
                save()

        resume = out / "last.ckpt"
        resuming = resume.exists()  # decided before fit; fit itself writes last.ckpt
        if resuming:  # a runtime can end mid-upload; only resume from a checkpoint that loads
            try:
                ck = torch.load(resume, map_location="cpu", weights_only=False)
                summary["last_ckpt"] = {"epoch": ck.get("epoch"), "global_step": ck.get("global_step"), "bytes": resume.stat().st_size}
                del ck
            except Exception as exc:
                resuming = False
                summary["last_ckpt"] = {"unusable": repr(exc)[:300], "bytes": resume.stat().st_size}
                resume.rename(out / "last_unusable.ckpt")
        summary["resumed_from_last_ckpt"] = resuming
        best_note = out / "best_weights_fp16.json"
        prev_best = json.loads(best_note.read_text()) if best_note.exists() else None
        if not resuming and args.init_from_best and prev_best and (out / "best_weights_fp16.pt").exists():
            state = torch.load(out / "best_weights_fp16.pt", map_location="cpu")
            model.load_state_dict({k: v.float() for k, v in state.items()}, strict=True)
            summary["init_from_best"] = {"epoch": prev_best.get("epoch"), "val/loss": prev_best.get("val/loss"),
                                         "note": "weights only; optimizer, learning-rate schedule and epoch count start fresh"}
        save()
        logger = None
        tracking_uri = os.environ.get("MLFLOW_TRACKING_URI") or cfg["colab"].get("tracking_uri")
        if CREDS.exists() and not tracking_uri:
            print("MLFLOW_TRACKING_URI is not set: MLflow logging is off for this run.", flush=True)
        if CREDS.exists() and tracking_uri:  # MLflow reads /root/.mlflow/credentials itself; this script never opens it
            logger = MLFlowLogger(experiment_name=cfg["colab"]["mlflow_experiment"], tracking_uri=tracking_uri,
                                  run_name=args.run_name, tags={"model": f"{cfg['model']['name']}-{cfg['model']['version']}",
                                  "base_model_revision": bm["revision"], "gpu": gpu, "resumed": str(resuming)})
        best_cb = BestWeightsToDrive()
        if prev_best and prev_best.get("val/loss") is not None:
            best_cb.best = float(prev_best["val/loss"])  # never overwrite saved best weights with worse ones
        trainer = Trainer(
            logger=logger if logger else False, max_epochs=2 if args.smoke else args.max_epochs,
            limit_train_batches=4 if args.smoke else 1.0, limit_val_batches=2 if args.smoke else 1.0,
            max_time={"hours": args.max_hours}, precision="bf16-mixed", log_every_n_steps=5, enable_progress_bar=False,
            default_root_dir=str(WORK / "out"),
            callbacks=[ModelCheckpoint(dirpath=str(out), filename="last", save_last=False, every_n_epochs=args.ckpt_every,
                                       save_top_k=-1, enable_version_counter=False),
                       EarlyStopping(monitor="val/loss", patience=args.patience), LearningRateMonitor(logging_interval="epoch"),
                       best_cb, Progress()])
        trainer.fit(model, datamodule=dm, ckpt_path=str(resume) if resuming else None)
        summary["steps"]["fit"] = {"stopped_epoch": trainer.current_epoch, "best_val_loss": best_cb.best}
        summary["status"] = "done"
    except Exception as exc:
        summary["status"] = "failed"
        summary["error"] = repr(exc)[:800]
        summary["trace"] = traceback.format_exc()[-3000:]
    finally:
        if CREDS.exists():
            CREDS.unlink()
        summary["ended"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        summary["mlflow_credentials_removed"] = not CREDS.exists()
        save()


if __name__ == "__main__":
    main()
