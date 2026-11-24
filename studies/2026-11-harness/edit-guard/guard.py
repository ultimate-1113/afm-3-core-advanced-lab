"""Validate single-cell edits against the user's request and the current document."""

from dataclasses import dataclass
import re
import threading
from typing import Tuple

NUMBER = r"([0-9０-９]+)"
RELATIVE = re.compile(
    r"を[、,]?(?:反映時点の値から|現在値から|今の値から|現数から)?"
    + NUMBER
    + r"(増やす|減らす|加算する|減算する)"
)
ABSOLUTE = re.compile(r"を" + NUMBER + r"(?:に|へ)(?:設定|訂正|変更)(?:する)?")
CONDITIONAL = re.compile(
    r"が"
    + NUMBER
    + r"(?:のときだけ|の場合のみ|なら)[、,]?"
    + NUMBER
    + r"(?:に|へ)(?:変更|設定)(?:する)?"
    + r"(?:。(?:違えば現在値を維持|それ以外は現状維持))?"
)
HEADING = re.compile(r"\[([^\[\]\r\n]+)\]")
VALUE = re.compile(r"([ \t]*)([0-9]+)([ \t]*)")


class Review(ValueError):
    """The harness could not establish permission for this update."""


@dataclass(frozen=True)
class Cell:
    section: str
    key: str
    index: int
    old: str
    prefix: str
    digits: str
    suffix: str
    current: int
    desired: int
    condition_met: bool

    def render(self, value):
        digits = str(value)
        if self.digits.startswith("0"):
            digits = digits.zfill(len(self.digits))
        return self.prefix + digits + self.suffix

    @property
    def changed(self):
        return self.desired != self.current


def effect(clause, current):
    match = CONDITIONAL.fullmatch(clause)
    if match:
        met = current == int(match[1])
        return (int(match[2]) if met else current), met
    match = ABSOLUTE.fullmatch(clause)
    if match:
        return int(match[1]), True
    match = RELATIVE.fullmatch(clause)
    if match:
        delta = int(match[1])
        if match[2] in ("減らす", "減算する"):
            delta = -delta
        if current + delta < 0:
            raise Review("negative_result")
        return current + delta, True
    raise Review("unrecognized_clause")


def bind(ticket, lines):
    """Resolve a literal section and key, then parse the entire remaining clause."""
    if not isinstance(ticket, str) or "\n" in ticket or "\r" in ticket:
        raise Review("invalid_ticket")
    text = ticket.strip().removesuffix("。")
    if any(
        line.lstrip().startswith("[") and not HEADING.fullmatch(line) for line in lines
    ):
        raise Review("invalid_section_heading")
    headers = [
        (i, line, m[1])
        for i, line in enumerate(lines)
        if (m := HEADING.fullmatch(line))
    ]
    matches = []
    for j, (i, title, name) in enumerate(headers):
        prefixes = (name + "の", title + "の", "「" + name + "」の")
        prefix = next((p for p in prefixes if text.startswith(p)), None)
        if prefix is not None:
            stop = headers[j + 1][0] if j + 1 < len(headers) else len(lines)
            matches.append((title, text[len(prefix) :], i + 1, stop))
    if len(matches) != 1:
        raise Review("unknown_or_ambiguous_section")
    title, rest, start, end = matches[0]
    candidates = []
    for i in range(start, end):
        left, sep, value = lines[i].partition("=")
        key = left.strip()
        if not (sep and key):
            continue
        for token in (key, "「" + key + "」"):
            if rest.startswith((token + "を", token + "が")):
                candidates.append((i, left, key, value, rest[len(token) :]))
                break
    if len(candidates) != 1:
        raise Review("unknown_or_ambiguous_key")
    i, left, key, value, clause = candidates[0]
    match = VALUE.fullmatch(value)
    if not match:
        raise Review("non_numeric_cell")
    try:
        current = int(match[2])
        desired, met = effect(clause, current)
    except Review:
        raise
    except ValueError as err:
        raise Review("invalid_number") from err
    return Cell(
        title,
        key,
        i,
        lines[i],
        left + "=" + match[1],
        match[2],
        match[3],
        current,
        desired,
        met,
    )


