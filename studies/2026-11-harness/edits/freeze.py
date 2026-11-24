from pathlib import Path
from sheet import scenarios
from common import sha, write_json, write_rows

here = Path(__file__).resolve().parent
if (here / "lock.json").exists():
    raise SystemExit("Create a separate panel to change the design.")
data = scenarios()
write_rows(here / "fixtures/inputs.jsonl", [x for x, _ in data])
write_rows(here / "fixtures/answers.jsonl", [g for _, g in data])
names = [
    "design.md",
    "sheet.py",
    "run.py",
    "report.py",
    "Run Edits.command",
    "fixtures/inputs.jsonl",
    "fixtures/answers.jsonl",
    "../Run Harness.command",
    "../run.py",
    "../protocol.py",
]
write_json(here / "lock.json", {name: sha(here / name) for name in names})
