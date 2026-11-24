"""Offline outcome construction. Answers are read only in the reporting process."""

import time
from engine import execute, code_ir
from protocol import PANEL, unpack, canonical, checks


def outcome(case, method, calls, vision, gold):
    d, p = case["domain"], case["payload"]
    image = vision.get(case["id"], {})
    rows = image.get("rows", [])
    uses_ocr = d == "invoice" and method in ("code", "program", "rows")
    started = time.perf_counter()
    records = []
    flags = []
    inter = None
    strict = False
    status = "ok"
    trigger = None
    if method == "code":
        inter = code_ir(d, p, rows)
        answer = execute(d, p, rows, inter)
    else:
        if method in ("review", "feedback", "guard"):
            initial = calls["schema"]
            records.append(initial)
            a0, _ = unpack(initial["text"])
            flags = checks(d, p, a0)
            trigger = bool(flags)
            if initial["status"] == "ok" and (method == "review" or trigger):
                records.append(calls["review" if method == "review" else "feedback"])
        else:
            records.append(calls[method])
        result = records[-1]
        status = result["status"]
        parsed, strict = unpack(result["text"])
        if method == "program":
            inter = parsed
            answer = execute(d, p, rows, parsed)
        else:
            answer = canonical(d, p, parsed)
            if method == "guard" and checks(d, p, parsed):
                answer = None
    process_s = time.perf_counter() - started
    # Frozen OCR is acquired once. Charge its full measured time to each equivalent standalone use.
    ocr_s = image.get("seconds", 0) if uses_ocr else 0
    prep_s = sum(r["prep_s"] for r in records)
    cli_s = sum(r["cli_e2e_s"] for r in records)
    return dict(
        id=case["id"],
        domain=d,
        method=method,
        answer=answer,
        exact=answer is not None and answer == gold["answer"],
        fields={
            k: answer is not None and answer.get(k) == v
            for k, v in gold["answer"].items()
        },
        raw_json=(strict if records else None),
        contract=(answer is not None),
        ir_exact=(inter == gold["ir"] if method in ("code", "program") else None),
        ir=inter,
        abstain=answer is None,
        status=status,
        diagnostics=flags,
        trigger=trigger,
        calls=len(records),
        call_methods=[r["method"] for r in records],
        ocr_s=ocr_s,
        cli_s=cli_s,
        prep_s=prep_s,
        post_s=process_s,
        active_s=cli_s + ocr_s + prep_s + process_s,
        first_stdout_s=records[0]["first_stdout_s"] if records else None,
    )


def strategies(domain):
    return [*PANEL, "guard"] + (["rows"] if domain == "invoice" else [])
