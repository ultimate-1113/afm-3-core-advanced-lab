"""One lock-protected real Terminal session. No answer key is loaded for inference."""

import argparse
from datetime import date
import hashlib
import json
import os
from pathlib import Path
import random
import re
import sys
import time
from common import (
    DATA,
    HERE,
    ESC,
    clock,
    decode,
    js,
    quota_state,
    read_rows,
    sha,
    write_json,
)
from protocol import request

WORK = Path(os.getenv("AFM_HARNESS_WORK", HERE / "build/session")).resolve()
PART = WORK / "terminal"
RAW = WORK / "raw"
NAMES = {"system": "AFM 3 Core Advanced", "pcc": "AFM 3 Cloud"}


def today():
    return date.today().isoformat()


def state(status, reason=None):
    data = dict(status=status, time=clock(), completed=len(list(RAW.glob("*.json"))))
    if reason:
        data["reason"] = reason
    write_json(WORK / "status.json", data)


class Pause(Exception):
    pass


def preflight():
    manifest = json.loads((HERE / "lock.json").read_text())
    amendment = json.loads((HERE / "provenance/transport.json").read_text())
    original = {
        "run.py": ("provenance/transport-v1.py.txt", "run_sha256"),
        "Run Harness.command": ("provenance/launcher-v1.zsh.txt", "launcher_sha256"),
    }
    for name, expected in manifest["sha256"].items():
        if name in original:
            archived, current = original[name]
            if sha(HERE / archived) != expected:
                raise ValueError(
                    "Original transport no longer matches the preregistration"
                )
            expected = amendment[current]
        if sha(HERE / name) != expected:
            raise ValueError("Changed frozen file: " + name)
    return sha(HERE / "lock.json")


def save_text(name, value):
    (PART / name).write_text(value)


def path(model, cid, method):
    if (
        model not in NAMES
        or not re.fullmatch(r"(?:allocation|timeline|invoice)-\d{2}", cid)
        or method not in ("plain", "schema", "review", "feedback", "program", "rows")
    ):
        raise ValueError("Unknown call identifier")
    return RAW / f"{cid}.{model}.{method}.json"


def fingerprint(req):
    image_hash = sha(DATA / req["image"]) if req["image"] else None
    return hashlib.sha256(js([req, image_hash]).encode()).hexdigest()


def order(cases, models):
    rng = random.Random(2026112402)
    cases = list(cases)
    rng.shuffle(cases)
    jobs = []
    for i, c in enumerate(cases):
        first = ["plain", "schema", "program"]
        if c["domain"] == "invoice":
            first.append("rows")
        rng.shuffle(first)
        revisions = ["review", "feedback"]
        rng.shuffle(revisions)
        for j, method in enumerate(first + revisions):
            group = list(models)
            if (i + j) % 2:
                group.reverse()
            jobs.extend(" ".join([m, c["id"], method]) for m in group)
    return jobs


def evidence():
    return {c["id"]: c for c in read_rows(DATA / "inputs.jsonl")}, {
        c["id"]: c["rows"] for c in read_rows(DATA / "vision.jsonl")
    }


def init(which):
    lock = preflight()
    recover_quota()
    PART.mkdir(parents=True, exist_ok=True)
    RAW.mkdir(parents=True, exist_ok=True)
    old = WORK / "session.json"
    if old.exists() and json.loads(old.read_text())["lock"] != lock:
        raise ValueError("Output directory belongs to a different protocol")
    meta = (
        json.loads(old.read_text())
        if old.exists()
        else dict(lock=lock, started=clock(), models={})
    )
    # Scope model discovery to the requested routes.
    models = list(NAMES) if which == "both" else [which]
    view = ESC.sub("", (PART / "models").read_text())
    for m in models:
        if not re.search(r"[✓✔]\s+" + m + r"\s+\(" + NAMES[m] + r"\)", view):
            raise Pause("Requested model unavailable in this Terminal: " + m)
        meta["models"][m] = NAMES[m]
    write_json(old, meta)
    cases, _ = evidence()
    save_text("sequence", "\n".join(order(cases.values(), models)) + "\n")
    state("running")


