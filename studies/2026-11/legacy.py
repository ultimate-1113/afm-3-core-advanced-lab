"""Repeat October's published inputs, instructions and grader in an empty run directory."""

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
PIN = "f07f88bb36edb2cebd9ba17eb5f6fc0f51b682be"
DIGESTS = {
    "scripts/lab.py": "5e35209e1cb780d0d2796733593e1ec243fcda65f6f986f8db9da3ee0c0cd0ec",
    "data/regressions.jsonl": "63996755efd200fe22c765cf900faa8be68813baebe22c65635590f087fb4bec",
    "data/extraction-heldout.jsonl": "1c100b8a06db94bbb52a4c1cf3b301a47e922f14f1a80608d1064272134cad7c",
    "data/table-heldout.jsonl": "76bbc9f8de11fc676255fbfb373d19279fb149566dd7461e0c0af9673c3f3dae",
    "data/diff-heldout.jsonl": "a021b32c43e76eea4d4ff22370addb7bb05a1377b22a9bc20f035a840f775566",
    "reports/selected-methods.json": "fccb4fd1eccea875274dbb8f7ea75b30dcda607692f194be7821dd32ebda56d6",
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runner", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    args = parser.parse_args()
    work = args.work.resolve()
    for name, expected in DIGESTS.items():
        src = REPO / name
        if hashlib.sha256(src.read_bytes()).hexdigest() != expected:
            raise SystemExit(f"October input differs: {name}")
        dest = work / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dest)
    (work / "bin").mkdir(exist_ok=True)
    (work / "results").mkdir(exist_ok=True)
    shutil.copy2(args.runner, work / "bin/afm-runner")
    spec = importlib.util.spec_from_file_location("october", work / "scripts/lab.py")
    october = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(october)
    choice = json.loads((work / "reports/selected-methods.json").read_text())
    runner = october.Runner()
    try:
        meta = dict(
            commit=PIN,
            runner_sha256=hashlib.sha256(args.runner.read_bytes()).hexdigest(),
            ready=runner.ready,
            inputs=DIGESTS,
        )
        (work / "results/manifest.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2)
        )
        october.evaluate(
            "regressions",
            ["baseline", "guided"],
            runner,
            work / "results/regressions.jsonl",
        )
        for domain in ("extraction", "table", "diff"):
            october.evaluate(
                domain + "-heldout",
                ["baseline", choice[domain]],
                runner,
                work / "results/heldout.jsonl",
            )
    finally:
        runner.close()


if __name__ == "__main__":
    main()
