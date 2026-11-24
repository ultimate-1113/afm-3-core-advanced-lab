"""Run and replay the real on-device model on the guarded editing study."""

import argparse
from collections import Counter
from dataclasses import asdict
import fcntl
import hashlib
import json
from pathlib import Path
import random
from statistics import median
import sys
import time

from guard import Sheet, Snapshot, target_for_model, update
from model import CONTRACT, scoped_request

LOCAL = Path(__file__).resolve().parent
OLD = LOCAL.parent / "edits"
sys.path.insert(0, str(OLD))
from sheet import req as original_request, apply as original_apply
from common import clock, js, read_rows, sha, write_json, write_rows
from fm_client import Client, available
from protocol import unpack
from run import fingerprint as old_hash

MODES = ("baseline", "scope", "checked", "scoped", "rules")
FIXED = [
    "design.md",
    "guard.py",
    "study.py",
    "panel.py",
    "model.py",
    "apply_edit.py",
    "fixtures/inputs.jsonl",
    "fixtures/answers.jsonl",
    "../edits/fixtures/inputs.jsonl",
    "../edits/fixtures/answers.jsonl",
    "../edits/results/calls.jsonl",
    "../edits/sheet.py",
    "../run.py",
    "../protocol.py",
    "../common.py",
    "../../2026-11/fm_client.py",
    "../../2026-11/tasks.py",
    "../../2026-11/fixtures.py",
]
WORK = LOCAL / "build/session"


def freeze():
    dest = LOCAL / "lock.json"
    if dest.exists():
        raise SystemExit("A frozen protocol exists.")
    write_json(dest, {name: sha(LOCAL / name) for name in FIXED})


def verify_lock():
    expected = json.loads((LOCAL / "lock.json").read_text())
    if set(expected) != set(FIXED):
        raise ValueError("Missing frozen inputs")
    for name, checksum in expected.items():
        if sha(LOCAL / name) != checksum:
            raise ValueError("Changed protocol file: " + name)
    return sha(LOCAL / "lock.json")


def inputs():
    rows = read_rows(OLD / "fixtures/inputs.jsonl") + read_rows(
        LOCAL / "fixtures/inputs.jsonl"
    )
    if len({r["id"] for r in rows}) != len(rows):
        raise ValueError("Duplicate case ID")
    return rows


def history(c):
    first = c["public"]["snapshot"]
    views = [("", Snapshot(0, tuple(first)))]
    if first != c["live"]:
        views.append(("fresh_", Snapshot(1, tuple(c["live"]))))
    return views


def requests(c):
    ticket = c["public"]["ticket"]
    for prefix, view in history(c):
        mode = prefix + "patch"
        req = original_request(c, mode)
        if not c["id"].startswith("edit-"):
            req["instructions"] += " " + CONTRACT + " 見送りはeditsを空配列にする。"
        yield mode, req
        cell = target_for_model(ticket, view)
        if cell is not None:
            yield prefix + "scoped", scoped_request(ticket, cell)


def legacy_calls():
    return {
        (r["id"], r["method"]): r
        for r in read_rows(OLD / "results/calls.jsonl")
        if r["model"] == "system" and r["method"] in ("patch", "fresh_patch")
    }


def new_hash(req):
    return hashlib.sha256(js([req["instructions"], req]).encode()).hexdigest()


def schedule():
    cases = inputs()
    random.Random(2026112421).shuffle(cases)
    for c in cases:
        groups = {}
        for m, req in requests(c):
            groups.setdefault(m.startswith("fresh_"), []).append((c["id"], m, req))
        for fresh, group in groups.items():
            random.Random(c["id"] + str(fresh)).shuffle(group)
            yield from group


