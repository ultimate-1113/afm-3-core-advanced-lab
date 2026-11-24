"""Build the fixed panel. Gold is produced separately and never loaded by the runner."""

import argparse
import itertools
import random
import subprocess
import tempfile
from pathlib import Path
from common import DATA, js, png_pixels, write_rows

# The first two machines are deliberately competitive on watts per request.
# Each row supplies its own catalog, finite stocks and a current (not historical) instruction.
ALLOCATION = [
    (
        [(116, 78, 3), (192, 141, 3), (344, 295, 2)],
        496,
        -1,
        "watts",
        "旧案は600件。確定条件は毎秒496件以上。消費電力を最小に。台数の指定なし。",
    ),
    (
        [(98, 42, 5), (207, 118, 3), (358, 212, 1)],
        390,
        3,
        "units",
        "毎秒390件は必要。設置は3台まで。まず台数が少ない案を選ぶ。",
    ),
    (
        [(104, 62, 3), (208, 124, 2), (310, 226, 1)],
        416,
        4,
        "watts",
        "4台以内で毎秒416件以上。電力を第一に比較する。",
    ),
    (
        [(111, 63, 1), (205, 149, 1), (312, 251, 1)],
        533,
        2,
        "watts",
        "毎秒533件を下回らないこと。使えるのは最大2台。最も省電力の構成を選ぶ。",
    ),
    (
        [(83, 41, 5), (186, 103, 3), (296, 156, 3)],
        370,
        -1,
        "units",
        "台数の上限は設けない。毎秒370件以上を満たす最少台数が希望。",
    ),
    (
        [(93, 54, 3), (182, 96, 2), (279, 154, 2)],
        457,
        3,
        "watts",
        "以前は毎秒390件で足りた。今は毎秒457件以上。3台までで電力を最小にする。",
    ),
    (
        [(126, 75, 0), (186, 122, 3), (315, 207, 2)],
        493,
        3,
        "units",
        "毎秒493件以上、最大3台。優先順位は台数、次が電力。",
    ),
    (
        [(96, 48, 4), (192, 96, 2), (288, 144, 1)],
        384,
        -1,
        "watts",
        "毎秒383件を超えること。台数制限は在庫だけ。第一優先は省電力。",
    ),
    (
        [(152, 91, 1), (205, 131, 1), (363, 252, 0)],
        365,
        -1,
        "units",
        "在庫の範囲で、毎秒365件を確保したい。必要な台数を最小にする。",
    ),
    (
        [(105, 55, 4), (217, 114, 3), (342, 215, 2)],
        525,
        4,
        "units",
        "旧方針の省電力優先は廃止。毎秒525件以上を4台以内で満たし、台数を第一にする。",
    ),
    (
        [(114, 73, 4), (218, 154, 3), (347, 242, 2)],
        462,
        2,
        "watts",
        "設置枠は2台。毎秒462件に届くもののうち電力が最小の案を。",
    ),
    (
        [(101, 57, 5), (202, 114, 3), (303, 171, 2)],
        606,
        3,
        "watts",
        "毎秒606件以上が必要。3台以下。まず消費電力で決める。",
    ),
]


def allocation(i, spec):
    entries, target, limit, priority, text = spec
    catalog = {
        k: dict(rate=r, watts=w, stock=s) for k, (r, w, s) in zip("ABC", entries)
    }
    # Independent exhaustive reference; the runtime solver uses different code.
    ranks = []
    for counts in itertools.product(*(range(s + 1) for _, _, s in entries)):
        n = sum(counts)
        work = sum(x * r for x, (r, _, _) in zip(counts, entries))
        draw = sum(x * w for x, (_, w, _) in zip(counts, entries))
        if work < target or (limit >= 0 and n > limit):
            continue
        order = (draw, n) if priority == "watts" else (n, draw)
        ranks.append((order, counts, work, draw))
    if ranks:
        _, (a, b, c), rate, watts = min(ranks)
        answer = dict(A=a, B=b, C=c, rate=rate, watts=watts)
    else:
        answer = dict.fromkeys(["A", "B", "C", "rate", "watts"], -1)
    return (
        dict(catalog=catalog, ticket=text),
        answer,
        dict(target=target, limit=limit, priority=priority),
    )


# A pair is (operator, argument). Rollbacks refer to the snapshot at or before HHMM.
# Values and final results are specified independently of the runtime executor.
LOGS = [
    (
        [
            ("mem", 8),
            ("mem", 12),
            ("cpu", 4),
            ("mem", 10),
            ("cpu", 6),
            ("cpu_back", 910),
        ],
        (None, 10),
    ),
    ([("cpu", 2), ("mem", 6), ("cpu", 8), ("mem", 14), ("mem_back", 915)], (8, 6)),
    ([("mem", 9), ("cpu", 3), ("cpu", 5), ("mem", 15), ("both_back", 917)], (3, 9)),
    ([("cpu", 7), ("mem", 11), ("skip", 16), ("cpu", 3), ("mem_back", 850)], (3, None)),
    ([("mem", 18), ("cpu", 6), ("mem", 28), ("cpu_back", 905), ("cpu", 4)], (4, 28)),
    (
        [
            ("cpu", 3),
            ("mem", 8),
            ("cpu", 6),
            ("mem", 16),
            ("cpu_back", 915),
            ("mem_back", 929),
        ],
        (3, 8),
    ),
    ([("mem", 7), ("cpu", 2), ("mem", 11), ("both_back", 905), ("cpu", 9)], (9, 7)),
    ([("cpu", 4), ("skip", 24), ("mem", 13), ("cpu", 8), ("mem_back", 918)], (8, None)),
    (
        [("mem", 6), ("cpu", 2), ("mem", 20), ("mem_back", 900), ("both_back", 939)],
        (2, 6),
    ),
    (
        [("cpu", 1), ("mem", 16), ("cpu", 9), ("both_back", 850), ("mem", 10)],
        (None, 10),
    ),
    (
        [
            ("mem", 4),
            ("mem", 12),
            ("cpu", 5),
            ("cpu", 7),
            ("both_back", 920),
            ("cpu_back", 910),
        ],
        (None, 12),
    ),
    (
        [
            ("cpu", 6),
            ("mem", 9),
            ("skip", 2),
            ("mem", 21),
            ("cpu_back", 935),
            ("skip", 12),
        ],
        (6, 21),
    ),
]


