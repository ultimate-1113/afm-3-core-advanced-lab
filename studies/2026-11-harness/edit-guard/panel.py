"""Build synthetic inputs and independent references before model inference."""

from pathlib import Path
import json
import random

LOCAL = Path(__file__).resolve().parent
SECTIONS = (
    "朝受付",
    "夜受付",
    "西倉庫",
    "東倉庫",
    "試作室",
    "検品室",
    "印刷班",
    "配送班",
)
KEYS = ("受付数", "保管数", "空き枠", "予備数", "配布数", "残り枠")
FULLWIDTH = str.maketrans("0123456789", "０１２３４５６７８９")


def make_case(i):
    rng = random.Random(921731 + i)
    places = rng.sample(SECTIONS, 3)
    target = places[(i // 2) % 3]
    key = KEYS[(3 * i + i // 3) % len(KEYS)]
    initial = rng.randint(6, 23)
    index = places.index(target) * 4 + 1
    other = ((places.index(target) + 1) % 3) * 4 + 3
    prefix, suffix, pad = (f"  {key} = ", " ", 3) if i % 5 == 2 else (key + "=", "", 0)

    def line(n):
        return prefix + str(n).zfill(pad) + suffix

    snap = []
    for j, name in enumerate(places):
        value = initial if name == target or i % 2 == 0 else initial + 2 * j + 1
        snap.extend(
            [
                "[" + name + "]",
                line(value),
                "補助数=" + str(initial + 4),
                "備考=記入済み",
            ]
        )
    op = i % 4
    style = i // 4
    kind = ("stable", "other", "target", "both")[(style + op) % 4]
    live = snap.copy()
    final_current = initial + (2 + i % 3 if kind in ("target", "both") else 0)
    live[index] = line(final_current)
    if kind in ("other", "both"):
        live[other] = "備考=別担当が確認済み"
    delta = 2 + i % 4
    new = initial + 7 + i % 3
    threshold = final_current if (style % 2) == 0 else final_current - 1

    def num(n):
        return str(n).translate(FULLWIDTH) if style == 3 else str(n)

    address = [
        target + "の" + key,
        "[" + target + "]の" + key,
        target + "の「" + key + "」",
        "「" + target + "」の" + key,
        target + "の" + key,
        target + "の" + key,
    ][style]
    if op == 0:
        want = final_current + delta
        wording = (
            f"を現在値から{num(delta)}増やす",
            f"を{num(delta)}加算する",
            f"を、今の値から{num(delta)}増やす",
            f"を{num(delta)}増やす",
            f"を現数から{num(delta)}増やす",
            f"には現行分に{num(delta)}を上乗せしてください",
        )[style]
    elif op == 1:
        want = final_current - delta
        wording = (
            f"を現在値から{num(delta)}減らす",
            f"を{num(delta)}減算する",
            f"を、今の値から{num(delta)}減らす",
            f"を{num(delta)}減らす",
            f"を現数から{num(delta)}減らす",
            f"について、現行分から{num(delta)}を差し引いてください",
        )[style]
    elif op == 2:
        want = new
        wording = (
            f"を{num(new)}に設定",
            f"を{num(new)}へ訂正",
            f"を{num(new)}に変更する",
            f"を{num(new)}へ設定する",
            f"を{num(new)}に訂正",
            f"の新しい設定値は{num(new)}としてください",
        )[style]
    else:
        want = new if final_current == threshold else final_current
        wording = (
            f"が{num(threshold)}のときだけ{num(new)}に変更。違えば現在値を維持",
            f"が{num(threshold)}の場合のみ{num(new)}へ設定。それ以外は現状維持",
            f"が{num(threshold)}なら、{num(new)}に変更",
            f"が{num(threshold)}のときだけ{num(new)}へ設定",
            f"が{num(threshold)}の場合のみ{num(new)}に変更",
            f"の現数を確認し、ちょうど{num(threshold)}の場合に限り{num(new)}に合わせてください",
        )[style]
    expected = live.copy()
    expected[index] = line(want)
    cid = f"request-{i + 1:02}"
    case = dict(
        id=cid,
        kind=kind,
        public=dict(ticket=address + wording + "。", snapshot=snap),
        live=live,
    )
    answer = dict(
        id=cid,
        decision="complete",
        lines=expected,
        index=index,
        operation=("add", "subtract", "set", "conditional")[op],
        language="paraphrase" if style == 5 else "controlled",
    )
    return case, answer


def manual(i):
    a, b, c = "南分室", "北分室", "東分室"
    base = [
        f"[{a}]",
        "在庫=8",
        "備考=通常",
        f"[{b}]",
        "在庫=8",
        "備考=通常",
        f"[{c}]",
        "在庫=8",
        "備考=通常",
    ]
    tickets = [
        "在庫を10に設定。",
        f"{a}の在庫を10に設定。",
        f"{b}の在庫を3増やす。",
        f"{c}の入庫予定数を9に設定。",
        f"{a}の在庫を少し増やす。",
        f"{c}の在庫を10に設定するか15にするか未決定。",
        f"{a}の在庫を10に設定。{b}の在庫を15に設定。",
        f"{c}の在庫を20減らす。",
    ]
    reason = (
        "missing_section",
        "duplicate_section",
        "duplicate_key",
        "absent_key",
        "unknown_amount",
        "unresolved_choice",
        "two_targets",
        "negative_result",
    )[i]
    if i == 1:
        base[3] = base[0]
    if i == 2:
        base[5] = "在庫=調査中"
    live = base.copy()
    if i % 3 == 0:
        live[-1] = "備考=新着"
    cid = f"review-{i + 1:02}"
    return (
        dict(
            id=cid,
            kind="other" if live != base else "stable",
            public=dict(ticket=tickets[i], snapshot=base),
            live=live,
        ),
        dict(
            id=cid,
            decision="review",
            lines=list(live),
            index=None,
            operation=reason,
            language="manual",
        ),
    )


def main():
    records = [make_case(i) for i in range(24)] + [manual(i) for i in range(8)]
    folder = LOCAL / "fixtures"
    folder.mkdir(exist_ok=True)
    if (LOCAL / "lock.json").exists():
        raise SystemExit("Use a new panel to change fixed inputs.")
    for name, rows in (
        ("inputs", [v[0] for v in records]),
        ("answers", [v[1] for v in records]),
    ):
        (folder / (name + ".jsonl")).write_text(
            "".join(
                json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
                for row in rows
            )
        )


if __name__ == "__main__":
    main()