def generate():
    lock = verify_lock()
    WORK.mkdir(parents=True, exist_ok=True)
    with (WORK / "active.lock").open("a") as excl:
        fcntl.flock(excl, fcntl.LOCK_EX | fcntl.LOCK_NB)
        client = Client(WORK)
        try:
            if client.setting("lock") not in (None, lock):
                raise ValueError("Session belongs to another study")
            name = available("system")
            client.put_setting("lock", lock)
            local = []
            old = legacy_calls()
            started = client.setting("started") or clock()
            client.put_setting("started", started)
            jobs = list(schedule())
            write_json(
                WORK / "status.json",
                dict(status="running", started=started, model=name, protocol=lock),
            )
            for cid, m, req in jobs:
                if (cid, m) in old:
                    r = old[cid, m]
                    assert (
                        r["status"] == "ok"
                        and r["transcript_model"] == "system"
                        and r["request_sha256"] == old_hash(req)
                    )
                    continue
                row = client.generate(cid, "system", m, 0, req)
                local.append(row)
                print(f"{len(local)}/{len(jobs) - len(old)} {cid} {m}", flush=True)
            write_rows(WORK / "calls.jsonl", local)
            write_json(
                WORK / "status.json",
                dict(
                    status="finished",
                    started=started,
                    ended=clock(),
                    model=name,
                    protocol=lock,
                    new_calls=len(local),
                    replayed=len(old),
                ),
            )
        except Exception as e:
            write_json(
                WORK / "status.json",
                dict(status="interrupted", detail=type(e).__name__, ended=clock()),
            )
            raise
        finally:
            client.db.close()


class DuringRead(Sheet):
    """Inject a concurrent commit after the first observation, independent of the model."""

    def __init__(self, c):
        super().__init__(c["public"]["snapshot"])
        self.upcoming = c["live"]

    def commit(self, *args, **kwargs):
        if self.upcoming is not None:
            self.external_edit(self.upcoming)
            self.upcoming = None
        return super().commit(*args, **kwargs)


def attempt(c, mode, records):
    start = time.perf_counter()
    used = []
    ticket = c["public"]["ticket"]

    def get(m):
        r = records[m]
        used.append(r)
        return r

    if mode == "baseline":
        which = "patch"
        r = get(which)
        if c["public"]["snapshot"] != c["live"]:
            r = get("fresh_patch")
        if r["status"] == "ok":
            lines, reason = original_apply(c["live"], r["text"], "patch")
        else:
            lines, reason = None, r["status"]
        status = (
            "held" if lines is None else "noop" if lines == c["live"] else "applied"
        )
        final = c["live"] if lines is None else lines
    else:
        sheet = DuringRead(c)

        def propose(view, cell):
            m = ("fresh_" if view.revision else "") + (
                "patch" if cell is None else "scoped"
            )
            r = get(m)
            return unpack(r["text"])[0] if r["status"] == "ok" else None

        receipt = update(sheet, c["id"], ticket, mode, propose)
        status, reason = receipt.status, receipt.reason
        final = list(sheet.read().lines)
    post = time.perf_counter() - start
    return dict(
        method=mode,
        status=status,
        reason=reason,
        final=final,
        call_methods=[r["method"] for r in used],
        calls=len(used),
        cli_s=sum(r["cli_e2e_s"] for r in used),
        harness_s=post,
    )


def changes(before, after):
    return {
        i
        for i in range(max(len(before), len(after)))
        if before[i : i + 1] != after[i : i + 1]
    }


def score(c, g, out):
    held = out["status"] == "held"
    diff = changes(c["live"], out["final"])
    assert not held or not diff
    complete = g["decision"] == "complete"
    exact = complete and not held and out["final"] == g["lines"]
    wrong_accepted = not held and not exact
    targets = {g["index"]} if complete else set()
    foreign = changes(c["public"]["snapshot"], c["live"]) - targets
    return dict(
        id=c["id"],
        panel="regression"
        if c["id"].startswith("edit-")
        else "actionable"
        if complete
        else "needs_review",
        language=g["language"],
        operation=g["operation"],
        **out,
        exact=exact,
        held=held,
        correct_review=not complete and held,
        wrong_accepted=wrong_accepted,
        wrong_write=wrong_accepted and bool(diff),
        wrong_no_write=wrong_accepted and not diff,
        outside_target=bool(diff - targets),
        lost_other_edit=bool(foreign & diff),
        active_s=out["cli_s"] + out["harness_s"],
    )


