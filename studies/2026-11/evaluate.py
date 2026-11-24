"""Run the frozen evaluation from Apple's Terminal. Resume with the same work directory."""

import argparse
import fcntl
import importlib.util
import json
import random
import statistics
import subprocess
import sys
import time
import tempfile
from pathlib import Path
from fixtures import DATA, HERE, KINDS, digest, js, write_json
from tasks import (
    METHODS,
    apply_actions,
    delivery_code,
    delivery_request,
    grade,
    long_request,
    notice_request,
    parse_json,
    select_paragraphs,
    update_request,
)
from fm_client import Client, Pause, available, clock

REPO = HERE.parents[1]


def legacy_module():
    spec = importlib.util.spec_from_file_location(
        "october_lab", REPO / "scripts/lab.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def dataset():
    locks = json.loads((DATA / "lock.json").read_text())
    for rel, expected in locks.items():
        if digest(DATA / rel) != expected:
            raise ValueError("Fixture differs: " + rel)
    raw = [json.loads(x) for x in (DATA / "cases.jsonl").read_text().splitlines()]
    old = legacy_module()
    for c in old.load("regressions"):
        raw.append(
            dict(
                id=c["id"],
                domain="regression",
                split="regression",
                family=c["id"],
                condition="baseline",
                payload=c,
                expected=c["expected"],
            )
        )
    shared = json.loads((DATA / "shared.json").read_text())
    if len(set(shared)) != 30 or not set(shared) <= {c["id"] for c in raw}:
        raise ValueError("Invalid common panel")
    return raw, set(shared), old


def evaluate(c, model, method, client, cache, old, vision, captured_ocr=None):
    key = "/".join([model, c["id"], method])
    if client.db.execute("select 1 from cases where key=?", (key,)).fetchone():
        return
    p = c["payload"]
    domain = c["domain"]
    calls = []
    ocr = None
    pre = 0.0
    selection = None
    start = time.perf_counter()
    inside_ask = 0.0
    same_ocr = None
    if domain == "delivery" and method != "image":
        mode = "flat" if method == "flat" else "table"
        frozen = json.loads((cache / (c["id"] + ".json")).read_text())
        if captured_ocr is None:
            with tempfile.TemporaryDirectory(dir=client.work) as folder:
                output = Path(folder) / "ocr.json"
                subprocess.run(
                    [vision, mode, DATA / p["image"], output], check=True, timeout=150
                )
                ocr = json.loads(output.read_text())
        else:
            ocr = captured_ocr
        attr = "flat" if mode == "flat" else "tables"
        same_ocr = ocr[attr] == frozen[attr]
        pre = time.perf_counter() - start
        if not same_ocr:
            write_json(
                client.work / ("ocr-" + model + "-" + c["id"] + "-" + method + ".json"),
                ocr,
            )

    def ask(req):
        nonlocal inside_ask
        t = time.perf_counter()
        msg = client.generate(c["id"], model, method, len(calls), req)
        inside_ask += time.perf_counter() - t
        calls.append(msg)
        return parse_json(msg["text"])

    if domain == "notice":
        answer = ask(notice_request(p, method))
    elif domain == "delivery":
        answer = (
            delivery_code(p, ocr)
            if method == "code"
            else ask(delivery_request(p, method, ocr))
        )
    elif domain == "update":
        if method == "batch":
            answer = ask(update_request(p))
        else:
            history = []
            state = dict(p["initial"])
            valid = True
            for idx in range(len(p["requests"])):
                step = ask(update_request(p, history, state, idx))
                if not isinstance(step, dict) or not isinstance(
                    step.get("actions"), list
                ):
                    valid = False
                    break
                state, _ = apply_actions(state, step["actions"])
                history.extend(step["actions"])
            answer = {"actions": history} if valid else None
    elif domain == "regression":
        original = old.request(p, "baseline")
        answer = ask(
            {
                "prompt": original["prompt"],
                "instructions": original["instructions"],
                "schema": None,
                "image": None,
            }
        )
    elif domain == "long":
        if method == "select":
            docs, selection = select_paragraphs(p)
        else:
            docs = p["paragraphs"]
        answer = ask(long_request(p, docs))
    else:
        raise ValueError(domain)
    if domain == "regression":
        old_grade = old.grade(
            p, {"text": calls[0]["text"], "status": calls[0]["status"]}, "baseline"
        )
        scores = {
            "exact": old_grade["pass"],
            "format": old_grade["format"],
            "semantic": old_grade["semantic"],
            "fields": old_grade["fields"],
        }
    else:
        scores = grade(c, method, answer)
    if any(r["status"] != "ok" for r in calls):
        scores["exact"] = False
    host = time.perf_counter() - start
    generation = sum(r["cli_e2e_s"] for r in calls)
    # Includes live OCR/selection, parsing and scoring. Quota checks and checkpoint I/O
    # occur inside generate() and are excluded from this active request duration.
    active = max(0, host - inside_ask) + generation
    first = calls[0]["first_stdout_s"] if calls else None
    row = dict(
        id=c["id"],
        domain=domain,
        split=c["split"],
        family=c["family"],
        condition=c["condition"],
        model=("code" if method == "code" else model),
        method=method,
        grade=scores,
        answer=answer,
        steps=len(calls),
        source_indexes=selection,
        vision_preprocess_s=pre,
        ocr_matches_frozen=same_ocr,
        first_stdout_s=first,
        model_e2e_s=generation,
        host_run_s=host,
        active_e2e_s=active,
        status="complete",
        recorded=clock(),
    )
    with client.db:
        client.db.execute("insert into cases values(?,?)", (key, js(row)))
    print(
        f"{model:6} {c['id']:20} {method:9} {'pass' if scores['exact'] else 'miss'}",
        flush=True,
    )


def methods(c, model):
    d = c["domain"]
    if d == "regression":
        return ["baseline"]
    if d == "long":
        return ["select" if model == "system" and c["condition"] != "4000" else "full"]
    return [m for m in METHODS[d] if model == "system" or m != "code"]


def tuning(client):
    rows = [json.loads(r[0]) for r in client.db.execute("select payload from cases")]
    choice = {}
    for d in KINDS:
        ranks = []
        for m in METHODS[d]:
            if m == "code":
                continue
            grp = [
                r
                for r in rows
                if r["domain"] == d and r["split"] == "dev" and r["method"] == m
            ]
            if len(grp) != 10:
                raise ValueError("Incomplete tuning set: " + d + "/" + m)
            ranks.append(
                (
                    -sum(r["grade"]["exact"] for r in grp),
                    sum(r["steps"] for r in grp),
                    statistics.median(r["active_e2e_s"] for r in grp),
                    m,
                )
            )
        choice[d] = min(ranks)[-1]
    return choice


def export(client, work):
    for table, name in (("calls", "calls"), ("cases", "cases")):
        records = [
            json.loads(row[0])
            for row in client.db.execute(
                "select payload from " + table + " order by key"
            )
        ]
        dest = work / (name + ".jsonl")
        tmp = dest.with_suffix(".new")
        tmp.write_text("".join(js(r) + "\n" for r in records))
        tmp.replace(dest)


def execute(work, cache, only, vision):
    raw, shared, old = dataset()
    client = Client(work)
    fixture_lock = digest(DATA / "lock.json")
    if client.setting("fixture-hash") not in (None, fixture_lock):
        raise RuntimeError("Incompatible fixtures in checkpoint")
    client.put_setting("fixture-hash", fixture_lock)
    models = ("system", "pcc") if only == "both" else (only,)
    state = dict(
        status="running", started=clock(), models={}, fixture_lock=fixture_lock
    )
    try:
        for model in models:
            state["models"][model] = available(model)
            for phase in (
                ("dev", "held", "regression", "long")
                if model == "system"
                else ("regression", "held", "long")
            ):
                items = [
                    c
                    for c in raw
                    if c["split"] == phase
                    and (model == "system" or c["id"] in shared or phase == "long")
                ]
                random.Random(20261124).shuffle(items)
                for c in items:
                    order = methods(c, model)
                    random.Random(c["id"]).shuffle(order)
                    for m in order:
                        evaluate(c, model, m, client, cache, old, vision)
                if phase == "dev":
                    write_json(work / "selected.json", tuning(client))
                export(client, work)
        state["status"] = "finished" if only == "both" else only + "_complete"
    except Pause as exc:
        state.update(status="paused", reason=str(exc))
    except BaseException as exc:
        state.update(status="error", reason=type(exc).__name__)
        raise
    finally:
        export(client, work)
        state["ended"] = clock()
        state["case_methods"] = client.db.execute(
            "select count(*) from cases"
        ).fetchone()[0]
        write_json(work / "status.json", state)
        client.db.close()
        print(js(state), flush=True)
    return (
        0 if state["status"] in ("finished", "system_complete", "pcc_complete") else 2
    )


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--work", type=Path, default=HERE / "build" / "session")
    p.add_argument("--ocr", type=Path, default=HERE / "build" / "vision-cache")
    p.add_argument("--vision", type=Path, default=HERE / "build" / "vision-tool")
    p.add_argument("--only", choices=["both", "system", "pcc"], default="both")
    a = p.parse_args()
    a.work.mkdir(parents=True, exist_ok=True)
    with (a.work / "exclusive.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit("An evaluation is already running in this directory.")
        return execute(a.work, a.ocr, a.only, a.vision.resolve())


if __name__ == "__main__":
    sys.exit(main())
