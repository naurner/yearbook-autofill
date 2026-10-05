"""Shared loading for the vignette CLI and scripts."""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]


def load_manifest(template):
    return json.loads((HERE / "manifests" / f"{template}.json").read_text(encoding="utf-8"))