def reference():
    g = {
        r["id"]: dict(
            id=r["id"],
            lines=r["lines"],
            index=r["target_index"],
            decision="complete",
            language="regression",
            operation="prior",
        )
        for r in read_rows(OLD / "fixtures/answers.jsonl")
    }
    g.update({r["id"]: r for r in read_rows(LOCAL / "fixtures/answers.jsonl")})
    return g


def evaluate(new):
    legacy = legacy_calls()
    records = {**legacy}
    for r in new:
        key = r["id"], r["method"]
        if key in records:
            raise ValueError("Duplicate response")
        if r["model"] != "system" or (
            r["status"] == "ok" and r["transcript_model"] != "system"
        ):
            raise ValueError("Unexpected transport model")
        records[key] = r
    expected = set()
    for cid, m, req in schedule():
        expected.add((cid, m))
        r = records[cid, m]
        sig = old_hash(req) if (cid, m) in legacy else new_hash(req)
        if sig != r["request_sha256"]:
            raise ValueError("Response and prompt differ: " + cid + "/" + m)
    if expected != set(records):
        raise ValueError("Unexpected responses")
    gold = reference()
    result = []
    for c in inputs():
        grouped = {m: r for (cid, m), r in records.items() if cid == c["id"]}
        for mode in MODES:
            result.append(score(c, gold[c["id"]], attempt(c, mode, grouped)))
    return result


COUNTS = (
    "exact",
    "held",
    "correct_review",
    "wrong_accepted",
    "wrong_write",
    "wrong_no_write",
    "outside_target",
    "lost_other_edit",
    "calls",
)


def summarize(rows):
    summary = {}
    for category in ("regression", "actionable", "needs_review"):
        base = {
            r["id"]: r
            for r in rows
            if r["method"] == "baseline" and r["panel"] == category
        }
        methods = {}
        for mode in MODES:
            sample = [r for r in rows if r["panel"] == category and r["method"] == mode]
            methods[mode] = dict(
                n=len(sample),
                **{k: sum(r[k] for r in sample) for k in COUNTS},
                gained=sum(r["exact"] and not base[r["id"]]["exact"] for r in sample),
                lost=sum(not r["exact"] and base[r["id"]]["exact"] for r in sample),
                median_active_s=median(r["active_s"] for r in sample),
                holds=dict(Counter(r["reason"] for r in sample if r["held"])),
            )
        summary[category] = methods
    return summary


def report(output, replay):
    verify_lock()
    calls = read_rows((output if replay else WORK) / "calls.jsonl")
    rows = evaluate(calls)
    if replay:
        saved = read_rows(output / "outcomes.jsonl")
        if len(saved) != len(rows):
            raise ValueError("Outcome count differs")
        for r, old in zip(rows, saved):
            for k in r.keys() - {"active_s", "harness_s"}:
                if r[k] != old[k]:
                    raise ValueError((r["id"], r["method"], k))
        assert summarize(saved) == json.loads((output / "summary.json").read_text())
    else:
        write_rows(output / "calls.jsonl", calls)
        write_rows(output / "outcomes.jsonl", rows)
        write_json(output / "summary.json", summarize(rows))
    print(
        f"{len(calls)} new calls, {len(legacy_calls())} prior responses, {len(rows)} outcomes"
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["freeze", "generate", "export", "verify"])
    ap.add_argument("--results", type=Path, default=None)
    a = ap.parse_args()
    if a.mode == "freeze":
        freeze()
    elif a.mode == "generate":
        generate()
    else:
        report(
            a.results
            or (LOCAL / "results" if a.mode == "verify" else WORK / "results"),
            a.mode == "verify",
        )


if __name__ == "__main__":
    main()
