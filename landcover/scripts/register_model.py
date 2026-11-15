"""Register a land-cover-ca training run in the MLflow model registry, from the Mac.

Colab cannot upload artifacts to the team MLflow server yet (artifacts go straight to Google Cloud Storage), so the model
folder is built here and uploaded with the Mac's Google application-default credentials, as was done for burn-scar-ca.

Needs an MLflow 2.15.x client (the server is 2.15.0) with google-cloud-storage; run it with that interpreter, e.g.
  <scratch venv>/bin/python landcover/scripts/register_model.py --run-name ft-l4-v1 --version-note "v1: ..."

The model folder (landcover/data/registry/<run>/model/) holds: best_weights_fp16.pt and .json, terratorch_config.yaml,
norm_stats.json (band means/stds and classes from the chip manifest), config.yaml, eval.json, baselines.json, README.md.
Registered name comes from config model.name; names in model.never_write are refused.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

import yaml

LC = Path(__file__).resolve().parents[1]
DATA = LC / "data"


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def fmt(r: dict) -> str:
    return f"mean IoU {r['mean_iou']}, pixel accuracy {r['pixel_accuracy']}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-name", required=True)
    ap.add_argument("--drive", type=Path, required=True, help="Local Drive sync folder .../My Drive/lakepulse-landcover")
    ap.add_argument("--chips", default="chips_v1", help="Drive chip folder whose manifest the run trained on")
    ap.add_argument("--baselines", type=Path, required=True, help="baselines.json scored on the same test chips")
    ap.add_argument("--version-note", required=True)
    ap.add_argument("--eval-name", default="eval.json", help="score file in the run folder (e.g. eval_v2test.json)")
    args = ap.parse_args()

    import mlflow
    from mlflow.tracking import MlflowClient

    cfg = yaml.safe_load((LC / "config.yaml").read_text())
    name = cfg["model"]["name"]
    if name in cfg["model"].get("never_write", []):
        raise SystemExit(f"refusing to write registered model {name!r}")
    run_dir = args.drive / "runs" / args.run_name
    out = DATA / "registry" / args.run_name / "model"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    for f in ("best_weights_fp16.pt", "best_weights_fp16.json", "terratorch_config.yaml", "summary.json"):
        shutil.copy2(run_dir / f, out / f)
    shutil.copy2(run_dir / args.eval_name, out / "eval.json")
    manifest = json.loads((args.drive / args.chips / "manifest.json").read_text())
    (out / "norm_stats.json").write_text(json.dumps({**manifest["band_stats"], "classes": manifest["classes"],
                                                      "ignore_index": manifest["ignore_index"]}, indent=1))
    shutil.copy2(LC / "config.yaml", out / "config.yaml")
    shutil.copy2(args.baselines, out / "baselines.json")
    ev = json.loads((out / "eval.json").read_text())
    bl = json.loads(args.baselines.read_text())
    weights_sha = sha256(out / "best_weights_fp16.pt")
    bm = cfg["model"]["base_model"]
    readme = f"""# {name} ({args.run_name})

{args.version_note}

Land cover (forest, cropland, built-up, water, wetland, other) at 30 m from a Sentinel-2 L2A summer median composite
(bands BLUE, GREEN, RED, NIR_NARROW, SWIR_1, SWIR_2; reflectance, no-data 0, then normalised with norm_stats.json).
Fine-tuned from {bm['id']} at revision {bm['revision']} (Apache-2.0). Weights: fp16 state dict of the TerraTorch
SemanticSegmentationTask (terratorch 1.2.14), SHA-256 {weights_sha}.

## Held-out test (Holland River unit + Lake Simcoe shore within 10 km; split by area; chips from {args.chips} test set)