def prepare(model, cid, method):
    dest = path(model, cid, method)
    start = time.perf_counter()
    cases, vision = evidence()
    old = None
    if method in ("review", "feedback"):
        parent = json.loads(path(model, cid, "schema").read_text())
        if parent["status"] != "ok":
            return 3
        old = parent["text"]
    req = request(cases[cid], method, vision.get(cid, []), old)
    if req is None:
        return 3
    key = fingerprint(req)
    if dest.exists():
        if json.loads(dest.read_text())["request_sha256"] != key:
            raise ValueError("Saved call has different input: " + cid)
        return 3
    if (WORK / "inflight.json").exists():
        raise Pause("Inspect unfinished request in inflight.json before resuming.")
    if model == "pcc" and held_today():
        raise Pause("PCC quota warning for today")
    save_text("instructions", req["instructions"])
    save_text("prompt", req["prompt"])
    save_text("schema", js(req["schema"]) if req["schema"] else "")
    save_text("image", str(DATA / req["image"]) if req["image"] else "")
    (PART / "transcript.json").unlink(missing_ok=True)
    write_json(
        PART / "meta.json",
        dict(
            model=model,
            id=cid,
            method=method,
            request_sha256=key,
            prep_s=time.perf_counter() - start,
            started=clock(),
        ),
    )
    return 0


def quota(where, rc):
    raw = (PART / ("quota-" + where)).read_text()
    value = quota_state(raw, rc)
    if value in ("approaching", "reached"):
        mark_day(WORK, today())
    return value


def before(rc):
    meta = json.loads((PART / "meta.json").read_text())
    q = quota("before", rc) if meta["model"] == "pcc" else None
    if q not in ("below", None):
        raise Pause("PCC quota before request: " + q)
    meta["quota_before"] = q
    write_json(WORK / "inflight.json", meta)


def generation_limited(text):
    return bool(
        re.search(
            r"\b(?:your |daily )?(?:quota|limit) (?:has been |is )?(?:reached|exceeded|exhausted)\b",
            text,
            re.I,
        )
    )


def hold_paths(work):
    return {work / "quota-day", HERE / "build/session/quota-day"}


def held_today():
    return any(f.exists() and f.read_text() == today() for f in hold_paths(WORK))


def mark_day(work, day):
    for hold in hold_paths(work):
        if not hold.exists() or hold.read_text() < day:
            hold.parent.mkdir(parents=True, exist_ok=True)
            hold.write_text(day)


def remember_quota(work, meta):
    day = meta["started"][:10]
    mark_day(work, day)
    write_json(
        work
        / "interruptions"
        / (day + "-" + meta["id"] + "-" + meta["method"] + ".json"),
        dict(meta, status="quota_reached", diagnostic="Your quota has been reached."),
    )


def recover_quota():
    # Recognize the interruption saved by the initial transport before the amendment.
    meta, error = WORK / "last-interruption.json", WORK / "last-cli-error.txt"
    if meta.exists() and error.exists():
        r = json.loads(meta.read_text())
        if r["model"] == "pcc" and generation_limited(error.read_text()):
            remember_quota(WORK, r)


def capture():
    first = None
    with (PART / "stdout").open("wb") as file:
        while True:
            block = os.read(0, 65536)
            if not block:
                break
            if first is None and block.strip():
                first = time.time()
            file.write(block)
    save_text("first", str(first) if first is not None else "")


def after(rc, start, end, qrc, output_path=path):
    inflight = WORK / "inflight.json"
    meta = json.loads(inflight.read_text())
    stamp = (PART / "first").read_text()
    result = decode(
        (PART / "stdout").read_bytes(),
        (PART / "stderr").read_bytes(),
        int(rc),
        False,
        PART / "transcript.json",
        meta["model"],
        WORK,
        max(0, float(stamp) - float(start)) if stamp else None,
        max(0, float(end) - float(start)),
    )
    meta.update(result)
    meta["quota_after"] = quota("after", int(qrc)) if meta["model"] == "pcc" else None
    if result["status"] in ("infrastructure", "timeout"):
        write_json(WORK / "last-interruption.json", meta)
        inflight.unlink()
        if meta["model"] == "pcc" and generation_limited((PART / "stderr").read_text()):
            remember_quota(WORK, meta)
            raise Pause("PCC generation reported quota reached; suspended for the day")
        raise Pause(
            "CLI transport error: "
            + meta["model"]
            + " "
            + meta["id"]
            + " "
            + meta["method"]
        )
    write_json(output_path(meta["model"], meta["id"], meta["method"]), meta)
    inflight.unlink()
    if meta["quota_after"] not in (None, "below"):
        raise Pause("PCC quota after request: " + meta["quota_after"])


def main():
    mode, *a = sys.argv[1:]
    try:
        if mode == "init":
            init(a[0])
        elif mode == "prepare":
            return prepare(*a)
        elif mode == "before":
            before(int(a[0]))
        elif mode == "capture":
            capture()
        elif mode == "after":
            after(*a)
        elif mode == "end":
            # Verify every required call, including conditional arms, before marking it complete.
            for job in (PART / "sequence").read_text().splitlines():
                if prepare(*job.split()) != 3:
                    raise Pause("Missing requested call: " + job)
            state("finished")
        else:
            raise ValueError(mode)
    except Pause as e:
        state("paused", str(e))
        print(e, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
