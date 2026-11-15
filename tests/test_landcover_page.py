"""The land-cover page's data must be exactly the checksummed CSVs from the dashboard."""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "data" / "landcover_dashboard"


def test_every_csv_matches_its_manifest_checksum():
    manifest = json.loads((SRC / "manifest.json").read_text())
    ids = [d["id"] for d in manifest["datasets"]]
    assert ids == ["test_scores", "epochs", "probes", "shares", "modis", "compute"]
    for d in manifest["datasets"]:
        assert hashlib.sha256((SRC / d["file"]).read_bytes()).hexdigest() == d["sha256"], d["file"]


def test_published_page_data_is_up_to_date(tmp_path):
    """Rebuilding web/landcover-data.js must reproduce the committed file byte for byte."""
    committed = (ROOT / "web" / "landcover-data.js").read_bytes()
    subprocess.run([sys.executable, str(ROOT / "scripts" / "build_landcover_page.py")], check=True, capture_output=True)
    assert (ROOT / "web" / "landcover-data.js").read_bytes() == committed


def test_builder_refuses_a_changed_csv(tmp_path, monkeypatch):
    import importlib.util

    spec = importlib.util.spec_from_file_location("blp", ROOT / "scripts" / "build_landcover_page.py")
    blp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(blp)
    src = tmp_path / "src"
    src.mkdir()
    for f in SRC.iterdir():
        (src / f.name).write_bytes(f.read_bytes())
    (src / "compute.csv").write_text("session,gpu,date,units\nTampered,L4,2026-11-14,999\n")
    out = tmp_path / "landcover-data.js"
    monkeypatch.setattr(blp, "SRC", src)
    monkeypatch.setattr(blp, "OUT", out)
    try:
        blp.main()
        raised = False
    except SystemExit as e:
        raised = "does not match manifest" in str(e)
    assert raised and not out.exists()


def test_page_shows_data_as_text_not_html():
    """Data values are untrusted: the page must not insert them with innerHTML."""
    page = (ROOT / "web" / "landcover.html").read_text()
    runtime = (ROOT / "web" / "landcover-runtime.js").read_text()
    assert "innerHTML" not in page and "innerHTML" not in runtime and ".html(" not in page


def test_page_code_does_not_need_unsafe_eval():
    """The site's CSP has no 'unsafe-eval': no eval, new Function or d3.csvParse in our code."""
    import re
    for f in ("web/landcover.html", "web/landcover-runtime.js"):
        code = (ROOT / f).read_text()
        code = re.sub(r"//[^\n]*", "", code)  # comments may mention them
        assert not re.search(r"\beval\(|new Function|csvParse|tsvParse|dsvFormat", code), f
