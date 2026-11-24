"""Bounded domain executors and code-only controls. They accept visible inputs only."""

import itertools
import re
from geometry import norm

AL_KEYS = ("A", "B", "C", "rate", "watts")
TIME_KEYS = ("cpu", "memory")
OPERATORS = ("cpu", "mem", "cpu_back", "mem_back", "both_back", "skip")


def integers(obj, names):
    return (
        isinstance(obj, dict)
        and set(obj) == set(names)
        and all(type(obj[k]) is int for k in names)
    )


def policy(ticket):
    clauses = [
        s
        for s in re.split("[。、]", ticket)
        if s and not any(v in s for v in ("旧", "以前", "廃止"))
    ]
    line = "。".join(clauses)
    needs = re.findall(r"毎秒(?:処理件数は)?(\d+)(?:件)?", line)
    if len(needs) != 1:
        return None
    target = int(needs[0]) + int("を超え" in line)
    cap = re.search(r"(\d+)台(?:まで|以内|以下)|(?:最大|設置枠は)(\d+)台", line)
    limit = int(next(g for g in cap.groups() if g is not None)) if cap else -1
    if re.search(r"最少台数|台数が少ない|台数を(?:第一|最小)|優先順位は台数", line):
        priority = "units"
    elif re.search("省電力|電力", line):
        priority = "watts"
    else:
        return None
    return dict(target=target, limit=limit, priority=priority)


def allocation(payload, ir):
    if (
        not isinstance(ir, dict)
        or set(ir) != {"target", "limit", "priority"}
        or type(ir["target"]) is not int
        or ir["target"] < 0
        or type(ir["limit"]) is not int
        or ir["limit"] < -1
        or ir["priority"] not in ("watts", "units")
    ):
        return None
    items = [payload["catalog"][k] for k in "ABC"]
    best = None
    answer = dict.fromkeys(AL_KEYS, -1)
    for counts in itertools.product(*(range(v["stock"] + 1) for v in items)):
        n = sum(counts)
        if ir["limit"] != -1 and n > ir["limit"]:
            continue
        rate = sum(q * item["rate"] for q, item in zip(counts, items))
        if rate < ir["target"]:
            continue
        watts = sum(q * item["watts"] for q, item in zip(counts, items))
        rank = (watts, n, counts) if ir["priority"] == "watts" else (n, watts, counts)
        if best is None or rank < best:
            best = rank
            answer = dict(zip(AL_KEYS, (*counts, rate, watts)))
    return answer


def log_ir(payload):
    result = []
    for row in payload["log"]:
        line = row["text"]
        if any(x in line for x in ("見送り", "現行値を維持")):
            op, arg = "skip", 0
        elif re.search("戻|復元", line):
            stamp = re.search(r"(\d{1,2}):(\d{2})", line)
            if not stamp:
                return None
            op = (
                "both_back"
                if "両方" in line
                else "cpu_back"
                if "CPU" in line
                else "mem_back"
                if "メモリ" in line
                else None
            )
            arg = int(stamp[1]) * 100 + int(stamp[2])
        else:
            val = re.search(r"(\d+)\s*(GB|コア)", line)
            if not val:
                return None
            op = "cpu" if val[2] == "コア" else "mem"
            arg = int(val[1])
        if op is None:
            return None
        result.append(dict(op=op, arg=arg))
    return dict(events=result)


def timeline(payload, ir):
    if (
        not isinstance(ir, dict)
        or not isinstance(ir.get("events"), list)
        or len(ir["events"]) != len(payload["log"])
    ):
        return None
    state = dict(cpu=-1, memory=-1)
    history = []
    for row, event in zip(payload["log"], ir["events"]):
        stamp = int(row["at"].replace(":", ""))
        if (
            not isinstance(event, dict)
            or event.get("op") not in OPERATORS
            or type(event.get("arg")) is not int
        ):
            return None
        op, arg = event["op"], event["arg"]
        if op.endswith("_back"):
            if not (0 <= arg < stamp) or arg % 100 >= 60:
                return None
            past = next(
                (s for when, s in reversed(history) if when <= arg),
                dict(cpu=-1, memory=-1),
            )
            keys = {
                "cpu_back": ["cpu"],
                "mem_back": ["memory"],
                "both_back": TIME_KEYS,
            }[op]
            for k in keys:
                state[k] = past[k]
        elif op == "skip":
            if arg != 0:
                return None
        elif arg < 0:
            return None
        else:
            state["cpu" if op == "cpu" else "memory"] = arg
        history.append((stamp, state.copy()))
    return state


def clean_code(s):
    return re.sub("[‐‑‒–—−ー]", "-", norm(s)).upper()


def invoice_ir(payload, rows):
    result = []
    for ref, name, _, raw_note in rows:
        linked = [
            p["sku"]
            for p in payload["order"]
            if clean_code(ref) == p["sku"] or norm(name) in (p["name"], p["alias"])
        ]
        if len(linked) != 1:
            return None
        note = norm(raw_note)
        number = re.search(r"(\d+)個", note)
        if any(v in note for v in ("なし", "全数", "受入可", "通常品", "追納")):
            excluded = 0
        elif number and any(
            v in note for v in ("見本", "試供", "返品", "検査", "破損", "除く", "不可")
        ):
            excluded = int(number[1])
        else:
            return None
        result.append(dict(sku=linked[0], exclude=excluded))
    return dict(rows=result)


def invoice(payload, rows, ir):
    if (
        not rows
        or not isinstance(ir, dict)
        or not isinstance(ir.get("rows"), list)
        or len(rows) != len(ir["rows"])
    ):
        return None
    totals = {p["sku"]: 0 for p in payload["order"]}
    for row, decision in zip(rows, ir["rows"]):
        if (
            not isinstance(decision, dict)
            or not isinstance(decision.get("sku"), str)
            or decision["sku"] not in totals
        ):
            return None
        count = norm(row[2])
        excl = decision.get("exclude")
        if (
            not re.fullmatch(r"[0-9]+", count)
            or type(excl) is not int
            or not 0 <= excl <= int(count)
        ):
            return None
        totals[decision["sku"]] += int(count) - excl
    return dict(
        received=totals,
        mismatches=sorted(
            item["sku"]
            for item in payload["order"]
            if totals[item["sku"]] != item["ordered"]
        ),
    )


def execute(domain, payload, rows, ir):
    if domain == "allocation":
        return allocation(payload, ir)
    if domain == "timeline":
        return timeline(payload, ir)
    return invoice(payload, rows, ir)


def code_ir(domain, payload, rows):
    if domain == "allocation":
        return policy(payload["ticket"])
    if domain == "timeline":
        return log_ir(payload)
    return invoice_ir(payload, rows)
