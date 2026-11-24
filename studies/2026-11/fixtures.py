"""Generate the synthetic, source-disjoint tasks and the preselected shared panel."""

import hashlib
import json
from pathlib import Path
import struct
import subprocess
import tempfile
import zlib

HERE = Path(__file__).resolve().parent
DATA = HERE / "fixtures"
FIELDS = ("date", "time", "place", "people")
CONDITIONS = ("supported", "partial", "missing", "superseded")
PLACES = (
    "桐ホール",
    "藤会館",
    "潮見工房",
    "梅交流室",
    "楓展示室",
    "泉講堂",
    "椿広場",
    "港会議室",
    "杉研修室",
    "浜実習室",
    "森資料室",
)
TEAMS = (
    "設計班",
    "運営班",
    "会計班",
    "企画班",
    "広報班",
    "編集班",
    "制作班",
    "検査班",
    "配送班",
    "調査班",
    "品質班",
    "受付班",
)
PRODUCTS = (
    "紙封筒",
    "留め金",
    "保管箱",
    "仕切板",
    "案内札",
    "緩衝材",
    "紙袋",
    "紙台紙",
)
KINDS = ("notice", "delivery", "update")


def js(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def token_count(value):
    proc = subprocess.run(
        ["/usr/bin/fm", "count-tokens", "--quiet", value],
        capture_output=True,
        text=True,
        check=True,
        timeout=35,
    )
    return int(proc.stdout.strip())


def notice(split, i):
    group, rotation = divmod(i, 4)
    source = group + (0 if split == "dev" else 13)
    condition = CONDITIONS[rotation]
    target = f"調整会{104 + 7 * source}"
    other = f"調整会{105 + 7 * source}"
    place, team = PLACES[source % len(PLACES)], TEAMS[source % len(TEAMS)]
    second = TEAMS[(source + 2) % len(TEAMS)]
    y, m, d = 2027 + source % 3, 2 + source % 9, 4 + source % 19
    date, t = f"{y}-{m:02d}-{d:02d}", f"{9 + source % 8:02d}:30"
    docs = []

    def add(scope, state, body):
        docs.append(
            dict(id=f"D{len(docs) + 1}", subject=scope, status=state, text=body)
        )

    old = "候補は2026年1月5日09:00、北分室。参加は記録班。"
    if rotation % 2 == 0:
        add(other, "確定", f"{date} 13:00 東会館。出席は受付班。")
    add(target, "失効" if condition == "superseded" else "案", old)
    expected = dict(date="", time="", place="", people=[])
    if condition in ("supported", "superseded"):
        add(target, "確定", f"開催日は{y}年{m}月{d}日。開始は{t}。")
        add(target, "確定", f"会場は{place}。出席は{team}と{second}。")
        expected.update(date=date, time=t, place=place, people=[team, second])
    elif condition == "partial":
        add(target, "確定", f"{m}月{d}日の{t}に集合。会場は{place}。参加班は調整中。")
        expected.update(time=t, place=place)
    else:
        add(target, "参考", "前回資料の転載。日程と担当は確認中。")
    if rotation % 2:
        add(other, "確定", "2033年4月8日08:15 西別館。参加は点検班。")
    if condition == "superseded":
        add(target, "失効", "旧版を再掲。2024年3月21日14:00、南別室。出席は点検班。")
    return dict(
        family=f"notice-{source}",
        condition=condition,
        payload=dict(target=target, documents=docs),
        expected=expected,
    )


def delivery(split, i):
    j = i + (10 if split == "dev" else 90)
    skus = [f"{'KLMN'[k]}-{120 + j * 3 + k}" for k in range(4)]
    order = []
    for k, sku in enumerate(skus):
        name = PRODUCTS[(j + k) % len(PRODUCTS)]
        order.append(
            dict(
                sku=sku,
                name=name,
                alias=name[1:] + "型",
                ordered=3 + (j * 3 + k * 5) % 16,
            )
        )
    rows, received = [], {s: 0 for s in skus}
    for k in [(j + v) % 4 for v in range(4)]:
        p = order[k]
        if i % 5 == 3 and k == 2:
            continue
        net = p["ordered"] + (1 if k == i % 4 and i % 5 else 0)
        sample = 1 + j % 2 if k == (i + 1) % 4 and i % 5 in (1, 2, 4) else 0
        first = net // 2 if k == (i + 2) % 4 and i % 5 == 4 else net
        ref = "―" if i % 5 == 2 and k == 1 else p["sku"]
        name = p["alias"] if ref == "―" else p["name"]
        rows.append(
            [
                ref,
                name,
                str(first + sample),
                f"うち見本{sample}個" if sample else "通常品",
            ]
        )
        if first < net:
            rows.append([p["sku"], p["name"], str(net - first), "追納分"])
        received[p["sku"]] = net
    mismatch = sorted(p["sku"] for p in order if p["ordered"] != received[p["sku"]])
    sheet = dict(
        number=f"DN-{8100 + j}",
        heading=["納品書", "出荷明細", "納入明細"][i % 3],
        rows=rows,
    )
    return dict(
        family=f"delivery-{j}",
        condition=("standard", "sample", "alias", "missing", "split")[i % 5],
        payload=dict(order=order),
        sheet=sheet,
        expected=dict(received=received, mismatches=mismatch),
    )


def update(split, i):
    j = i + (30 if split == "dev" else 101)
    a, b, c = [f"{k}{j}" for k in "RTJ"]
    start = {a: 4 + j % 5, b: 9 + j % 7}
    val = 5 + j % 9

    def cmd(op, key, q=0):
        return dict(op=op, id=key, quantity=q)

    variants = [
        [
            (f"{a}の数量を{val}に訂正。{b}は現状のまま。", [cmd("set", a, val)]),
            (f"{c}を数量3で新規登録。", [cmd("add", c, 3)]),
        ],
        [
            (f"{c}を{val}個で追加。", [cmd("add", c, val)]),
            (f"{c}の新規分を取り消し、行を削除。", [cmd("delete", c)]),
        ],
        [
            (f"{b}は変更しない。", []),
            (f"{a}の数量を今の値から2増やす。", [cmd("set", a, start[a] + 2)]),
        ],
        [
            (f"{b}を削除。", [cmd("delete", b)]),
            (
                f"別件。{c}を数量{val}で追加。{a}の変更案は見送り。",
                [cmd("add", c, val)],
            ),
        ],
        [
            (f"{a}を{val + 4}にする。", [cmd("set", a, val + 4)]),
            (
                f"{a}について直前の変更を取り消して元の数量に戻す。",
                [cmd("set", a, start[a])],
            ),
        ],
        [
            (f"{a}を残して{b}を削除。", [cmd("delete", b)]),
            (f"{b}を新しく数量{val}で登録し直す。", [cmd("add", b, val)]),
        ],
    ]
    steps = variants[i % 6]
    state = dict(start)
    trace = []
    for _, actions in steps:
        for action in actions:
            trace.append(action)
            if action["op"] == "delete":
                del state[action["id"]]
            else:
                state[action["id"]] = action["quantity"]
    return dict(
        family=f"update-{j}",
        condition=f"flow-{i % 6 + 1}",
        payload=dict(initial=start, requests=[s for s, _ in steps]),
        expected=dict(state=state, trace=trace),
    )


def png_pixels(pgm):
    _, size, depth, data = pgm.split(b"\n", 3)
    w, h = map(int, size.split())
    assert depth == b"255" and len(data) == w * h

    def chunk(kind, body):
        return (
            struct.pack(">I", len(body))
            + kind
            + body
            + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)
        )

    scan = b"".join(b"\0" + data[i : i + w] for i in range(0, len(data), w))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">2I5B", w, h, 8, 0, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(scan, 9))
        + chunk(b"IEND", b"")
    )


