"""Prepare fixed local materials and score outputs of fm run by Apple's Terminal."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import random
import subprocess
import sys
import time
from evaluate import dataset, evaluate, export, methods
from fixtures import DATA, HERE, digest, js, write_json
from fm_client import BASE, Client, Pause, clock, decode, quota_state
from tasks import (
    apply_actions,
    delivery_request,
    long_request,
    notice_request,
    parse_json,
    update_request,
)

WORK = Path(os.environ.get("AFM_STUDY_WORK", HERE / "build/session")).resolve()
WORK.mkdir(exist_ok=True, parents=True)
TMP = WORK / "terminal"
TMP.mkdir(mode=0o700, exist_ok=True)
CACHE = HERE / "build/vision-cache"
VISION = HERE / "build/vision-tool"


def save_status(client, status, reason=None):
    # Keep the observed Core identity from the same fixed study.
    loc = WORK / "status.json"
    state = (
        json.loads(loc.read_text())
        if loc.exists()
        else {"started": clock(), "models": {}}
    )
    state.update(
        status=status,
        ended=clock(),
        case_methods=client.db.execute("select count(*) from cases").fetchone()[0],
        fixture_lock=digest(DATA / "lock.json"),
    )
    if client.setting("terminal-pcc-available") == "yes":
        state["models"]["pcc"] = "AFM 3 Cloud"
    if reason:
        state["reason"] = reason
    else:
        state.pop("reason", None)
    write_json(loc, state)
    if status != "running":
        export(client, WORK)


def get_calls(client, case, method):
    records = []
    for status, s in client.db.execute(
        "select status,payload from calls where key like ?",
        (case + "/pcc/" + method + "/%",),
    ):
        if status == "done":
            records.append(json.loads(s))
    return sorted(records, key=lambda r: r["step"])


def inputs(c, m, idx, client, old):
    started = time.perf_counter()
    p = c["payload"]
    d = c["domain"]
    vision_s = 0.0
    matches = None
    selection = None
    if d == "notice":
        req = notice_request(p, m)
    elif d == "delivery":
        ocr = None
        if m != "image":
            now = time.perf_counter()
            live = TMP / "vision.json"
            subprocess.run(
                [VISION, m, DATA / p["image"], live], check=True, timeout=150
            )
            vision_s = time.perf_counter() - now
            ocr = json.loads(live.read_text())
            attr = "flat" if m == "flat" else "tables"
            frozen = json.loads((CACHE / (c["id"] + ".json")).read_text())
            matches = ocr[attr] == frozen[attr]
            if not matches:
                write_json(WORK / ("ocr-pcc-" + c["id"] + "-" + m + ".json"), ocr)
        req = delivery_request(p, m, ocr)
    elif d == "update" and m == "batch":
        req = update_request(p)
    elif d == "update":
        history = []
        state = dict(p["initial"])
        records = get_calls(client, c["id"], m)
        if len(records) < idx:
            raise RuntimeError("Missing preceding decision")
        for r in records[:idx]:
            ans = parse_json(r["text"])
            if not isinstance(ans, dict) or not isinstance(ans.get("actions"), list):
                return None, None
            state, _ = apply_actions(state, ans["actions"])
            history.extend(ans["actions"])
        req = update_request(p, history, state, idx)
    elif d == "long":
        docs = p["paragraphs"]
        req = long_request(p, docs)
    else:
        orig = old.request(p, "baseline")
        req = dict(
            prompt=orig["prompt"],
            instructions=orig["instructions"],
            schema=None,
            image=None,
        )
    return req, dict(
        prep_s=time.perf_counter() - started,
        vision_s=vision_s,
        matches=matches,
        selection=selection,
    )


def quota(path, code, client):
    raw = path.read_text()
    value = quota_state(raw, code)
    if value in ("approaching", "reached"):
        client.put_setting("quota-hold-day", clock()[:10])
    if value == "unknown":
        (WORK / "quota-unrecognized.txt").write_text(raw)
    return value


class RecordedClient:
    """Replay completed CLI responses; this adapter has no ability to call a model."""

    def __init__(self, client, records):
        self.db = client.db
        self.work = client.work
        self.records = records

    def generate(self, case, model, method, step, req):
        msg = self.records[step]
        assert (
            msg["request_sha256"]
            == hashlib.sha256(
                js([req.get("instructions", BASE), req]).encode()
            ).hexdigest()
        )
        return msg


def finalize(c, m, old, client):
    records = get_calls(client, c["id"], m)
    key = "/".join(["pcc", c["id"], m])
    if client.db.execute("select 1 from cases where key=?", (key,)).fetchone():
        return
    if not records:
        return
    if m == "step" and len(records) < len(c["payload"]["requests"]):
        ans = parse_json(records[-1]["text"])
        if isinstance(ans, dict) and isinstance(ans.get("actions"), list):
            return
    # Use the original scorer. Record live preprocessing from the actual sending path.
    captured = None
    if c["domain"] == "delivery" and m in ("flat", "table"):
        source = CACHE / (c["id"] + ".json")
        if records[0]["terminal_timing"]["matches"] is False:
            source = WORK / ("ocr-pcc-" + c["id"] + "-" + m + ".json")
        captured = json.loads(source.read_text())
    evaluate(
        c,
        "pcc",
        m,
        RecordedClient(client, records),
        CACHE,
        old,
        VISION,
        captured_ocr=captured,
    )
    row = json.loads(
        client.db.execute("select payload from cases where key=?", (key,)).fetchone()[0]
    )
    row.update(
        vision_preprocess_s=sum(r["terminal_timing"]["vision_s"] for r in records),
        active_e2e_s=sum(
            r["terminal_timing"]["prep_s"] + r["cli_e2e_s"] for r in records
        ),
        host_run_s=sum(r["terminal_timing"]["host_s"] for r in records),
        ocr_matches_frozen=records[0]["terminal_timing"]["matches"],
    )
    with client.db:
        client.db.execute("update cases set payload=? where key=?", (js(row), key))


def main():
    p = argparse.ArgumentParser()
    p.add_argument(
        "mode",
        choices=["init", "prepare", "before", "after", "end", "capture", "pause"],
    )
    p.add_argument("values", nargs="*")
    a = p.parse_args()
    v = a.values
    if a.mode == "capture":
        first = None
        with (TMP / "stdout").open("wb") as dest:
            while True:
                block = os.read(sys.stdin.fileno(), 65536)
                if not block:
                    break
                if first is None and block.strip():
                    first = time.time()
                dest.write(block)
        (TMP / "first").write_text(str(first) if first is not None else "")
        return
    client = Client(WORK)
    try:
        if a.mode == "pause":
            save_status(client, "paused", v[0])
            return
        if a.mode == "before":
            if client.setting("quota-hold-day") == clock()[:10]:
                raise Pause("PCC paused for the day at quota warning")
            status = quota(TMP / "quota-before", int(v[0]), client)
            if status != "below":
                raise Pause("PCC quota before request: " + status)
            meta = json.loads((TMP / "meta.json").read_text())
            meta["quota_before"] = status
            with client.db:
                client.db.execute(
                    "insert or replace into calls values(?,?,?)",
                    (meta["key"], "inflight", js(meta)),
                )
            write_json(TMP / "meta.json", meta)
            return
        raw, shared, old = dataset()
        if a.mode == "init":
            import re

            if not re.search(
                r"[✓✔]\s+pcc\s+\(AFM 3 Cloud\)", (TMP / "models").read_text()
            ):
                raise Pause("Apple Terminal did not list AFM 3 Cloud")
            client.put_setting("terminal-pcc-available", "yes")
            if client.setting("fixture-hash") not in (None, digest(DATA / "lock.json")):
                raise RuntimeError("Fixture hash differs")
            client.put_setting("fixture-hash", digest(DATA / "lock.json"))
            save_status(client, "running")
            seq = []
            for phase in ("regression", "held", "long"):
                items = [
                    c
                    for c in raw
                    if c["split"] == phase and (c["id"] in shared or phase == "long")
                ]
                random.Random(20261124).shuffle(items)
                for c in items:
                    cond = methods(c, "pcc")
                    random.Random(c["id"]).shuffle(cond)
                    for m in cond:
                        for idx in range(
                            len(c["payload"]["requests"]) if m == "step" else 1
                        ):
                            seq.append(" ".join([c["id"], m, str(idx)]))
            (TMP / "sequence").write_text("\n".join(seq) + "\n")
            return
        if a.mode == "end":
            remain = 0
            for c in raw:
                if c["id"] in shared or c["domain"] == "long":
                    for m in methods(c, "pcc"):
                        finalize(c, m, old, client)
                        remain += not bool(
                            client.db.execute(
                                "select 1 from cases where key=?",
                                ("pcc/" + c["id"] + "/" + m,),
                            ).fetchone()
                        )
            if remain:
                raise Pause(str(remain) + " PCC conditions pending")
            has_core = (
                client.db.execute(
                    "select count(*) from cases where key like 'system/%'"
                ).fetchone()[0]
                == 335
            )
            save_status(client, "finished" if has_core else "pcc_complete")
            return
        if a.mode == "prepare":
            cid, m, idx = v[0], v[1], int(v[2])
            c = next(c for c in raw if c["id"] == cid)
            if cid not in shared and c["domain"] != "long":
                raise ValueError("Outside frozen PCC panel")
            key = "/".join([cid, "pcc", m, str(idx)])
            entry = client.db.execute(
                "select status from calls where key=?", (key,)
            ).fetchone()
            if entry and entry[0] == "done":
                return 3
            if entry and entry[0] == "inflight":
                raise Pause("Interrupted request requires review: " + key)
            if client.setting("quota-hold-day") == clock()[:10]:
                raise Pause("PCC paused for the day at quota warning")
            start = time.time()
            req, timing = inputs(c, m, idx, client, old)
            if req is None:
                finalize(c, m, old, client)
                return 3
            meta = dict(
                key=key,
                id=cid,
                model="pcc",
                method=m,
                step=idx,
                started=clock(),
                request_sha256=hashlib.sha256(
                    js([req.get("instructions", BASE), req]).encode()
                ).hexdigest(),
                terminal_timing=timing,
                prep_start=start,
            )
            write_json(TMP / "meta.json", meta)
            (TMP / "prompt").write_text(req["prompt"])
            (TMP / "instructions").write_text(req.get("instructions", BASE))
            (TMP / "schema").write_text(js(req["schema"]) if req["schema"] else "")
            (TMP / "image").write_text(str(DATA / req["image"]) if req["image"] else "")
            transcript = TMP / "transcript.json"
            if transcript.exists():
                transcript.unlink()
            return
        if a.mode == "after":
            rc, start, end, qrc = int(v[0]), float(v[1]), float(v[2]), int(v[3])
            meta = json.loads((TMP / "meta.json").read_text())
            first = (TMP / "first").read_text()
            response = decode(
                (TMP / "stdout").read_bytes(),
                (TMP / "stderr").read_bytes(),
                rc,
                False,
                TMP / "transcript.json",
                "pcc",
                WORK,
                max(0, float(first) - start) if first else None,
                max(0, end - start),
            )
            meta.update(response)
            meta["quota_after"] = quota(TMP / "quota-after", qrc, client)
            meta["terminal_timing"]["host_s"] = time.time() - meta.pop("prep_start")
            key = meta.pop("key")
            retry = meta["status"] == "infrastructure"
            with client.db:
                client.db.execute(
                    "update calls set status=?,payload=? where key=?",
                    ("retry" if retry else "done", js(meta), key),
                )
            if retry:
                raise Pause("PCC CLI error; see local diagnostics")
            c = next(c for c in raw if c["id"] == meta["id"])
            finalize(c, meta["method"], old, client)
            if meta["quota_after"] != "below":
                raise Pause("PCC quota after request: " + meta["quota_after"])
    except Pause as exc:
        save_status(client, "paused", str(exc))
        print(str(exc), file=sys.stderr)
        return 2
    finally:
        client.db.close()


if __name__ == "__main__":
    sys.exit(main())
