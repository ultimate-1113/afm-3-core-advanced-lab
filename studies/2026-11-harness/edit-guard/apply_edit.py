"""Read a single JSON job from stdin and print the edited in-memory document."""

import argparse
from dataclasses import asdict
import json
import sys
from guard import Sheet, update
from model import local_proposal
from fm_client import Pause


def unique(pairs):
    out = dict(pairs)
    if len(out) != len(pairs):
        raise ValueError("Duplicate JSON key")
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument(
        "--method", choices=("checked", "scoped", "rules"), default="checked"
    )
    mode = p.parse_args().method
    try:
        job = json.load(sys.stdin, object_pairs_hook=unique)
        if (
            not isinstance(job, dict)
            or not isinstance(job.get("lines"), list)
            or not isinstance(job.get("ticket"), str)
        ):
            raise ValueError("Expected lines and a ticket")
        if mode == "checked" and "proposal" not in job:
            raise ValueError("A patch proposal is required for checked mode")
        sheet = Sheet(job["lines"])
        ticket = job["ticket"]

        def propose(view, cell):
            return (
                local_proposal(ticket, cell)
                if mode == "scoped"
                else job.get("proposal")
            )

        result = update(sheet, job.get("id", "stdin"), ticket, mode, propose)
        print(
            json.dumps(
                dict(**asdict(result), lines=sheet.read().lines), ensure_ascii=False
            )
        )
    except (ValueError, TypeError, Pause) as err:
        p.exit(2, str(err) + "\n")


if __name__ == "__main__":
    main()
