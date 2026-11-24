"""Task contracts, deterministic postprocessing, and scoring. Prompts use only payloads."""

from collections import Counter
import json
import re
import unicodedata
from fixtures import FIELDS, js

STR = {"type": "string"}
INT = {"type": "integer"}


def arr(item):
    return {"type": "array", "items": item}


def obj(**fields):
    return {
        "type": "object",
        "properties": fields,
        "required": list(fields),
        "x-order": list(fields),
        "additionalProperties": False,
    }


NOTICE = obj(date=STR, time=STR, place=STR, people=arr(STR))
EVIDENCE = obj(
    **{
        k: obj(value=(arr(STR) if k == "people" else STR), source=STR, quote=STR)
        for k in FIELDS
    }
)
ITEM = obj(sku=STR, quantity=INT)
DELIVERY = obj(received=arr(ITEM), mismatches=arr(STR))
ACTION = obj(
    op={"type": "string", "enum": ["add", "set", "delete"]}, id=STR, quantity=INT
)
UPDATE = obj(actions=arr(ACTION))
LONG = obj(venue=STR, deadline=STR, limit=INT, pending=STR)
BASE = "与えられた資料だけを使い、日本語の指示に従い指定のJSONを返してください。"
METHODS = {
    "notice": ["direct", "evidence"],
    "delivery": ["image", "flat", "table", "code"],
    "update": ["batch", "step"],
}


def norm(s):
    return unicodedata.normalize("NFKC", s).strip()


def request(prompt, schema, image=None):
    return {"prompt": prompt, "schema": schema, "image": image}


def notice_request(p, method):
    task = (
        "対象会議の現在の確定通知から開催日(YYYY-MM-DD)、開始(HH:MM)、会場、出席班を抽出。"
        "案・他の会議・失効した通知は除外。年不明なら日付は空文字。不明な文字列は空、出席不明は空配列。"
    )
    if method == "evidence":
        task += (
            " 各属性にvalue、根拠文書のIDをsource、valueのすべてを直接支える原文の連続した一節をquoteへ。"
            "不明はsourceとquoteも空文字。日付と時刻は正規化する。"
        )
    return request(
        task + "\n対象と資料\n" + js(p), EVIDENCE if method == "evidence" else NOTICE
    )


def supported(k, value, quote):
    q = norm(quote)
    if k == "date":
        m = re.fullmatch(r"(\d{4})-(\d\d)-(\d\d)", value)
        if not m:
            return False
        year, month, day = map(int, m.groups())
        return value in q or re.search(rf"{year}年0?{month}月0?{day}日", q) is not None
    if k == "time":
        return re.fullmatch(r"\d\d:\d\d", value) is not None and value in q
    if k == "people":
        return (
            isinstance(value, list)
            and bool(value)
            and all(isinstance(n, str) and n and n in q for n in value)
        )
    return isinstance(value, str) and bool(value) and value in q


def notice_values(p, method, output):
    docs = {d["id"]: d for d in p["documents"]}
    result = {}
    invalid = []
    abstain = {}
    for k in FIELDS:
        empty = [] if k == "people" else ""
        field = output.get(k)
        if method == "direct":
            result[k] = field
            continue
        if not isinstance(field, dict):
            invalid.append(k)
            result[k] = empty
            continue
        value = field.get("value")
        if value == empty:
            result[k] = empty
            if field.get("quote") or field.get("source"):
                invalid.append(k)
            continue
        doc = docs.get(field.get("source"))
        q = field.get("quote")
        if (
            not doc
            or doc["subject"] != p["target"]
            or doc["status"] != "確定"
            or not isinstance(q, str)
            or not q
            or q not in doc["text"]
            or not supported(k, value, q)
        ):
            invalid.append(k)
            abstain[k] = value
            result[k] = empty
        else:
            result[k] = value
    return result, invalid, abstain


def delivery_request(p, method, ocr):
    form = (
        "発注表と納品明細を突合。receivedに発注全品番の受入数量を品番別に返す。"
        "品番省略時は品名またはaliasで照合。明細のない品番は0。追納分は加算、見本を含む行では見本数を差し引く。"
        "mismatchesには発注数量と異なる品番だけ。発注表\n" + js(p["order"])
    )
    if method == "image":
        return request(form + "\n添付の納品書を読む。", DELIVERY, p["image"])
    text = "\n".join(ocr["flat"]) if method == "flat" else js(ocr["tables"])
    return request(form + "\n納品明細\n" + text, DELIVERY)


def delivery_code(p, ocr):
    order = p["order"]
    values = {v["sku"]: 0 for v in order}
    for table in ocr["tables"]:
        for row in table:
            if len(row) != 4:
                continue
            code, name, raw, note = map(norm, row)
            matching = [
                v for v in order if code == v["sku"] or name in (v["name"], v["alias"])
            ]
            if len(matching) != 1 or not re.fullmatch(r"\d+", raw):
                continue
            m = re.search(r"見本\s*(\d+)\s*個", note)
            values[matching[0]["sku"]] += int(raw) - (int(m[1]) if m else 0)
    return {
        "received": [{"sku": s, "quantity": q} for s, q in values.items()],
        "mismatches": [p["sku"] for p in order if p["ordered"] != values[p["sku"]]],
    }


