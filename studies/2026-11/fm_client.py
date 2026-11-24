"""Apple fm subprocess transport, quota checks and crash-safe per-request checkpoints."""

from contextlib import closing
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import sqlite3
import subprocess
import tempfile
import time
from fixtures import DATA, js
from tasks import BASE

FM = "/usr/bin/fm"
ESC = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


class Pause(Exception):
    pass


def clock():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def lines(args):
    p = subprocess.run([FM] + args, capture_output=True, text=True, timeout=35)
    return ESC.sub("", p.stdout + "\n" + p.stderr).strip(), p.returncode


def available(model):
    text, _ = lines(["models"])
    name = {"system": "AFM 3 Core Advanced", "pcc": "AFM 3 Cloud"}[model]
    if not re.search(r"[✓✔]\s+" + model + r"\s+\(" + name + r"\)", text):
        reason = (
            "requires Apple Terminal"
            if "Terminal app" in text
            else "model not available in this session"
        )
        raise Pause(model + ": " + reason)
    return name


def quota_state(text, code=0):
    plain = ESC.sub("", text).casefold().replace("_", " ").replace("-", " ")
    if code or any(t in plain for t in ("unavailable", "not available", "error")):
        return "unavailable"
    neutral = re.sub(
        r"\b(?:not|isn't) (?:approaching|near(?:ing)?|reached|exceeded)\b",
        "below",
        plain,
    )
    if re.search(
        r"\b(limit reached|quota reached|exhausted|exceeded|at (?:the )?limit|limit has been reached|no quota left|no quota remaining|0 (?:requests? )?remaining)\b",
        neutral,
    ):
        return "reached"
    if re.search(r"\b(approaching|near(?:ing)?|close to)\b", neutral):
        return "approaching"
    if re.search(r"\b(below|within|under|available|normal|ample|healthy)\b", neutral):
        return "below"
    return "unknown"


class Client:
    def __init__(self, work):
        self.work = work
        self.db = sqlite3.connect(work / "run.sqlite")
        self.db.execute("pragma journal_mode=wal")
        self.db.executescript("""
          create table if not exists calls (key text primary key, status text not null, payload text not null);
          create table if not exists cases (key text primary key, payload text not null);
          create table if not exists settings (key text primary key, value text not null);
        """)
        self.last_quota = None

    def setting(self, k):
        row = self.db.execute("select value from settings where key=?", (k,)).fetchone()
        return row[0] if row else None

    def put_setting(self, k, v):
        with self.db:
            self.db.execute("insert or replace into settings values(?,?)", (k, v))

    def quota(self):
        raw, code = lines(["quota-usage", "--model", "pcc"])
        status = quota_state(raw, code)
        if status == "unknown":
            (self.work / "quota-unrecognized.txt").write_text(raw + "\n")
        if status in ("approaching", "reached"):
            self.put_setting("quota-hold-day", clock()[:10])
        self.last_quota = status
        return status

    def generate(self, case_id, model, method, step, req):
        key = "/".join([case_id, model, method, str(step)])
        fingerprint = hashlib.sha256(
            js([req.get("instructions", BASE), req]).encode()
        ).hexdigest()
        row = self.db.execute(
            "select status,payload from calls where key=?", (key,)
        ).fetchone()
        if row:
            data = json.loads(row[1])
            if data["request_sha256"] != fingerprint:
                raise RuntimeError("Request changed before resume: " + key)
            if row[0] == "done":
                return data
            if row[0] == "inflight":
                raise Pause("Interrupted request requires review before retry: " + key)
        before = None
        if model == "pcc":
            if self.setting("quota-hold-day") == clock()[:10]:
                raise Pause("PCC paused for the day at the quota warning")
            before = self.quota()
            if before != "below":
                raise Pause("PCC quota before request: " + before)
        data = dict(
            id=case_id,
            model=model,
            method=method,
            step=step,
            started=clock(),
            request_sha256=fingerprint,
            quota_before=before,
            quota_after=None,
            usage=None,
        )
        with self.db:
            self.db.execute(
                "insert or replace into calls values(?,?,?)",
                (key, "inflight", js(data)),
            )
        response = invoke(model, req, self.work)
        data.update(response)
        if model == "pcc":
            try:
                data["quota_after"] = self.quota()
            except (OSError, subprocess.SubprocessError):
                data["quota_after"] = "unavailable"
        interrupted = data["status"] in ("infrastructure", "timeout")
        with self.db:
            self.db.execute(
                "update calls set status=?,payload=? where key=?",
                ("retry" if interrupted else "done", js(data), key),
            )
        if interrupted:
            raise Pause(
                model + " " + data["status"] + " at " + key + "; see local diagnostics"
            )
        return data