def proposed_line(cell, proposal, mode):
    if mode == "rules":
        return cell.render(cell.desired)
    if mode == "scoped":
        if not cell.changed:
            return cell.old
        if (
            not isinstance(proposal, dict)
            or set(proposal) != {"value"}
            or type(proposal["value"]) is not int
        ):
            raise Review("invalid_value")
        if proposal["value"] != cell.desired:
            raise Review("value_mismatch")
        return cell.render(proposal["value"])
    if (
        not isinstance(proposal, dict)
        or set(proposal) != {"edits"}
        or not isinstance(proposal["edits"], list)
    ):
        raise Review("invalid_edits")
    edits = proposal["edits"]
    if not edits:
        if mode == "checked" and cell.changed:
            raise Review("required_edit_missing")
        return cell.old
    # Validate the whole proposal before touching any line, including mixed valid/invalid edits.
    if len(edits) != 1:
        raise Review("multiple_edits")
    edit = edits[0]
    if not isinstance(edit, dict) or set(edit) != {"section", "old", "new"}:
        raise Review("invalid_edit")
    if edit["section"] != cell.section or edit["old"] != cell.old:
        raise Review("wrong_target_or_old_line")
    new = edit["new"]
    if not isinstance(new, str) or not re.fullmatch(
        re.escape(cell.prefix) + r"[0-9]+" + re.escape(cell.suffix), new
    ):
        raise Review("wrong_key_or_shape")
    if mode == "checked" and new != cell.render(cell.desired):
        raise Review(
            "condition_not_met" if not cell.condition_met else "value_mismatch"
        )
    return new


@dataclass(frozen=True)
class Snapshot:
    revision: int
    lines: Tuple[str, ...]


@dataclass(frozen=True)
class Receipt:
    status: str
    reason: str
    revision: int


def valid_lines(lines):
    if isinstance(lines, (str, bytes)):
        raise ValueError("Expected a sequence of lines")
    value = tuple(lines)
    if not all(isinstance(s, str) and "\r" not in s and "\n" not in s for s in value):
        raise ValueError("Document contains a non-line")
    return value


class Sheet:
    """A single shared in-memory document, with atomic comparison and write."""

    def __init__(self, lines):
        self._lines = valid_lines(lines)
        self._revision = 0
        self._finished = {}
        self._lock = threading.Lock()

    def read(self):
        with self._lock:
            return Snapshot(self._revision, self._lines)

    def external_edit(self, lines):
        """Simulate another writer publishing a document version."""
        updated = valid_lines(lines)
        with self._lock:
            if self._lines != updated:
                self._revision += 1
                self._lines = updated

    def _prior(self, request_id, ticket):
        previous = self._finished.get(request_id)
        if previous is None:
            return None
        previous_ticket, receipt = previous
        if previous_ticket != ticket:
            return Receipt("held", "request_id_reused", self._revision)
        return Receipt("duplicate", receipt.status, receipt.revision)

    def previous(self, request_id, ticket):
        if not isinstance(request_id, str) or not request_id.strip():
            raise ValueError("A request ID is required")
        with self._lock:
            return self._prior(request_id, ticket)

    def commit(self, request_id, ticket, seen_revision, mode, proposal=None):
        if mode not in ("scope", "checked", "scoped", "rules"):
            raise ValueError("Unknown commit policy")
        if not isinstance(request_id, str) or not request_id.strip():
            raise ValueError("A request ID is required")
        with self._lock:
            previous = self._prior(request_id, ticket)
            if previous is not None:
                return previous
            if type(seen_revision) is not int or self._revision != seen_revision:
                return Receipt("held", "stale_revision", self._revision)
            try:
                cell = bind(ticket, self._lines)
                new = proposed_line(cell, proposal, mode)
            except Review as err:
                return Receipt("held", str(err), self._revision)
            if new == cell.old:
                receipt = Receipt("noop", "unchanged", self._revision)
            else:
                self._lines = (
                    self._lines[: cell.index] + (new,) + self._lines[cell.index + 1 :]
                )
                self._revision += 1
                receipt = Receipt(
                    "applied",
                    "verified" if mode != "scope" else "scope_only",
                    self._revision,
                )
            self._finished[request_id] = (ticket, receipt)
            return receipt


def target_for_model(ticket, view):
    try:
        cell = bind(ticket, view.lines)
    except Review:
        return None
    return cell if cell.changed else None


def update(sheet, request_id, ticket, mode, propose=None):
    """Read, prepare outside the lock and commit. Reread at most once on a race."""
    previous = sheet.previous(request_id, ticket)
    if previous is not None:
        return previous
    for attempt in (0, 1):
        view = sheet.read()
        proposal = None
        if mode in ("scope", "checked"):
            proposal = propose(view, None)
        elif mode == "scoped":
            cell = target_for_model(ticket, view)
            if cell is not None:
                proposal = propose(view, cell)
        receipt = sheet.commit(request_id, ticket, view.revision, mode, proposal)
        if receipt.reason != "stale_revision" or attempt == 1:
            return receipt