def update_request(p, history=None, state=None, index=None):
    task = (
        "依頼を時刻順に表へ適用するための操作をactionsに列挙。addは新規、setは既存数量の絶対値、deleteは削除でquantity=0。"
        "見送り・変更なし・重複した無効な操作は追加しない。取消の際は依頼に従い元の状態を復元。"
    )
    if index is None:
        data = {"初期": p["initial"], "依頼": p["requests"]}
    else:
        data = {
            "初期": p["initial"],
            "過去の依頼": p["requests"][:index],
            "実行済み": history,
            "現在の表": state,
            "今回の依頼": p["requests"][index],
        }
        task += " 今回の依頼だけの操作を返す。"
    return request(task + "\n" + js(data), UPDATE)


def apply_actions(state, actions):
    new = dict(state)
    errors = []
    for a in actions:
        if not isinstance(a, dict) or set(a) != {"op", "id", "quantity"}:
            errors.append("invalid_action")
            continue
        op, key, qty = a["op"], a["id"], a["quantity"]
        if (
            not isinstance(key, str)
            or not re.fullmatch(r"[A-Z][0-9]{1,4}", key)
            or type(qty) != int
            or qty < 0
            or op not in ("add", "set", "delete")
        ):
            errors.append("invalid_arguments")
            continue
        if (op == "add" and key in new) or (op in ("delete", "set") and key not in new):
            errors.append("invalid_transition")
            continue
        if op == "delete":
            if qty != 0:
                errors.append("delete_quantity")
            del new[key]
        else:
            new[key] = qty
    return new, errors


def select_paragraphs(p):
    # The query is available to both models. Labels and answer positions never enter the search.
    query = p["project"] + " 会場 締切 上限 保留 最終 決定"
    query_terms = {
        query[i : i + 2] for i in range(len(query) - 1) if " " not in query[i : i + 2]
    }
    ranked = sorted(
        range(len(p["paragraphs"])),
        key=lambda i: (
            p["project"] not in p["paragraphs"][i],
            -sum(q in p["paragraphs"][i] for q in query_terms),
            i,
        ),
    )
    ids = sorted(ranked[:12])
    return [p["paragraphs"][i] for i in ids], ids


def long_request(p, docs):
    return request(
        f"対象は{p['project']}。この事業の最後に有効な会場venue、締切deadline（YYYY-MM-DD）、"
        "人数上限limit、保留事項pending（項目名のみ）を記録から復元。\n"
        + "\n".join(docs),
        LONG,
    )


def parse_json(text):
    def unique(pairs):
        if len(pairs) != len(dict(pairs)):
            raise ValueError("duplicate keys")
        return dict(pairs)

    try:
        v = json.loads(text, object_pairs_hook=unique)
        return v if isinstance(v, dict) else None
    except (ValueError, TypeError):
        return None


def grade(c, method, result):
    gold = c["expected"]
    domain = c["domain"]
    out = result if isinstance(result, dict) else {}
    g = {"format": isinstance(result, dict), "exact": False}
    if domain == "notice":
        values, invalid, filtered = notice_values(c["payload"], method, out)

        def equal(k):
            a, b = values.get(k), gold[k]
            return (
                sorted(a) == sorted(b)
                if k == "people"
                and isinstance(a, list)
                and all(isinstance(x, str) for x in a)
                else a == b
            )

        fields = {k: equal(k) for k in FIELDS}
        g.update(
            fields=fields,
            unsupported=sum(bool(values.get(k)) and not fields[k] for k in FIELDS),
            omitted=sum(bool(gold[k]) and not values.get(k) for k in FIELDS),
            correct_abstentions=sum(not gold[k] and fields[k] for k in FIELDS),
            abstention_opportunities=sum(not gold[k] for k in FIELDS),
            rejected_evidence=invalid,
            filtered_values=filtered,
            values=values,
            exact=all(fields.values()) and g["format"],
        )
    elif domain == "delivery":
        rows = out.get("received", [])
        values = {}
        valid = isinstance(rows, list) and all(
            isinstance(r, dict)
            and isinstance(r.get("sku"), str)
            and type(r.get("quantity")) == int
            for r in rows
        )
        if valid:
            values = {r["sku"]: r["quantity"] for r in rows}
        mism = out.get("mismatches")
        matches_discrepancies = (
            isinstance(mism, list)
            and all(isinstance(s, str) for s in mism)
            and sorted(mism) == gold["mismatches"]
        )
        g.update(
            quantities=valid
            and len(values) == len(rows)
            and values == gold["received"],
            mismatches=matches_discrepancies,
        )
        g["exact"] = g["format"] and g["quantities"] and matches_discrepancies
    elif domain == "update":
        actions = out.get("actions")
        if not isinstance(actions, list):
            return g
        state, errors = apply_actions(c["payload"]["initial"], actions)
        observed = Counter(json.dumps(a, sort_keys=True) for a in actions)
        wanted = Counter(json.dumps(a, sort_keys=True) for a in gold["trace"])
        g.update(
            state=state == gold["state"],
            trace=actions == gold["trace"],
            invalid=errors,
            extra_actions=sum((observed - wanted).values()),
            missing_actions=sum((wanted - observed).values()),
        )
        g["exact"] = g["state"] and g["trace"] and not errors
    elif domain == "long":
        g["fields"] = {
            k: out.get(k) == v and type(out.get(k)) == type(v) for k, v in gold.items()
        }
        g["exact"] = all(g["fields"].values())
    return g
