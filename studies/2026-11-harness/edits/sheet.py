"""In-memory document editor. All numbers and requests in the panel are synthetic."""

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import STR, arr, js, obj, parse_json
from protocol import BASE, unpack

FULL = obj(lines=arr(STR))
PATCH = obj(edits=arr(obj(section=STR, old=STR, new=STR)))


def scenarios():
    # Each group includes a relative update, an absolute update, and a conditional update.
    result = []
    for i in range(12):
        group = i // 3
        target = ("東窓口", "西窓口", "北窓口")[i % 3]
        key = ("予約枠", "棚番号", "持出枠")[i % 3]
        quantity = 7 + i
        other = "北窓口" if target != "北窓口" else "西窓口"
        initial = []
        for section in ("東窓口", "西窓口", "北窓口"):
            initial.extend([f"[{section}]", f"{key}={quantity}", f"備考=棚卸{i + 1}"])
        instructions = [
            f"{target}の{key}を、反映時点の値から3増やす。",
            f"{target}の{key}を{quantity + 5}に設定。",
            f"{target}の{key}が{quantity}のときだけ{quantity + 4}に変更。違えば現在値を維持。",
        ]
        live = list(initial)
        target_at = live.index("[" + target + "]") + 1
        other_at = live.index("[" + other + "]") + 1
        if group in (1, 3):
            live[other_at + 1] = f"備考=現地確認{i + 1}"
        if group in (2, 3):
            live[target_at] = f"{key}={quantity + 2}"
        visible = dict(ticket=instructions[i % 3], snapshot=initial)
        scenario = dict(
            id=f"edit-{i + 1:02}",
            kind=["stable", "unrelated", "target", "both"][group],
            public=visible,
            live=live,
        )
        gold = list(live)
        live_qty = int(live[target_at].split("=")[1])
        new_qty = (
            live_qty + 3,
            quantity + 5,
            quantity + 4 if live_qty == quantity else live_qty,
        )[i % 3]
        gold[target_at] = f"{key}={new_qty}"
        result.append(
            (scenario, dict(id=scenario["id"], lines=gold, target_index=target_at))
        )
    return result


def req(case, method):
    fresh = method.startswith("fresh_")
    mode = method.removeprefix("fresh_")
    input_lines = case["live"] if fresh else case["public"]["snapshot"]
    common = (
        "合成の管理表を1回更新する。依頼の対象以外は空白を含めすべて保存する。"
        "角括弧は区画の見出し。各行を1つの文字列として扱う。\n依頼\n"
        + case["public"]["ticket"]
    )
    if fresh:
        common += "\n適用直前に版の変更を検出して読み直した。次が現在の全文。"
    else:
        common += "\n読み取り時の全文"
    common += "\n" + js(input_lines)
    if mode == "patch":
        task = (
            "\n置換案をJSONのedits配列で返す。sectionは角括弧付きの見出しを完全転記。"
            "oldは置換前の1行、newはその置換後の1行を完全転記。変更が不要ならeditsは空配列。"
        )
    else:
        task = "\n更新後の全文を元の行順のJSON文字列配列linesに入れて返す。"
    return dict(
        prompt=common + task,
        instructions=BASE,
        schema=None if mode == "plain" else PATCH if mode == "patch" else FULL,
        image=None,
    )


def apply(lines, response, method):
    answer, _ = unpack(response)
    if not isinstance(answer, dict):
        return None, "invalid_json"
    if method in ("full", "plain"):
        val = answer.get("lines")
        if (
            set(answer) != {"lines"}
            or not isinstance(val, list)
            or not all(type(x) is str for x in val)
        ):
            return None, "invalid_full"
        return val, "applied"
    edits = answer.get("edits")
    if set(answer) != {"edits"} or not isinstance(edits, list):
        return None, "invalid_edits"
    staged = list(lines)
    for change in edits:
        if (
            not isinstance(change, dict)
            or set(change) != {"section", "old", "new"}
            or not all(type(x) is str and "\n" not in x for x in change.values())
        ):
            return None, "invalid_edit"
        section, old, new = (change[k] for k in ("section", "old", "new"))
        if (
            not (section.startswith("[") and section.endswith("]"))
            or staged.count(section) != 1
        ):
            return None, "missing_section"
        if old.startswith("[") or new.startswith("["):
            return None, "invalid_edit"
        start = staged.index(section) + 1
        end = next(
            (j for j in range(start, len(staged)) if staged[j].startswith("[")),
            len(staged),
        )
        hits = [j for j in range(start, end) if staged[j] == old]
        if len(hits) != 1:
            return None, "context_mismatch"
        staged[hits[0]] = new
    return staged, ("applied" if edits else "noop")
