"""Fixed prompts, machine-checkable invariants and semantically tolerant decoding."""

import json
import re
from common import INT, STR, arr, js, obj, parse_json
from engine import AL_KEYS, TIME_KEYS, OPERATORS, integers, policy

BASE = "依頼と資料に基づいて回答してください。最後の答えは指定したJSONオブジェクト1個とし、説明は不要です。"
PANEL = ["plain", "schema", "review", "feedback", "program", "code"]


def enum(values):
    return {"type": "string", "enum": list(values)}


def answer_schema(domain):
    if domain == "allocation":
        return obj(**dict.fromkeys(AL_KEYS, INT))
    if domain == "timeline":
        return obj(cpu=INT, memory=INT)
    return obj(received=arr(obj(sku=STR, quantity=INT)), mismatches=arr(STR))


def unpack(text):
    strict = parse_json(text)
    if strict is not None:
        return strict, True
    # Accept exactly one unambiguous top-level object with surrounding prose/fence.
    start = text.find("{")
    if start < 0:
        return None, False
    try:
        _, end = json.JSONDecoder().raw_decode(text[start:])
    except ValueError:
        return None, False
    if any(c in text[:start] + text[start + end :] for c in "{}"):
        return None, False
    return parse_json(text[start : start + end]), False


def canonical(domain, payload, answer):
    if domain == "allocation":
        return answer if integers(answer, AL_KEYS) else None
    if domain == "timeline":
        return answer if integers(answer, TIME_KEYS) else None
    if not isinstance(answer, dict) or set(answer) != {"received", "mismatches"}:
        return None
    items = answer["received"]
    bad = answer["mismatches"]
    if not isinstance(items, list) or not isinstance(bad, list):
        return None
    totals = {}
    for row in items:
        if (
            not isinstance(row, dict)
            or set(row) != {"sku", "quantity"}
            or not isinstance(row["sku"], str)
            or type(row["quantity"]) is not int
            or row["quantity"] < 0
            or row["sku"] in totals
        ):
            return None
        totals[row["sku"]] = row["quantity"]
    keys = {p["sku"] for p in payload["order"]}
    if (
        set(totals) != keys
        or not all(isinstance(k, str) and k in keys for k in bad)
        or len(set(bad)) != len(bad)
    ):
        return None
    return dict(received=totals, mismatches=sorted(bad))


def checks(domain, payload, answer):
    result = canonical(domain, payload, answer)
    if result is None:
        return ["必須のキー・件数・型・品番を指定通りにそろえる。"]
    issues = []
    if domain == "allocation":
        p = policy(payload["ticket"])
        if all(v == -1 for v in result.values()):
            return []
        catalog = payload["catalog"]
        if any(not 0 <= result[k] <= catalog[k]["stock"] for k in "ABC"):
            issues.append("機種別の台数が在庫の範囲外。")
        rates = sum(result[k] * catalog[k]["rate"] for k in "ABC")
        watts = sum(result[k] * catalog[k]["watts"] for k in "ABC")
        if rates != result["rate"] or watts != result["watts"]:
            issues.append("機種別台数から計算した処理能力か電力が記載合計と不一致。")
        if p and rates < p["target"]:
            issues.append("台数から計算した処理能力が現在の要求を下回る。")
        if p and p["limit"] != -1 and sum(result[k] for k in "ABC") > p["limit"]:
            issues.append("合計台数が現在の設置枠を上回る。")
    elif domain == "timeline":
        for field, unit in [("cpu", "コア"), ("memory", "GB")]:
            # Necessary condition only. It does not replay the log or use the answer key.
            candidates = {-1}
            for row in payload["log"]:
                candidates.update(
                    int(v) for v in re.findall(r"(\d+)" + unit, row["text"])
                )
            if result[field] not in candidates:
                issues.append(field + "に、ログにも未設定値にもない数値がある。")
    else:
        discrepancies = sorted(
            x["sku"]
            for x in payload["order"]
            if x["ordered"] != result["received"][x["sku"]]
        )
        if discrepancies != result["mismatches"]:
            issues.append(
                "回答の受入数と発注数を比較した結果がmismatchesと一致しない。"
            )
    return issues


def request(case, method, rows, previous=None):
    domain, p = case["domain"], case["payload"]
    schema = answer_schema(domain)
    image = None
    if domain == "allocation":
        description = (
            "各機種のrateは1台当たりの毎秒処理件数、wattsはW、stockは在庫。台数は非負整数。"
            "依頼の第一目的が同点なら他方（消費電力または台数）を最小化。両方同点なら(A,B,C)の辞書順で最小。"
            "実現不能なら全項目-1。台数A,B,C、合計rate,wattsを整数で返す。"
        )
        data = js(p)
        ir_desc = (
            "計算は外部で行う。依頼から最小の必要処理件数target、総台数の上限limit（別途上限がなければ-1、在庫は含めない）、"
            "第一目的priority（wattsかunits）だけを抽出。"
        )
        ir_schema = obj(target=INT, limit=INT, priority=enum(("watts", "units")))
    elif domain == "timeline":
        description = (
            "時刻順に設定履歴を処理し、最後のCPU割当cpu（コア）とメモリ割当memory（GB）を整数で返す。"
            "復元は指定された項目だけを指定時刻以下で最後に有効だった値へ戻す。未設定の値は-1。見送り・案は反映しない。"
        )
        data = js(p["log"])
        ir_desc = (
            "計算は外部で行う。ログ順に1行につき1個のeventsを返す。設定はop=cpuまたはmem、arg=値。"
            "復元はcpu_back/mem_back/both_backでarg=復元先の時刻をHHMMの整数にする。09:05は905。"
            "提案や見送りはop=skip,arg=0。"
        )
        ir_schema = obj(events=arr(obj(op=enum(OPERATORS), arg=INT)))
    else:
        description = (
            "納品書と発注表を突合し、receivedに全品番のsku,quantity（受入数量）を1回ずつ列挙。"
            "mismatchesは発注数量と異なる品番の配列。同じ品番の行は合算。品番が省略された行は品名やaliasで対応する。"
            "明細にない品番は0。備考に従い見本・返品など受入不可分は納入数から除き、受入可なら含める。"
        )
        data = "発注表\n" + js(p["order"])
        if method in ("rows", "program"):
            data += "\n納品書を文字認識した各行。[品番,品名,納入数,備考]の順\n" + js(
                rows
            )
        else:
            image = p["image"]
            data += "\n添付の納品書を読む。"
        ir_desc = (
            "集計は外部で行う。文字認識した行の順番を保ち各行につき1件、対応する発注品番skuと"
            "その行の納入数から除く個数excludeだけをrowsに返す。"
        )
        ir_schema = obj(
            rows=arr(obj(sku=enum([x["sku"] for x in p["order"]]), exclude=INT))
        )
    prompt = description + "\n" + data
    if method == "program":
        prompt += "\n今回は上記の最終回答に代えて、次の中間データだけを出す。" + ir_desc
        schema = ir_schema
    if method in ("review", "feedback"):
        prompt += (
            "\n直前の回答\n"
            + previous
            + "\n元資料と条件を再確認し、正しければそのまま、間違いがあれば訂正して最終回答を返す。"
        )
        if method == "feedback":
            obj0, _ = unpack(previous)
            errors = checks(domain, p, obj0)
            if not errors:
                return None
            prompt += "\n機械による検査結果\n" + "\n".join(errors)
    return dict(
        prompt=prompt,
        instructions=BASE,
        schema=None if method == "plain" else schema,
        image=image,
    )