def long_doc(band, variant):
    project = ("海風庁舎", "花森別館", "川辺会所")[variant]
    venue = ("桃展示室", "竹研修室", "銀会館")[variant]
    date = ("2028-03-08", "2027-11-13", "2029-04-19")[variant]
    limit = (37, 52, 81)[variant]
    pending = ("送迎", "通訳", "配布物")[variant]
    key = [
        f"{project}の旧版。会場は赤別館、上限は19。最終承認で更新する。",
        f"{project}の担当会議で会場を{venue}に確定し、締切を{date}とする。",
        f"{project}の最終承認。上限を{limit}名に改定。{pending}だけは保留。他の決定は継続。",
    ]

    def render(n):
        cuts = (n // 16 + variant, n // 2 + variant, n - 2 - variant)
        paragraphs = []
        for idx in range(n):
            if idx in cuts:
                body = key[cuts.index(idx)]
            else:
                label = (
                    "海風分室",
                    "花森計画",
                    "川辺倉庫",
                    "海風管理棟",
                    "花森出張所",
                )[idx % 5]
                topic = (
                    "案内係の当番",
                    "備品箱の収納",
                    "週次連絡の担当",
                    "図面の改訂",
                    "通路の表示",
                )[idx % 5]
                body = f"{label}の記録。{topic}について{idx % 71 + 13}件の確認を終えた。会場は第{idx % 9 + 1}室、上限は{idx % 43 + 12}名を予定。次回確認する。"
            paragraphs.append(f"[記録{idx + 1:04d}] {body}")
        return paragraphs

    lo, hi = 14, 900
    while lo < hi:
        mid = (lo + hi) // 2
        n = token_count("\n".join(render(mid)))
        if n < band:
            lo = mid + 1
        else:
            hi = mid
    paragraphs = render(lo)
    return dict(
        id=f"long-{band}-{variant + 1}",
        domain="long",
        split="long",
        family=f"long-project-{variant}",
        condition=str(band),
        payload=dict(project=project, paragraphs=paragraphs),
        document_tokens=token_count("\n".join(paragraphs)),
        expected=dict(venue=venue, deadline=date, limit=limit, pending=pending),
    )


def main():
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--vision", type=Path, required=True)
    p.add_argument("--out", type=Path, default=DATA)
    a = p.parse_args()
    destination = a.out.resolve()
    if (destination / "lock.json").exists():
        raise SystemExit("Fixtures already frozen; use verification for existing data.")
    if destination.exists() and any(destination.iterdir()):
        raise SystemExit("Use an empty fixtures directory.")
    destination.mkdir(exist_ok=True)
    imgs = destination / "images"
    imgs.mkdir()
    cases = []
    with tempfile.TemporaryDirectory() as tmp:
        for split, count in (("dev", 10), ("held", 30)):
            for domain, make in zip(KINDS, (notice, delivery, update)):
                for i in range(count):
                    c = make(split, i)
                    c.update(
                        id=f"{domain}-{split}-{i + 1:02d}", domain=domain, split=split
                    )
                    if domain == "delivery":
                        inp = Path(tmp) / "sheet.json"
                        pgm = Path(tmp) / "sheet.pgm"
                        write_json(inp, c.pop("sheet"))
                        subprocess.run(
                            [a.vision.resolve(), "paint", inp, pgm], check=True
                        )
                        image = imgs / (c["id"] + ".png")
                        image.write_bytes(png_pixels(pgm.read_bytes()))
                        c["payload"]["image"] = "images/" + image.name
                    cases.append(c)
    shared = [f"regression-{i:02d}" for i in range(1, 7)]
    positions = {
        "notice": [1, 2, 3, 4, 17, 18, 19, 20],
        "delivery": [1, 7, 13, 19, 25, 26, 27, 30],
        "update": [1, 8, 15, 22, 29, 30, 13, 20],
    }
    for domain, indices in positions.items():
        shared += [f"{domain}-held-{i:02d}" for i in indices]
    cases += [long_doc(band, v) for v in range(3) for band in (4000, 12000, 24000)]
    (destination / "cases.jsonl").write_text("".join(js(c) + "\n" for c in cases))
    write_json(destination / "shared.json", shared)
    files = {
        str(p.relative_to(destination)): digest(p)
        for p in sorted(destination.rglob("*"))
        if p.is_file()
    }
    write_json(destination / "lock.json", files)


if __name__ == "__main__":
    main()
