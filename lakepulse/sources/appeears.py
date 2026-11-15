"""AppEEARS area requests: build, submit, poll and download.

API reference: https://appeears.earthdatacloud.nasa.gov/api/ (read 2026-11-14).
- POST /login with basic auth returns a bearer token.
- POST /task with {"task_type": "area", "task_name", "params": {"dates", "layers", "geo", "output"}}.
  Dates are MM-DD-YYYY. Output format "netcdf4"; projection "native" keeps the MODIS
  sinusoidal grid so pixel centres match our water-cell list exactly.
- GET /task/{id} for status; GET /bundle/{id} lists files; GET /bundle/{id}/{file_id} downloads.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import requests

from .earthdata_auth import credentials

API = "https://appeears.earthdatacloud.nasa.gov/api"
TIMEOUT = 120


def lake_lst_task(name: str, lake_feature_collection: dict, start: str, end: str) -> dict:
    layers = ["LST_Day_1km", "LST_Night_1km", "QC_Day", "QC_Night", "Day_view_time"]
    return {
        "task_type": "area",
        "task_name": name,
        "params": {
            "dates": [{"startDate": start, "endDate": end}],
            "layers": [{"product": "MOD11A2.061", "layer": l} for l in layers],
            "geo": lake_feature_collection,
            "output": {"format": {"type": "netcdf4"}, "projection": "native"},
        },
    }


def catchment_task(name: str, bbox: dict, start: str, end: str) -> dict:
    w, s, e, n = bbox["west"], bbox["south"], bbox["east"], bbox["north"]
    geo = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"name": name},
                "geometry": {"type": "Polygon", "coordinates": [[[w, s], [e, s], [e, n], [w, n], [w, s]]]},
            }
        ],
    }
    layers = [
        ("MOD13A3.061", "_1_km_monthly_NDVI"),
        ("MOD13A3.061", "_1_km_monthly_pixel_reliability"),
        ("MCD12Q1.061", "LC_Type1"),
    ]
    return {
        "task_type": "area",
        "task_name": name,
        "params": {
            "dates": [{"startDate": start, "endDate": end}],
            "layers": [{"product": p, "layer": l} for p, l in layers],
            "geo": geo,
            "output": {"format": {"type": "netcdf4"}, "projection": "native"},
        },
    }


class Client:
    def __init__(self) -> None:
        self._token: str | None = None
        self.s = requests.Session()

    def _login(self) -> None:
        user, pwd = credentials()
        r = requests.post(f"{API}/login", auth=(user, pwd), headers={"Content-Length": "0"}, timeout=TIMEOUT)
        if r.status_code != 200:
            raise RuntimeError(f"AppEEARS login failed with HTTP {r.status_code}")
        self._token = r.json()["token"]
        self.s.headers["Authorization"] = f"Bearer {self._token}"

    def __enter__(self) -> "Client":
        self._login()
        return self

    def _get(self, url: str, **kw) -> requests.Response:
        """GET that logs in again once if the token was invalidated (AppEEARS ends a
        user's token when any client for that user logs out)."""
        r = self.s.get(url, timeout=TIMEOUT, **kw)
        if r.status_code in (401, 403):
            self._login()
            r = self.s.get(url, timeout=TIMEOUT, **kw)
        return r

    def __exit__(self, *exc) -> None:
        # No /logout call: it would end the token for every other running client of
        # the same user (seen 2026-11-14: a quick status check killed a running wait).
        # Tokens expire on their own.
        self._token = None
        self.s.headers.pop("Authorization", None)

    def submit(self, task: dict) -> dict:
        r = self.s.post(f"{API}/task", json=task, timeout=TIMEOUT)
        if r.status_code not in (200, 202):
            raise RuntimeError(f"submit '{task['task_name']}' failed: HTTP {r.status_code} {r.text[:500]}")
        return r.json()

    def status(self, task_id: str) -> dict:
        r = self._get(f"{API}/task/{task_id}")
        r.raise_for_status()
        return r.json()

    def download_bundle(self, task_id: str, out_dir: Path, suffixes=(".nc", ".json", ".csv", ".xml", ".txt")) -> list[Path]:
        r = self._get(f"{API}/bundle/{task_id}")
        r.raise_for_status()
        out_dir.mkdir(parents=True, exist_ok=True)
        saved = []
        for f in r.json()["files"]:
            name = f["file_name"]
            if not name.endswith(suffixes):
                continue
            dest = out_dir / Path(name).name
            if dest.exists() and dest.stat().st_size == f.get("file_size", -1):
                saved.append(dest)
                continue
            with self.s.get(f"{API}/bundle/{task_id}/{f['file_id']}", stream=True, allow_redirects=True, timeout=TIMEOUT) as d:
                d.raise_for_status()
                with open(dest, "wb") as fh:
                    for chunk in d.iter_content(chunk_size=1 << 20):
                        fh.write(chunk)
            saved.append(dest)
        return saved


def load_tasks(path: Path) -> dict:
    return json.loads(path.read_text()) if path.exists() else {}


def save_tasks(path: Path, tasks: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(tasks, indent=2) + "\n")


def wait(client: Client, task_id: str, every_s: int = 60, max_wait_s: int = 0) -> dict:
    """Poll until done/error. max_wait_s = 0 means a single check."""
    start = time.time()
    while True:
        st = client.status(task_id)
        if st.get("status") in ("done", "error") or max_wait_s == 0 or time.time() - start > max_wait_s:
            return st
        time.sleep(every_s)
