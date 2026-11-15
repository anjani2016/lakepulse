"""Load landcover/config.yaml. Relative file paths in it are relative to the config file."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

LC_ROOT = Path(__file__).resolve().parents[1]
DEFAULT = LC_ROOT / "config.yaml"
DATA = LC_ROOT / "data"  # git-ignored: downloads, geometry, chips


def load(path: Path | str = DEFAULT) -> dict[str, Any]:
    path = Path(path)
    cfg = yaml.safe_load(path.read_text())
    base = path.resolve().parent
    for key in ("units_file", "lake_outline"):
        cfg["region"][key] = str((base / cfg["region"][key]).resolve())
    return cfg


def dirs(v2: bool = False) -> dict[str, Path]:
    """Output folders. v1 = the 13-unit region (also used for yearly inference and shares); v2 = the wider training grid."""
    s = "_v2" if v2 else ""
    return {"labels": DATA / f"labels{s}", "geometry": DATA / f"geometry{s}", "composites": DATA / f"composites{s}",
            "chips": DATA / "chips" / ("v2" if v2 else "v1"), "tars": DATA / "chips" / ("v2_tars" if v2 else "v1_tars"),
            "results": DATA / "results"}
