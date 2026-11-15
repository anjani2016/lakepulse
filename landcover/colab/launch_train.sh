#!/usr/bin/env zsh
# Start a land-cover-ca training run on Colab that keeps going after the laptop closes.
#
#   landcover/colab/launch_train.sh <session> <gpu: L4|A100|H100> <run_name> <units_left_in_cap> [--smoke]
#
# Steps: copy code to the Drive sync folder -> new session -> mount Drive (the owner signs in once in the browser) ->
# install pinned packages -> copy the MLflow credentials file (never printed) -> start train_vm.py with nohup.
# The training wall-clock cap = units_left / the usage rate `colab usage` shows once the GPU is attached, minus 0.3 h.
# Ledger: read `colab usage` before and after and add a row to landcover/colab_ledger.md.
set -euo pipefail
SESSION=$1; GPU=$2; RUN=$3; UNITS_LEFT=$4; SMOKE=${5:-}
HERE=${0:A:h}; LC=${HERE:h}
DRIVE_LOCAL=$(ls -d ~/Library/CloudStorage/GoogleDrive-*/"My Drive" | head -1)/lakepulse-landcover
VM_DRIVE=/content/drive/MyDrive/lakepulse-landcover

mkdir -p "$DRIVE_LOCAL/code/colab"
cp "$LC/config.yaml" "$DRIVE_LOCAL/code/config.yaml"
cp "$LC/colab/train_vm.py" "$DRIVE_LOCAL/code/colab/train_vm.py"
[[ -f "$DRIVE_LOCAL/chips_v1/manifest.json" ]] || { echo "chips_v1 not on Drive yet"; exit 1; }

colab usage
colab new -s "$SESSION" --gpu "$GPU"
# On a fresh session the first mount asks for Google consent (owner approves in the browser, presses Enter) and fails;
# a second run then mounts without a prompt (seen twice on 2026-11-14). So: try, and retry once.
colab drivemount -s "$SESSION" || true
colab ssh -s "$SESSION" -- test -d /content/drive/MyDrive || colab drivemount -s "$SESSION"
colab ssh -s "$SESSION" -- test -d /content/drive/MyDrive || { echo "Drive not mounted"; exit 1; }
# wait until Drive sync has uploaded the code and chips
for i in {1..60}; do
  colab ssh -s "$SESSION" -- test -f "$VM_DRIVE/code/colab/train_vm.py" -a -f "$VM_DRIVE/chips_v1/manifest.json" && break
  sleep 10
done
colab ssh -s "$SESSION" -- pip uninstall -y -q mlflow mlflow-tracing; colab ssh -s "$SESSION" -- pip install -q "terratorch==1.2.14" "mlflow-skinny==2.15.1"   # terratorch as in the fire work; MLflow 2.15 client to match the server (owner); full mlflow 2.15.1 fails to build pyarrow on Colab Python 3.13
colab upload -s "$SESSION" ~/.mlflow/credentials /content/.mlflow_credentials
colab ssh -s "$SESSION" -- 'mkdir -p /root/.mlflow && mv /content/.mlflow_credentials /root/.mlflow/credentials && chmod 600 /root/.mlflow/credentials'

RATE=$(colab usage | awk -F'[: /]+' '/Usage rate/ {print $3}')
HOURS=$(python3 -c "r=float('$RATE'); print(max(0.2, round(float('$UNITS_LEFT')/r - 0.3, 2)) if r > 0 else 0)")
[[ "$HOURS" != "0" ]] || { echo "usage rate not readable ($RATE); not starting"; colab stop -s "$SESSION"; exit 1; }
echo "rate $RATE units/h -> training cap $HOURS h"
colab ssh -s "$SESSION" -- mkdir -p "$VM_DRIVE/runs/$RUN"
colab ssh -s "$SESSION" -- "nohup python3 $VM_DRIVE/code/colab/train_vm.py --run-name $RUN --max-hours $HOURS $SMOKE > $VM_DRIVE/runs/$RUN/train.log 2>&1 &"
echo "started; progress in My Drive/lakepulse-landcover/runs/$RUN/summary.json"
