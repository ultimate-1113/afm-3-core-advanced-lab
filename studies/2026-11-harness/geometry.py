"""Make OCR rows from observed boxes and header positions, without drawing coordinates."""

import json
import statistics
import subprocess
import time
import unicodedata
from pathlib import Path
from common import DATA, read_rows, write_rows


def norm(text):
    return unicodedata.normalize("NFKC", text).replace(" ", "").strip()


def read_table(boxes):
    if not boxes:
        return []
    lines = []
    for box in sorted(boxes, key=lambda b: b["y"]):
        if lines:
            mid = statistics.median(b["y"] for b in lines[-1])
            height = statistics.median(b["height"] for b in lines[-1])
            if abs(mid - box["y"]) < 0.65 * max(box["height"], height):
                lines[-1].append(box)
                continue
        lines.append([box])
    columns = ["品番", "品名", "納入数", "備考"]
    for index, line in enumerate(lines):
        heads = {norm(b["text"]): b["x"] for b in line}
        if all(k in heads for k in columns):
            anchors = [heads[k] for k in columns]
            if anchors != sorted(anchors):
                return []
            rows = []
            for group in lines[index + 1 :]:
                cells = [[], [], [], []]
                for b in sorted(group, key=lambda q: q["x"]):
                    col = min(range(4), key=lambda j: abs(b["x"] - anchors[j]))
                    cells[col].append(b["text"])
                rows.append([" ".join(words) for words in cells])
            return rows
    return []


def observe(tool, inputs, output):
    result = []
    for c in inputs:
        if c["domain"] != "invoice":
            continue
        start = time.perf_counter()
        boxes = json.loads(
            subprocess.check_output([tool, DATA / c["payload"]["image"]], timeout=90)
        )
        rows = read_table(boxes)
        result.append(
            dict(
                id=c["id"], boxes=boxes, rows=rows, seconds=time.perf_counter() - start
            )
        )
    write_rows(output, result)


if __name__ == "__main__":
    import sys

    observe(
        Path(sys.argv[1]).resolve(), read_rows(DATA / "inputs.jsonl"), Path(sys.argv[2])
    )
