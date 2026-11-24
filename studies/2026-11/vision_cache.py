"""Build an isolated Vision cache without forwarding synthetic image answers to the model."""

import argparse
import json
from pathlib import Path
import subprocess
import tempfile
from fixtures import DATA, digest


def run(cache, tool):
    cache.mkdir(parents=True, exist_ok=True)
    files = sorted((DATA / "images").glob("*.png"))
    lock = json.loads((DATA / "lock.json").read_text())
    for image in files:
        if digest(image) != lock["images/" + image.name]:
            raise ValueError("Image changed: " + image.name)
    with tempfile.TemporaryDirectory() as tmp:
        manifest = Path(tmp) / "inputs.json"
        manifest.write_text(json.dumps([[f.stem, str(f)] for f in files]))
        subprocess.run([tool.resolve(), "batch", manifest, cache.resolve()], check=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("cache", type=Path)
    p.add_argument("tool", type=Path)
    a = p.parse_args()
    run(a.cache, a.tool)
