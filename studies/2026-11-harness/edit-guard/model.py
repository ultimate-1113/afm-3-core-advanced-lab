"""The same one-row Core Advanced adapter is used by the command and experiment."""

from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common import INT, js, obj
from fm_client import available, invoke
from protocol import BASE, unpack

CONTRACT = "更新は、依頼から一意に確定できる非負整数の1セルだけ。不明、複数対象、負数になるときは変更を提案しない。"


def scoped_request(ticket, cell):
    prompt = (
        "依頼の対象の1行を読み取った。更新後の数値を整数valueで返す。"
        "相対変更はその行の現在値を基準にする。\n依頼\n"
        + ticket
        + "\n現在の区画と行\n"
        + js(dict(section=cell.section, line=cell.old))
    )
    return dict(
        prompt=prompt,
        instructions=BASE + " " + CONTRACT,
        schema=obj(value=INT),
        image=None,
    )


def local_proposal(ticket, cell):
    available("system")
    with tempfile.TemporaryDirectory() as tmp:
        response = invoke("system", scoped_request(ticket, cell), Path(tmp))
    return unpack(response["text"])[0] if response["status"] == "ok" else None
