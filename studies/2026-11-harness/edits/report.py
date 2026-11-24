"""Score edits against the version present when the request is committed."""

import argparse
import json
import os
from pathlib import Path
from statistics import median
import time
import re
from sheet import req, apply, scenarios
from common import read_rows, write_json, write_rows, sha
from protocol import unpack
from run import fingerprint

LOCAL = Path(__file__).resolve().parent
WORK = Path(os.environ.get("AFM_HARNESS_WORK", LOCAL / "build/session"))
METHODS = (
    "plain",
    "full",
    "patch",
    "full_hold",
    "patch_hold",
    "full_read",
    "patch_read",
    "rules_read",
)


def rules(ticket, lines):
    m = re.match(r"([^の]+)の([^をが]+)[をが]", ticket)
    if not m:
        return None
    section = "[" + m[1] + "]"
    key = m[2]
    if lines.count(section) != 1:
        return None
    start = lines.index(section) + 1
    end = next(
        (i for i in range(start, len(lines)) if lines[i].startswith("[")), len(lines)
    )
    hit = [
        i for i in range(start, end) if re.fullmatch(re.escape(key) + r"=\d+", lines[i])
    ]
    if len(hit) != 1:
        return None
    i = hit[0]
    value = int(lines[i].split("=")[1])
    relative = re.search(r"値から(\d+)増やす", ticket)
    conditional = re.search(r"が(\d+)のときだけ(\d+)に変更", ticket)
    absolute = re.search(r"を(\d+)に設定", ticket)
    if relative:
        value += int(relative[1])
    elif conditional:
        if value == int(conditional[1]):
            value = int(conditional[2])
    elif absolute:
        value = int(absolute[1])
    else:
        return None
    updated = list(lines)
    updated[i] = f"{key}={value}"
    return updated


def judge(c, g, method, records):
    start = time.perf_counter()
    live = c["live"]
    snapshot = c["public"]["snapshot"]
    changed = live != snapshot
    invoked = []
    if method == "rules_read":
        lines = rules(c["public"]["ticket"], live)
        message = "rules" if lines is not None else "unsupported"
    else:
        arm = method.split("_")[0]
        invoked = [records[arm]]
        if changed and method.endswith("_hold"):
            lines, message = None, "stale_version"
        else:
            if changed and method.endswith("_read"):
                invoked.append(records["fresh_" + arm])
            current = invoked[-1]
            if current["status"] == "ok":
                lines, message = apply(live, current["text"], arm)
            else:
                lines, message = None, current["status"]
    post = time.perf_counter() - start
    i = g["target_index"]
    ok = lines is not None and lines == g["lines"]
    collateral = lines is not None and (
        len(lines) != len(live)
        or lines[:i] + lines[i + 1 :] != live[:i] + live[i + 1 :]
    )
    lost = lines is not None and any(
        j != i and snapshot[j] != v and (j >= len(lines) or lines[j] != v)
        for j, v in enumerate(live)
    )
    return dict(
        id=c["id"],
        method=method,
        kind=c["kind"],
        exact=ok,
        held=lines is None,
        wrong_applied=lines is not None and not ok,
        collateral=collateral,
        lost_other_edit=lost,
        result=lines,
        disposition=message,
        calls=len(invoked),
        call_methods=[r["method"] for r in invoked],
        active_s=post + sum(r["cli_e2e_s"] + r["prep_s"] for r in invoked),
        post_s=post,
    )


def compute(calls):
    inputs = read_rows(LOCAL / "fixtures/inputs.jsonl")
    gold = {r["id"]: r for r in read_rows(LOCAL / "fixtures/answers.jsonl")}
    rows = []
    for model in sorted({x["model"] for x in calls}):
        grouped = {(x["id"], x["method"]): x for x in calls if x["model"] == model}
        expected = set()
        for c in inputs:
            modes = ["plain", "full", "patch"]
            if c["live"] != c["public"]["snapshot"]:
                modes += ["fresh_full", "fresh_patch"]
            records = {}
            for mode in modes:
                k = c["id"], mode
                expected.add(k)
                rec = grouped[k]
                assert rec["request_sha256"] == fingerprint(req(c, mode))
                if rec["status"] == "ok":
                    assert rec["transcript_model"] == model
                records[mode] = rec
            rows.extend(
                dict(model=model, **judge(c, gold[c["id"]], method, records))
                for method in METHODS
            )
        assert set(grouped) == expected and len(expected) == sum(
            x["model"] == model for x in calls
        )
    return rows


def summarize(rows):
    result = {}
    for model in sorted({r["model"] for r in rows}):
        summary = {}
        for mode in METHODS:
            found = [r for r in rows if r["model"] == model and r["method"] == mode]
            if not found:
                continue
            summary[mode] = {
                k: sum(r[k] for r in found)
                for k in (
                    "exact",
                    "held",
                    "wrong_applied",
                    "collateral",
                    "lost_other_edit",
                    "calls",
                )
            }
            summary[mode].update(
                n=len(found), median_active_s=median(r["active_s"] for r in found)
            )
        result[model] = summary
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["export", "verify"])
    ap.add_argument("--results", type=Path)
    a = ap.parse_args()
    path = a.results or (WORK / "results" if a.mode == "export" else LOCAL / "results")
    if a.mode == "export":
        calls = [
            json.loads(f.read_text()) for f in sorted((WORK / "raw").glob("*.json"))
        ]
        rows = compute(calls)
        write_rows(path / "calls.jsonl", calls)
        write_rows(path / "outcomes.jsonl", rows)
        write_json(path / "summary.json", summarize(rows))
    else:
        calls = read_rows(path / "calls.jsonl")
        rows = compute(calls)
        old = read_rows(path / "outcomes.jsonl")
        assert len(rows) == len(old) and rows
        for row, prior in zip(rows, old):
            for key in row.keys() - {"active_s", "post_s"}:
                assert row[key] == prior[key], (row["id"], key)
        assert summarize(old) == json.loads((path / "summary.json").read_text())
    print(f"{a.mode}: {len(calls)} calls, {len(rows)} scored edits")


if __name__ == "__main__":
    main()
