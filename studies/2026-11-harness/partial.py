"""Report an interrupted PCC panel on identical completed problems of both models."""

import argparse
import json
from pathlib import Path
from statistics import median
from report import paired, stable
from common import HERE, DATA, read_rows, write_rows, write_json
from grade import strategies, outcome
from protocol import request, unpack, checks
from run import fingerprint, preflight


def measure(cloud, core):
    preflight()
    inputs = read_rows(DATA / "inputs.jsonl")
    gold = {r["id"]: r for r in read_rows(DATA / "answers.jsonl")}
    ocr = {r["id"]: r for r in read_rows(DATA / "vision.jsonl")}
    grouped = {m: {} for m in ("pcc", "system")}
    for row in cloud + core:
        part = grouped[row["model"]].setdefault(row["id"], {})
        if row["method"] in part:
            raise ValueError("Duplicate call")
        part[row["method"]] = row
    result = []
    complete = []
    for c in inputs:
        cid = c["id"]
        table = grouped["pcc"].get(cid, {})
        if not table:
            continue
        corresponding = grouped["system"][cid]
        for arm, r in table.items():
            parent = table["schema"]["text"] if arm in ("feedback", "review") else None
            req = request(c, arm, ocr.get(cid, {}).get("rows", []), parent)
            assert req and r["request_sha256"] == fingerprint(req)
            if parent is None:
                assert r["request_sha256"] == corresponding[arm]["request_sha256"]
            if r["status"] == "ok":
                assert r["transcript_model"] == "pcc"
        available = []
        for method in strategies(c["domain"]):
            if method == "code":
                ready = True
            elif method in ("review", "feedback", "guard"):
                ready = "schema" in table
                if ready and table["schema"]["status"] == "ok":
                    trigger = checks(
                        c["domain"], c["payload"], unpack(table["schema"]["text"])[0]
                    )
                    ready = (
                        ("review" in table)
                        if method == "review"
                        else (not trigger or "feedback" in table)
                    )
            else:
                ready = method in table
            if not ready:
                continue
            available.append(method)
            for model, records in [("system", corresponding), ("pcc", table)]:
                result.append(
                    dict(model=model, **outcome(c, method, records, ocr, gold[cid]))
                )
        if set(available) == set(strategies(c["domain"])):
            complete.append(cid)
    summary = {}
    for model in ("system", "pcc"):
        summary[model] = {}
        for method in (
            "plain",
            "schema",
            "review",
            "feedback",
            "guard",
            "program",
            "code",
            "rows",
        ):
            sample = [
                r
                for r in result
                if r["id"] in complete and r["model"] == model and r["method"] == method
            ]
            baseline = [
                r
                for r in result
                if r["model"] == model
                and r["method"] == "plain"
                and r["id"] in {a["id"] for a in sample}
            ]
            if sample:
                summary[model][method] = dict(
                    n=len(sample),
                    exact=sum(v["exact"] for v in sample),
                    versus_plain=paired(baseline, sample),
                    median_cli_ocr_s=median(v["cli_s"] + v["ocr_s"] for v in sample),
                )
    return result, dict(
        completed_all_methods=complete,
        started_cases=sorted(grouped["pcc"]),
        calls=len(cloud),
        common=summary,
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["export", "verify"])
    ap.add_argument("--results", type=Path, default=HERE / "results")
    ap.add_argument("--raw-dir", type=Path)
    opt = ap.parse_args()
    folder = opt.results
    core = [r for r in read_rows(folder / "calls.jsonl") if r["model"] == "system"]
    if opt.mode == "export":
        if not opt.raw_dir:
            ap.error("--raw-dir is required to export")
        cloud = [
            json.loads(f.read_text()) for f in sorted(opt.raw_dir.glob("*.pcc.*.json"))
        ]
        write_rows(folder / "pcc-interim-calls.jsonl", cloud)
    else:
        cloud = read_rows(folder / "pcc-interim-calls.jsonl")
    rows, summary = measure(cloud, core)
    dest = folder / "pcc-interim.json"
    detail = folder / "pcc-interim-outcomes.jsonl"
    if opt.mode == "export":
        write_json(dest, summary)
        write_rows(detail, rows)
    else:
        assert summary == json.loads(dest.read_text())
        assert list(map(stable, rows)) == list(map(stable, read_rows(detail)))
    print(
        f"{len(cloud)} recorded PCC calls, {len(summary['completed_all_methods'])} complete paired cases"
    )


if __name__ == "__main__":
    main()
