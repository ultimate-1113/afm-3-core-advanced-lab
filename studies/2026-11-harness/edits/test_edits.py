import json
import unittest
from sheet import scenarios, apply
from pathlib import Path
import importlib.util
from common import js

spec = importlib.util.spec_from_file_location(
    "edit_score", Path(__file__).with_name("report.py")
)
scoring = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scoring)


class EditTests(unittest.TestCase):
    def test_context_and_atomicity(self):
        lines = ["[東]", "枠=3", "[西]", "枠=3"]
        first = dict(section="[東]", old="枠=3", new="枠=4")
        self.assertEqual(
            apply(lines, js(dict(edits=[first])), "patch")[0],
            ["[東]", "枠=4", "[西]", "枠=3"],
        )
        result, reason = apply(lines, js(dict(edits=[first, first])), "patch")
        self.assertIsNone(result)
        self.assertEqual(reason, "context_mismatch")
        self.assertEqual(lines[1], "枠=3")

    def test_fixtures_and_rules(self):
        for scenario, gold in scenarios():
            self.assertEqual(
                scoring.rules(scenario["public"]["ticket"], scenario["live"]),
                gold["lines"],
            )

    def test_unknown_and_duplicate_context(self):
        bad = {"edits": [dict(section="[不明]", old="枠=3", new="枠=8")]}
        self.assertIsNone(apply(["[東]", "枠=3"], js(bad), "patch")[0])
        bad["edits"][0]["section"] = "[東]"
        self.assertIsNone(apply(["[東]", "枠=3", "枠=3"], js(bad), "patch")[0])


if __name__ == "__main__":
    unittest.main()
