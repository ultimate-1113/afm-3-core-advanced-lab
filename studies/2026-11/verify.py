"""Check the public export against the locked cases and actual CLI outputs, offline."""

from collections import defaultdict
import argparse
import json
from pathlib import Path
from evaluate import dataset, methods
from report import read
from tasks import delivery_code, grade, parse_json


def verify(out):
    fixtures, shared, old = dataset()
    cases = {c["id"]: c for c in fixtures}
    summary = json.loads((out / "summary.json").read_text())
    calls = defaultdict(list)
    for call in read(out / "calls.jsonl"):
        assert call["id"] in cases and call["model"] in ("system", "pcc")
        if call["status"] == "ok":
            assert call["model"] == call["transcript_model"]
        if call["model"] == "pcc":
            assert call["quota_before"] == "below"
        calls[call["id"], call["model"], call["method"]].append(call)
    ocr = {r["id"]: r for r in read(out / "vision.jsonl")}
    drift = {r["trial"]: r for r in read(out / "vision-differences.jsonl")}
    checks = set()
    nonidentical = []
    resolved = []
    for r in read(out / "cases.jsonl"):
        c = cases[r["id"]]
        d = c["domain"]
        m = r["method"]
        model = r["model"]
        key = (r["id"], model, m)
        assert key not in checks
        checks.add(key)
        records = sorted(calls.get(key, []), key=lambda v: v["step"])
        assert [v["step"] for v in records] == list(range(r["steps"]))
        if m == "code":
            source = drift.get("ocr-system-" + r["id"] + "-" + m, ocr[r["id"]])
            answer = delivery_code(c["payload"], source)
        elif m == "step":
            parsed = [parse_json(x["text"]) for x in records]
            answer = (
                {"actions": [a for x in parsed for a in x["actions"]]}
                if all(
                    isinstance(x, dict) and isinstance(x.get("actions"), list)
                    for x in parsed
                )
                else None
            )
        else:
            answer = parse_json(records[0]["text"])
        assert answer == r["answer"], key
        if d == "regression":
            raw = records[0]
            g = old.grade(
                c["payload"], {"text": raw["text"], "status": raw["status"]}, "baseline"
            )
            assert (
                g["pass"] == r["grade"]["exact"] and g["fields"] == r["grade"]["fields"]
            ), key
        else:
            g = grade(c, m, answer)
            if any(x["status"] != "ok" for x in records):
                g["exact"] = False
            assert g == r["grade"], key
        if model == "pcc" and c["id"] in shared and records:
            counterpart = calls[c["id"], "system", m]
            assert counterpart, key
            if (
                min(counterpart, key=lambda x: x["step"])["request_sha256"]
                != records[0]["request_sha256"]
            ):
                nonidentical.append(key)
            resolved.append(key)
    expected = {
        (c["id"], "code" if m == "code" else model, m)
        for c in fixtures
        for model in ("system", "pcc")
        if model == "system" or c["id"] in shared or c["domain"] == "long"
        for m in methods(c, model)
    }
    assert checks <= expected
    if summary["run_status"] == "finished":
        assert expected == checks
    legacy = read(out / "legacy-cases.jsonl")
    assert len({(r["id"], r["method"]) for r in legacy}) == 192
    for r in legacy:
        src = next(c for c in old.load(r["dataset"]) if c["id"] == r["id"])
        assert old.grade(src, r["result"], r["method"]) == r["grade"]
    assert len(ocr) == 40 and len(shared) == 30
    return dict(
        case_methods_regraded=len(checks),
        pending_case_methods=len(expected - checks),
        legacy_regraded=len(legacy),
        paired_method_first_inputs=len(resolved),
        different_first_inputs=nonidentical,
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("results", type=Path)
    a = p.parse_args()
    print(json.dumps(verify(a.results), ensure_ascii=False, indent=2))