def timeline(i, spec):
    events, result = spec
    rows, ops = [], []
    for j, (op, arg) in enumerate(events):
        if op in ("cpu", "mem"):
            label, unit = ("CPU", "コア") if op == "cpu" else ("メモリ", "GB")
            line = [
                f"{label}上限を{arg}{unit}に設定。",
                f"{label}枠は{arg}{unit}へ変更。",
                f"{label}の割当を{arg}{unit}で確定。",
            ][(i + j) % 3]
        elif op == "skip":
            line = f"メモリを{arg}GBにする案は見送り。現行値を維持。"
        else:
            subject = {
                "cpu_back": "CPUだけ",
                "mem_back": "メモリだけ",
                "both_back": "両方",
            }[op]
            stamp = f"{arg // 100:02d}:{arg % 100:02d}"
            line = [
                f"{subject}を{stamp}時点の設定に戻す。",
                f"{stamp}の設定を復元。対象は{subject}。",
                f"{subject}について、{stamp}の時点に巻き戻し。",
            ][(i + j) % 3]
        rows.append(dict(at=f"09:{10 * j:02d}", text=line))
        ops.append(dict(op=op, arg=0 if op == "skip" else arg))
    a, b = result
    return (
        dict(log=rows),
        dict(cpu=-1 if a is None else a, memory=-1 if b is None else b),
        dict(events=ops),
    )


NOTES = [
    ("通常品", 0),
    ("うち見本2個", 2),
    ("全数を検収", 0),
    ("1個は返品", 1),
    ("予備2個も受入可", 0),
    ("検査用を2個除く", 2),
    ("試供品1個を含む", 1),
    ("返品なし", 0),
    ("見本なし", 0),
    ("破損2個は受入不可", 2),
    ("予備1個込みで全数受入", 0),
    ("うち試供用2個", 2),
]


def invoice(i, painter, tmp):
    rng = random.Random(9040 + i)
    names = ["紙封筒", "仕切板", "案内札", "保管箱"]
    aliases = ["封筒型", "板型", "札型", "箱型"]
    order = [
        dict(
            sku=f"{k}-{801 + 4 * i + j}",
            name=names[j],
            alias=aliases[j],
            ordered=rng.randint(6, 19),
        )
        for j, k in enumerate("KLMN")
    ]
    rows, expected_ir = [], []
    totals = {item["sku"]: 0 for item in order}
    perm = list(range(4))
    rng.shuffle(perm)
    for pos, j in enumerate(perm):
        item = order[j]
        if i % 4 == 2 and pos == 3:
            continue
        note, reject = NOTES[i] if pos == 1 else ("通常品", 0)
        net = item["ordered"] + (1 if pos == 0 and i % 3 else 0)
        first = net - 2 if pos == 2 and i % 4 == 3 else net
        sku, name = (
            ("―", item["alias"])
            if pos == 1 and i % 3 == 1
            else (item["sku"], item["name"])
        )
        rows.append([sku, name, str(first + reject), note])
        expected_ir.append(dict(sku=item["sku"], exclude=reject))
        if first < net:
            rows.append([item["sku"], item["name"], str(net - first), "追納分"])
            expected_ir.append(dict(sku=item["sku"], exclude=0))
        totals[item["sku"]] = net
    sheet = dict(
        number=f"DN-{73000 + i}",
        heading=["納品書", "出荷明細", "納入明細"][i % 3],
        rows=rows,
    )
    (tmp / "sheet.json").write_text(js(sheet))
    subprocess.run(
        [painter, "paint", tmp / "sheet.json", tmp / "sheet.pgm"], check=True
    )
    img = f"images/invoice-{i + 1:02}.png"
    (DATA / img).write_bytes(png_pixels((tmp / "sheet.pgm").read_bytes()))
    gold = dict(
        received=totals,
        mismatches=sorted(k["sku"] for k in order if k["ordered"] != totals[k["sku"]]),
    )
    return dict(order=order, image=img), gold, dict(rows=expected_ir)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("painter", type=Path)
    args = ap.parse_args()
    (DATA / "images").mkdir(parents=True, exist_ok=True)
    cases, answers = [], []
    with tempfile.TemporaryDirectory() as path:
        for domain in ("allocation", "timeline", "invoice"):
            for i in range(12):
                if domain == "allocation":
                    payload, gold, ir = allocation(i, ALLOCATION[i])
                elif domain == "timeline":
                    payload, gold, ir = timeline(i, LOGS[i])
                else:
                    payload, gold, ir = invoice(i, args.painter.resolve(), Path(path))
                key = f"{domain}-{i + 1:02}"
                cases.append(dict(id=key, domain=domain, payload=payload))
                answers.append(dict(id=key, answer=gold, ir=ir))
    write_rows(DATA / "inputs.jsonl", cases)
    write_rows(DATA / "answers.jsonl", answers)


if __name__ == "__main__":
    main()
