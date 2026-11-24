"""Shared schema helpers and transport decoding from the first November study."""

import hashlib
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
PREVIOUS = HERE.parent / "2026-11"
sys.path.insert(0, str(PREVIOUS))
from fixtures import js, png_pixels
from tasks import INT, STR, arr, obj, parse_json
from fm_client import ESC, clock, decode, quota_state

DATA = HERE / "fixtures"


def read_rows(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def write_rows(path, values):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(js(row) + "\n" for row in values))


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    tmp.replace(path)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()