def invoke(model, req, work):
    with tempfile.TemporaryDirectory(dir=work) as tmp:
        transcript = Path(tmp) / "transcript.json"
        args = [
            FM,
            "respond",
            "--model",
            model,
            "--greedy",
            "--stream",
            "--instructions",
            req.get("instructions", BASE),
            "--save-transcript",
            str(transcript),
        ]
        if req["schema"]:
            args.extend(["--schema", js(req["schema"])])
        if req["image"]:
            args.extend(["--image", str(DATA / req["image"])])
        args.extend(["--text", req["prompt"]])
        start = time.perf_counter()
        p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        streams = {"out": bytearray(), "err": bytearray()}
        first = None
        timed_out = False
        with closing(selectors.DefaultSelector()) as poll:
            poll.register(p.stdout, selectors.EVENT_READ, "out")
            poll.register(p.stderr, selectors.EVENT_READ, "err")
            while poll.get_map():
                left = 180 - (time.perf_counter() - start)
                if left <= 0:
                    p.kill()
                    timed_out = True
                    break
                for k, _ in poll.select(min(left, 3)):
                    block = os.read(k.fileobj.fileno(), 65536)
                    if not block:
                        poll.unregister(k.fileobj)
                        continue
                    streams[k.data].extend(block)
                    if (
                        k.data == "out"
                        and first is None
                        and ESC.sub(
                            "", streams["out"].decode("utf-8", "ignore")
                        ).strip()
                    ):
                        first = time.perf_counter() - start
        p.wait()
        p.stdout.close()
        p.stderr.close()
        elapsed = time.perf_counter() - start
        return decode(
            bytes(streams["out"]),
            bytes(streams["err"]),
            p.returncode,
            timed_out,
            transcript,
            model,
            work,
            first,
            elapsed,
        )


def decode(stdout, stderr, code, timed_out, transcript, model, work, first, elapsed):
    out = ESC.sub("", stdout.decode("utf-8", "replace"))
    err = ESC.sub("", stderr.decode("utf-8", "replace"))
    out = "\n".join(
        l for l in out.splitlines() if not l.startswith("Transcript saved to:")
    ).strip()
    status = "timeout" if timed_out else "ok" if code == 0 else "infrastructure"
    low = (out + "\n" + err).lower()
    if status == "infrastructure" and any(
        x in low for x in ("guardrail", "safety refusal", "generation was refused")
    ):
        status = "refusal"
    if status == "infrastructure" and any(
        x in low
        for x in ("context window", "context size exceeded", "exceeded the context")
    ):
        status = "context_limit"
    usage = None
    route = None
    if transcript.exists():
        pack = json.loads(transcript.read_text())
        route = pack.get("modelName")
        entries = pack.get("transcript", {}).get("transcript", {}).get("entries", [])
        last = next(
            (
                e
                for e in reversed(entries)
                if e.get("role") in ("assistant", "response")
            ),
            {},
        )
        observed = last.get("usage") or last.get("metadata", {}).get("usage")
        if isinstance(observed, dict):
            usage = {k: v for k, v in observed.items() if type(v) == int}
    if status == "ok" and route != model:
        status = "infrastructure"
    if status == "infrastructure":
        (work / "last-cli-error.txt").write_text((err + "\n" + out)[:5000] + "\n")
    return dict(
        status=status,
        exit=code,
        text=out if status == "ok" else "",
        transcript_model=route,
        first_stdout_s=first if out and status == "ok" else None,
        cli_e2e_s=elapsed,
        usage=usage,
    )
