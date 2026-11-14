"""Check the AppEEARS tasks and download finished bundles to data/raw/appeears/<key>/.

Usage: .venv/bin/python scripts/fetch_appeears.py [--wait-minutes 0]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lakepulse.sources import appeears  # noqa: E402

TASKS_FILE = ROOT / "data" / "appeears_tasks.json"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--wait-minutes", type=int, default=0)
    args = ap.parse_args()
    tasks = appeears.load_tasks(TASKS_FILE)
    if not tasks:
        sys.exit("No submitted tasks in data/appeears_tasks.json. Run scripts/submit_appeears.py first.")
    with appeears.Client() as c:
        for key, t in tasks.items():
            st = appeears.wait(c, t["task_id"], max_wait_s=args.wait_minutes * 60)
            print(f"{key}: {st.get('status')} (task {t['task_id']})")
            if st.get("status") == "done":
                files = c.download_bundle(t["task_id"], ROOT / "data" / "raw" / "appeears" / key)
                print(f"  downloaded {len(files)} files to data/raw/appeears/{key}/")


if __name__ == "__main__":
    main()