| | Whole test block | Test pixels in the 30 m shoreline/stream strip |
|---|---|---|
| This model | {fmt(ev['test_block'])} | {fmt(ev['test_strip'])} |
| Gradient boosting (6 bands, per pixel) | {fmt(bl['gbm']['test_block'])} | {fmt(bl['gbm']['test_strip'])} |
| Most common class ({bl['most_common']['class']}) | {fmt(bl['most_common']['test_block'])} | {fmt(bl['most_common']['test_strip'])} |

Per-class IoU (test block): {json.dumps(ev['test_block']['per_class_iou'])}

## Limits
- Labels are the 2020 Land Cover of Canada, a published map (stated overall accuracy 86.9%, 832 samples), not
  field-checked ground truth. Scores measure agreement with that map.
- Wetland is rare in the training area and is poorly mapped (see per-class IoU).
- Summer composites only: a winter scene and a cloudy scene were probed and fail (eval.json, probes).
- Trained and tested in the Lake Simcoe area of southern Ontario only.

## Attribution
- Labels: Contains information licensed under the Open Government Licence - Canada (2020 Land Cover of Canada).
- Streams, shoreline, watershed units: Contains information licensed under the Open Government Licence - Ontario.
- Imagery: Contains modified Copernicus Sentinel data [verify: year range and exact wording].

Alpha Centauri Ventures Inc. (Centauri Research)
"""
    (out / "README.md").write_text(readme)

    tracking_uri = os.environ.get("MLFLOW_TRACKING_URI") or cfg["colab"].get("tracking_uri")
    if not tracking_uri:
        raise SystemExit("Set MLFLOW_TRACKING_URI to the MLflow server address (it is not stored in config.yaml).")
    mlflow.set_tracking_uri(tracking_uri)
    client = MlflowClient()
    exp = client.get_experiment_by_name(cfg["colab"]["mlflow_experiment"])
    runs = client.search_runs([exp.experiment_id], filter_string=f"tags.mlflow.runName = '{args.run_name}'")
    if not runs:
        raise SystemExit(f"no run named {args.run_name}")
    # A run resumed after Colab ended its runtime has one MLflow run per attempt; the saved best weights come from the
    # attempt that wrote best_weights_fp16.json last, which is the latest-started run.
    runs = sorted(runs, key=lambda r: r.info.start_time)
    run, earlier = runs[-1], [r.info.run_id for r in runs[:-1]]
    client.log_artifacts(run.info.run_id, str(out), artifact_path="model")
    try:
        client.get_registered_model(name)
    except Exception:
        client.create_registered_model(name, description="Land cover around Lake Simcoe for the LakePulse project. "
                                       "Fine-tuned Prithvi-EO-2.0-300M. See each version's README.")
    src = f"{run.info.artifact_uri}/model"
    mv = client.create_model_version(name, src, run_id=run.info.run_id, description=args.version_note)
    tags = {"test_block_mean_iou": ev["test_block"]["mean_iou"], "test_strip_mean_iou": ev["test_strip"]["mean_iou"],
            "gbm_test_block_mean_iou": bl["gbm"]["test_block"]["mean_iou"],
            "gbm_test_strip_mean_iou": bl["gbm"]["test_strip"]["mean_iou"],
            "beats_gbm_test_block": ev["test_block"]["mean_iou"] > bl["gbm"]["test_block"]["mean_iou"],
            "beats_gbm_test_strip": ev["test_strip"]["mean_iou"] > bl["gbm"]["test_strip"]["mean_iou"],
            "weights_sha256": weights_sha, "base_model_revision": bm["revision"], "chips": args.chips,
            "labels_caveat": "published map, not field-checked ground truth",
            "earlier_attempt_run_ids": ",".join(earlier) or "none"}
    for k, v in tags.items():
        client.set_model_version_tag(name, mv.version, k, str(v))
    print(json.dumps({"registered_model": name, "version": mv.version, "status": mv.status, "source": src,
                      "run_id": run.info.run_id, "tags": tags}, indent=1))


if __name__ == "__main__":
    main()
