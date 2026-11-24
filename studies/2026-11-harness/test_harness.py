import unittest
from common import DATA, read_rows
from engine import allocation, timeline, invoice
from geometry import read_table
from protocol import canonical, checks, request, unpack


class HarnessTests(unittest.TestCase):
    def test_solver_and_authored_reference_agree(self):
        key = {x["id"]: x for x in read_rows(DATA / "answers.jsonl")}
        for c in read_rows(DATA / "inputs.jsonl"):
            g = key[c["id"]]
            if c["domain"] == "allocation":
                self.assertEqual(
                    allocation(c["payload"], g["ir"]), g["answer"], c["id"]
                )
            if c["domain"] == "timeline":
                self.assertEqual(timeline(c["payload"], g["ir"]), g["answer"], c["id"])

    def test_input_and_schema_ablation(self):
        for c in read_rows(DATA / "inputs.jsonl"):
            plain = request(c, "plain", [])
            guided = request(c, "schema", [])
            for name in ("prompt", "image", "instructions"):
                self.assertEqual(plain[name], guided[name])
            self.assertIsNone(plain["schema"])
            self.assertIsInstance(guided["schema"], dict)

    def test_format_vs_content(self):
        self.assertEqual(
            unpack('説明\n```json\n{"cpu":4,"memory":8}\n```'),
            ({"cpu": 4, "memory": 8}, False),
        )
        for duplicate in ['{"a":1,"a":2}', '{"a":1}\n{"a":2}']:
            self.assertIsNone(unpack(duplicate)[0])
        self.assertIsNone(canonical("timeline", {}, dict(cpu=True, memory=8)))

    def test_invalid_ocr_is_not_invented(self):
        self.assertEqual(read_table([]), [])
        p = {"order": [dict(sku="K-1", ordered=2)]}
        self.assertIsNone(
            invoice(
                p,
                [["K-1", "箱", "", "通常品"]],
                dict(rows=[dict(sku="K-1", exclude=0)]),
            )
        )
        self.assertIsNone(
            invoice(
                p,
                [["K-1", "箱", "2", "通常品"]],
                dict(rows=[dict(sku="K-1", exclude=3)]),
            )
        )

    def test_validator_does_not_use_optimum(self):
        p = dict(
            catalog={k: dict(stock=2, rate=10, watts=5) for k in "ABC"},
            ticket="毎秒10件以上。電力を最小に。",
        )
        self.assertEqual(
            checks("allocation", p, dict(A=2, B=0, C=0, rate=20, watts=10)), []
        )
        self.assertTrue(checks("allocation", p, dict(A=0, B=0, C=0, rate=10, watts=2)))


if __name__ == "__main__":
    unittest.main()
