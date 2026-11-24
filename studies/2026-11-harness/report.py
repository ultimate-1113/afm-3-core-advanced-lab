"""Reconstruct both sides of each comparison from the original CLI answers."""

import argparse
from collections import Counter
import json
from pathlib import Path
from statistics import median
from common import DATA, HERE, read_rows, write_json, write_rows, sha
from geometry import read_table
from grade import outcome, strategies
from protocol import request
from run import WORK, fingerprint, preflight


def paired(baseline, other):
    b = {v["id"]: v["exact"] for v in baseline}
    o = {v["id"]: v["exact"] for v in other}
    if b.keys() != o.keys():
        raise ValueError("Unpaired cases")
    return dict(
        n=len(b),
        gain=sum(not b[k] and o[k] for k in b),
        loss=sum(b[k] and not o[k] for k in b),
        both=sum(b[k] and o[k] for k in b),
        neither=sum(not b[k] and not o[k] for k in b),
    )


def calculate(calls, models):
    cases = read_rows(DATA / "inputs.jsonl")
    answers = {r["id"]: r for r in read_rows(DATA / "answers.jsonl")}
    vision = {r["id"]: r for r in read_rows(DATA / "vision.jsonl")}
    assert set(answers) == {c["id"] for c in cases} and len(cases) == 36
    assert all(read_table(v["boxes"]) == v["rows"] for v in vision.values())
    grouped = {}
    for record in calls:
        k = record["model"], record["id"]
        table = grouped.setdefault(k, {})
        assert record["method"] not in table
        table[record["method"]] = record
    results = []
    matched = {}
    for model in models:
        for c in cases:
            key = c["id"]
            table = grouped[model, key]
            primary = table["schema"]
            verify = set()
            for method in ["plain", "schema", "program", "review", "feedback"] + (
                ["rows"] if c["domain"] == "invoice" else []
            ):
                initial = None
                if method in ("review", "feedback"):
                    if primary["status"] != "ok":
                        continue
                    initial = primary["text"]
                req = request(c, method, vision.get(key, {}).get("rows", []), initial)
                if req is None:
                    continue
                record = table[method]
                verify.add(method)
                assert record["request_sha256"] == fingerprint(req)
                if record["status"] == "ok":
                    assert record["transcript_model"] == model
                if model == "pcc":
                    assert record["quota_before"] == "below" and record[
                        "quota_after"
                    ] in ("below", "approaching", "reached", "unavailable", "unknown")
                if method not in ("review", "feedback"):
                    old = matched.setdefault((key, method), record["request_sha256"])
                    assert old == record["request_sha256"]
            assert set(table) == verify
            for method in strategies(c["domain"]):
                row = outcome(c, method, table, vision, answers[key])
                results.append(dict(model=model, **row))
    assert len(grouped) == len(cases) * len(models)
    summaries = {}
    for model in models:
        totals = [r for r in results if r["model"] == model]
        by_domain = {}
        for domain in ("all", "allocation", "timeline", "invoice"):
            selected = [r for r in totals if domain == "all" or r["domain"] == domain]
            plain = [r for r in selected if r["method"] == "plain"]
            schema = [r for r in selected if r["method"] == "schema"]
            methods = {}
            for method in strategies(domain):
                r = [v for v in selected if v["method"] == method]
                first = [
                    v["first_stdout_s"] for v in r if v["first_stdout_s"] is not None
                ]
                methods[method] = dict(
                    n=len(r),
                    exact=sum(v["exact"] for v in r),
                    abstain=sum(v["abstain"] for v in r),
                    bare_json=sum(v["raw_json"] is True for v in r),
                    ir_exact=sum(v["ir_exact"] is True for v in r)
                    if method in ("code", "program")
                    else None,
                    calls=sum(v["calls"] for v in r),
                    median_active_s=median(v["active_s"] for v in r),
                    median_first_s=median(first) if first else None,
                    versus_plain=paired(plain, r),
                    versus_schema=paired(schema, r),
                )
            by_domain[domain] = methods
        errors = {}
        review = [r for r in totals if r["method"] == "review"]
        feedback = [r for r in totals if r["method"] == "feedback"]
        trigger = {r["id"] for r in feedback if r["trigger"]}
        blind = [r for r in review if r["id"] in trigger]
        informed = [r for r in feedback if r["id"] in trigger]
        initial = [r for r in totals if r["method"] == "schema" and r["id"] in trigger]
        errors["triggered"] = len(trigger)
        errors["blind_vs_initial"] = paired(initial, blind)
        errors["informed_vs_initial"] = paired(initial, informed)
        errors["informed_vs_blind"] = paired(blind, informed)
        errors["undetected_wrong"] = sum(
            r["method"] == "schema" and not r["exact"] and r["id"] not in trigger
            for r in totals
        )
        subset = [r for r in calls if r["model"] == model]
        summaries[model] = dict(
            domains=by_domain,
            validation=errors,
            actual_calls=len(subset),
            status=dict(Counter(r["status"] for r in subset)),
            quota_before=dict(
                Counter(r["quota_before"] for r in subset if r["quota_before"])
            ),
            quota_after=dict(
                Counter(r["quota_after"] for r in subset if r["quota_after"])
            ),
            usage_reported=sum(r["usage"] is not None for r in subset),
        )
    return results, dict(
        protocol_sha256=sha(HERE / "lock.json"),
        models=summaries,
        matched_initial_requests=len(matched) if len(models) == 2 else None,
    )


def stable(row):
    # These two fields include the speed of this independent offline replay.
    return {k: v for k, v in row.items() if k not in ("active_s", "post_s")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["export", "verify"])
    ap.add_argument("--results", type=Path)
    a = ap.parse_args()
    preflight()
    if a.mode == "export":
        target = a.results or WORK / "results"
        calls = [
            json.loads(p.read_text()) for p in sorted((WORK / "raw").glob("*.json"))
        ]
        session = json.loads((WORK / "session.json").read_text())
        models = [
            m
            for m in ("system", "pcc")
            if m in session["models"]
            and len({v["id"] for v in calls if v["model"] == m}) == 36
        ]
        if not models:
            raise ValueError("No completed model panel")
        # Partial data stay in build/session for later resumption.
        calls = [r for r in calls if r["model"] in models]
        results, summary = calculate(calls, models)
        write_rows(target / "calls.jsonl", calls)
        write_rows(target / "outcomes.jsonl", results)
        write_json(target / "summary.json", summary)
    else:
        target = a.results or HERE / "results"
        calls = read_rows(target / "calls.jsonl")
        saved = json.loads((target / "summary.json").read_text())
        results, summary = calculate(calls, list(saved["models"]))
        previous = read_rows(target / "outcomes.jsonl")
        assert list(map(stable, results)) == list(map(stable, previous))
        for m, by in summary["models"].items():
            for d, methods in by["domains"].items():
                for arm, stats in methods.items():
                    matching = [
                        r
                        for r in previous
                        if r["model"] == m
                        and r["method"] == arm
                        and (d == "all" or r["domain"] == d)
                    ]
                    stats["median_active_s"] = median(r["active_s"] for r in matching)
        assert saved == summary
    print(f"{a.mode}: {len(calls)} calls, {len(results)} outcomes")


if __name__ == "__main__":
    main()
