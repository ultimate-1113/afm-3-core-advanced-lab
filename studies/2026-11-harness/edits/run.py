"""Use the same real Apple Terminal transport for the separate edit panel."""

from pathlib import Path
import hashlib
import json
import random
import re
import sys
import time
from sheet import req
from common import HERE, ESC, clock, js, read_rows, sha, write_json
import run as transport

LOCAL = Path(__file__).resolve().parent


def cases():
    return {c["id"]: c for c in read_rows(LOCAL / "fixtures/inputs.jsonl")}


def output(model, cid, method):
    if (
        model not in transport.NAMES
        or not re.fullmatch(r"edit-(?:0[1-9]|1[0-2])", cid)
        or method not in ("plain", "full", "patch", "fresh_full", "fresh_patch")
    ):
        raise ValueError("Unknown edit request")
    return transport.RAW / f"{cid}.{model}.{method}.json"


def verify():
    lock = json.loads((LOCAL / "lock.json").read_text())
    for name, expected in lock.items():
        if sha(LOCAL / name) != expected:
            raise ValueError("Edit protocol changed: " + name)
    return sha(LOCAL / "lock.json")


def init(route):
    frozen = verify()
    transport.preflight()
    transport.recover_quota()
    transport.RAW.mkdir(parents=True, exist_ok=True)
    info = transport.WORK / "session.json"
    state = (
        json.loads(info.read_text())
        if info.exists()
        else dict(lock=frozen, started=clock(), models={})
    )
    if state["lock"] != frozen:
        raise ValueError("Edit session protocol differs")
    selected = list(transport.NAMES) if route == "both" else [route]
    for model in selected:
        if not re.search(
            r"[✓✔]\s+" + model + r"\s+\(" + transport.NAMES[model] + r"\)",
            ESC.sub("", (transport.PART / "models").read_text()),
        ):
            raise transport.Pause("Model unavailable in Apple Terminal: " + model)
        state["models"][model] = transport.NAMES[model]
    write_json(info, state)
    panel = list(cases().values())
    rng = random.Random(202611244)
    rng.shuffle(panel)
    jobs = []
    for i, c in enumerate(panel):
        arms = ["plain", "full", "patch"]
        rng.shuffle(arms)
        if c["public"]["snapshot"] != c["live"]:
            newer = ["fresh_full", "fresh_patch"]
            rng.shuffle(newer)
            arms.extend(newer)
        for j, arm in enumerate(arms):
            for model in selected if (i + j) % 2 == 0 else reversed(selected):
                jobs.append(" ".join((model, c["id"], arm)))
    transport.save_text("sequence", "\n".join(jobs) + "\n")
    transport.state("running")


def prepare(model, cid, method):
    start = time.perf_counter()
    c = cases()[cid]
    dest = output(model, cid, method)
    request = req(c, method)
    sig = transport.fingerprint(request)
    if dest.exists():
        if json.loads(dest.read_text())["request_sha256"] != sig:
            raise ValueError("Edit request differs on resume")
        return 3
    if (transport.WORK / "inflight.json").exists():
        raise transport.Pause("Inspect unfinished edit request before resuming")
    if model == "pcc" and transport.held_today():
        raise transport.Pause("PCC generation quota reached for today")
    for name, val in (
        ("instructions", request["instructions"]),
        ("prompt", request["prompt"]),
        ("image", ""),
        ("schema", js(request["schema"]) if request["schema"] else ""),
    ):
        transport.save_text(name, val)
    (transport.PART / "transcript.json").unlink(missing_ok=True)
    write_json(
        transport.PART / "meta.json",
        dict(
            id=cid,
            model=model,
            method=method,
            request_sha256=sig,
            prep_s=time.perf_counter() - start,
            started=clock(),
        ),
    )
    return 0


def main():
    mode, *args = sys.argv[1:]
    try:
        if mode == "init":
            init(args[0])
        elif mode == "prepare":
            return prepare(*args)
        elif mode == "capture":
            transport.capture()
        elif mode == "before":
            transport.before(int(args[0]))
        elif mode == "after":
            transport.after(*args, output_path=output)
        elif mode == "end":
            for job in (transport.PART / "sequence").read_text().splitlines():
                if prepare(*job.split()) != 3:
                    raise transport.Pause("Missing edit result")
            transport.state("finished")
        else:
            raise ValueError(mode)
    except transport.Pause as e:
        transport.state("paused", str(e))
        print(e, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
