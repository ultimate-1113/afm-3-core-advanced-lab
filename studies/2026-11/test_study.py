from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from fixtures import notice, update
from fm_client import Client, Pause, quota_state
from tasks import apply_actions, grade, parse_json, select_paragraphs


class StudyTests(unittest.TestCase):
    def test_abstention_needs_current_support(self):
        c = notice("held", 0)
        c["domain"] = "notice"
        gold = c["expected"]
        facts = [
            d
            for d in c["payload"]["documents"]
            if d["subject"] == c["payload"]["target"] and d["status"] == "確定"
        ]
        result = {
            k: dict(
                value=v,
                source=facts[int(k in ("people", "place"))]["id"],
                quote=facts[int(k in ("people", "place"))]["text"],
            )
            for k, v in gold.items()
        }
        self.assertTrue(grade(c, "evidence", result)["exact"])
        result["place"]["source"] = c["payload"]["documents"][0]["id"]
        scores = grade(c, "evidence", result)
        self.assertEqual(scores["rejected_evidence"], ["place"])
        self.assertEqual(scores["omitted"], 1)
        self.assertFalse(scores["exact"])

    def test_correct_final_state_can_hide_extra_effects(self):
        c = update("dev", 1)
        c["domain"] = "update"
        trace = c["expected"]["trace"] * 2
        scores = grade(c, "batch", {"actions": trace})
        self.assertTrue(scores["state"])
        self.assertFalse(scores["trace"])
        self.assertEqual(scores["extra_actions"], 2)

    def test_strict_json_and_operations(self):
        self.assertIsNone(parse_json('{"x":1,"x":2}'))
        self.assertEqual(
            apply_actions({"T1": 1}, [{"op": "set", "id": "T1", "quantity": True}]),
            ({"T1": 1}, ["invalid_arguments"]),
        )

    def test_quota_and_resume(self):
        self.assertEqual(
            [
                quota_state(s)
                for s in [
                    "PCC: below limit",
                    "PCC: approaching limit",
                    "PCC: limit reached",
                    "unavailable",
                    "???",
                ]
            ],
            ["below", "approaching", "reached", "unavailable", "unknown"],
        )
        with tempfile.TemporaryDirectory() as folder:
            client = Client(Path(folder))
            req = {"prompt": "合成試験", "schema": None, "image": None}
            try:
                with (
                    patch(
                        "fm_client.lines",
                        side_effect=[
                            ("PCC: below limit", 0),
                            ("PCC: approaching limit", 0),
                        ],
                    ),
                    patch(
                        "fm_client.invoke", return_value={"status": "ok", "text": "{}"}
                    ) as send,
                ):
                    client.generate("t", "pcc", "direct", 0, req)
                    client.generate("t", "pcc", "direct", 0, req)
                    with self.assertRaises(Pause):
                        client.generate("u", "pcc", "direct", 0, req)
                    self.assertEqual(send.call_count, 1)
            finally:
                client.db.close()

    def test_retriever_has_no_answer_input(self):
        p = {"project": "松港", "paragraphs": ["一般記録"] * 40}
        p["paragraphs"][30] = "松港の決定"
        docs, indices = select_paragraphs(p)
        self.assertEqual(len(indices), 12)
        self.assertIn(30, indices)
        self.assertEqual(docs, [p["paragraphs"][i] for i in indices])


if __name__ == "__main__":
    unittest.main()
