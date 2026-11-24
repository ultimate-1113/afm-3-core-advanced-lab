"""Maintainer command, executed before the first inference of a new panel."""

from common import DATA, HERE, sha, write_json


def main():
    names = [
        "Boxes.swift",
        "Run Harness.command",
        "common.py",
        "engine.py",
        "geometry.py",
        "grade.py",
        "make_fixtures.py",
        "protocol.md",
        "protocol.py",
        "report.py",
        "run.py",
        "../2026-11/tasks.py",
        "../2026-11/fm_client.py",
        "../2026-11/fixtures.py",
        "../2026-11/Vision.swift",
    ]
    names += sorted(
        p.relative_to(HERE).as_posix() for p in DATA.rglob("*") if p.is_file()
    )
    if (HERE / "lock.json").exists():
        raise SystemExit(
            "A manifest already exists. Use a new study directory for a different protocol."
        )
    write_json(
        HERE / "lock.json",
        dict(panel="2026-11-harness", sha256={n: sha(HERE / n) for n in names}),
    )


if __name__ == "__main__":
    main()
