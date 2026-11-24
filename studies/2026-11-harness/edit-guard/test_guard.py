import json
from pathlib import Path
from threading import Barrier, Thread
import unittest
from guard import Sheet, update
from model import scoped_request

OLD = Path(__file__).resolve().parent.parent / "edits/fixtures"
LINES = ["[東班]", "枠=8", "備考=東", "[西班]", "枠=8", "備考=西"]
TICKET = "東班の枠を、反映時点の値から3増やす。"


def patch(section="[東班]", old="枠=8", new="枠=11"):
    return {"edits": [dict(section=section, old=old, new=new)]}


class GuardTests(unittest.TestCase):
    def test_same_model_answer_preserves_all_other_lines(self):
        sheet = Sheet(LINES)
        receipt = update(sheet, "one", TICKET, "checked", lambda *_: patch())
        self.assertEqual(receipt.status, "applied")
        self.assertEqual(sheet.read().lines, tuple([LINES[0], "枠=11", *LINES[2:]]))

    def test_unmatched_condition_is_noop_only_if_checked(self):
        ticket = "東班の枠が7のときだけ10に変更。違えば現在値を維持。"
        sheet = Sheet(LINES)
        self.assertEqual(
            sheet.commit("x", ticket, 0, "checked", patch(new="枠=10")).reason,
            "condition_not_met",
        )
        self.assertEqual(
            sheet.commit("x", ticket, 0, "checked", {"edits": []}).status, "noop"
        )
        self.assertEqual(sheet.read().revision, 0)
        self.assertEqual(
            update(
                sheet,
                "other",
                ticket,
                "scoped",
                lambda *_: self.fail("No call required"),
            ).status,
            "noop",
        )

    def test_hold_unknowns_and_conflicting_negation_in_whole_ticket(self):
        cases = [
            (LINES, TICKET + "ただし今回は反映しない。"),
            (LINES, "東班か西班の枠を10に設定。"),
            (LINES, "東班の枠を5に設定。西班の枠を15に設定。"),
            (LINES, "東班の枠を20減らす。"),
            (["[東班]", "枠=調整中"], TICKET),
            (["[東班]", "枠=8", " 枠 =調査中"], TICKET),
            (["[東班]", "枠=8", "[東班]", "枠=4"], TICKET),
            (["[東班]", "[壊れた見出し", "枠=8"], TICKET),
        ]
        for lines, ticket in cases:
            with self.subTest(ticket=ticket, lines=lines):
                sheet = Sheet(lines)
                self.assertEqual(
                    update(
                        sheet,
                        "r",
                        ticket,
                        "scoped",
                        lambda *_: self.fail("Ambiguous request sent"),
                    ).status,
                    "held",
                )
                self.assertEqual(sheet.read().lines, tuple(lines))

    def test_numeric_format_and_exact_names(self):
        sheet = Sheet(["[Ａ班]", "  残数 = ００７ "])
        self.assertEqual(
            sheet.commit("a", "A班の残数を2増やす。", 0, "rules").status, "held"
        )
        sheet = Sheet(["[Ａ班]", "  残数 = 007 "])
        receipt = sheet.commit(
            "b",
            "「Ａ班」の「残数」を２加算する。",
            0,
            "checked",
            patch("[Ａ班]", "  残数 = 007 ", "  残数 = 009 "),
        )
        self.assertEqual(receipt.status, "applied")
        self.assertEqual(sheet.read().lines[-1], "  残数 = 009 ")

    def test_read_aba_and_two_stale_proposals(self):
        sheet = Sheet(LINES)
        other = [*LINES[:-1], "備考=新"]

        def aba(view, cell):
            sheet.external_edit(other)
            sheet.external_edit(LINES)
            return {"value": 11}

        self.assertEqual(
            update(sheet, "r", TICKET, "scoped", aba).reason, "stale_revision"
        )
        self.assertEqual(sheet.read().lines, tuple(LINES))
        self.assertEqual(sheet.read().revision, 4)

    def test_reread_uses_commit_time_value(self):
        sheet = Sheet(LINES)
        starting = []

        def propose(view, cell):
            starting.append(cell.current)
            if len(starting) == 1:
                sheet.external_edit([LINES[0], "枠=10", *LINES[2:]])
            return {"value": cell.current + 3}

        res = update(sheet, "r", TICKET, "scoped", propose)
        self.assertEqual(
            (res.status, starting, sheet.read().lines[1]), ("applied", [8, 10], "枠=13")
        )

    def test_concurrent_duplicates_add_only_once_and_no_replay_call(self):
        sheet = Sheet(LINES)
        barrier = Barrier(2)
        done = []

        def worker():
            def propose(*_):
                barrier.wait(timeout=5)
                return {"value": 11}

            done.append(update(sheet, "same", TICKET, "scoped", propose).status)

        threads = [Thread(target=worker) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=6)
        self.assertCountEqual(done, ["duplicate", "applied"])
        sheet.external_edit([*sheet.read().lines[:-1], "備考=更新済み"])
        self.assertEqual(
            update(
                sheet, "same", TICKET, "scoped", lambda *_: self.fail("Duplicate sent")
            ).status,
            "duplicate",
        )
        self.assertEqual(sheet.read().lines[1], "枠=11")
        self.assertEqual(
            sheet.commit("same", "東班の枠を20に設定。", 2, "rules").reason,
            "request_id_reused",
        )

    def test_wrong_types_no_partial_write(self):
        for proposal in (
            None,
            {"value": True},
            {"value": "11"},
            {"value": 11, "section": "[西班]"},
            {"value": 13},
        ):
            sheet = Sheet(LINES)
            self.assertEqual(
                sheet.commit("one", TICKET, 0, "scoped", proposal).status, "held"
            )
            self.assertEqual(sheet.read().revision, 0)
        sheet = Sheet(LINES)
        self.assertEqual(
            sheet.commit(
                "m",
                TICKET,
                0,
                "checked",
                {"edits": patch()["edits"] + patch("[西班]")["edits"]},
            ).reason,
            "multiple_edits",
        )
        self.assertEqual(sheet.read().lines, tuple(LINES))

    def test_only_original_cell_and_ticket_are_model_visible(self):
        sheet = Sheet(LINES)

        def propose(view, cell):
            r = scoped_request(TICKET, cell)
            self.assertIn("枠=8", r["prompt"])
            for unneeded in ("西班", "備考", "枠=11", "desired"):
                self.assertNotIn(unneeded, r["prompt"])
            return {"value": 11}

        update(sheet, "r", TICKET, "scoped", propose)

    def test_six_corruptions_on_every_original_document(self):
        inputs = [
            json.loads(l) for l in (OLD / "inputs.jsonl").read_text().splitlines()
        ]
        gold = {
            r["id"]: r
            for r in map(json.loads, (OLD / "answers.jsonl").read_text().splitlines())
        }
        count = 0
        for c in inputs:
            g = gold[c["id"]]
            i = g["target_index"]
            live = c["live"]
            section, old, new = live[i - 1], live[i], g["lines"][i]
            key = old.split("=")[0]
            other = next(x for x in live if x.startswith("[") and x != section)
            right = patch(section, old, new)["edits"][0]
            wrong = patch(section, old, key + "=" + str(int(new.split("=")[1]) + 7))[
                "edits"
            ][0]
            mutations = [
                dict(edits=[wrong]),
                patch(other, old, new),
                dict(edits=[right, right]),
                patch(section, old, "備考=99"),
                patch(section, "旧" + old, new),
                dict(edits=[right, dict(wrong, section=other)]),
            ]
            for proposal in mutations:
                sheet = Sheet(live)
                receipt = sheet.commit(
                    "q", c["public"]["ticket"], 0, "checked", proposal
                )
                self.assertEqual(
                    (receipt.status, sheet.read().lines), ("held", tuple(live))
                )
                count += 1
        self.assertEqual(count, 72)


if __name__ == "__main__":
    unittest.main()
