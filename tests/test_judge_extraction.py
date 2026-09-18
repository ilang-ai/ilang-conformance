# -*- coding: utf-8 -*-
"""Judge block selection, schema_valid, padding and --eval parsing
(cases/SCHEMA.md §6.2-§6.5, §8.1; book §5.0 judge, judge填充)."""

import json
import tempfile
import unittest
from pathlib import Path

import support
from support import judge_block, score

jv = score.vendor_module("ilang_judge_validator")

# the SPEC-v5.0-PRE Part II §4 example vector
GOOD_V = {"int": 0.80, "cap": 0.60, "csq": 0.70, "rel": 0.55, "cer": 0.90, "aut": 0.75,
          "rev": 0.85, "evd": 0.80, "sov": 0.95, "ine": 0.60, "ext": 0.90}
GOOD_MODE = jv.f_v5(GOOD_V)
BLOCK = judge_block(GOOD_V, GOOD_MODE)


def extract(*parts):
    return score.judge_extract(jv, "\n".join(parts))


class BlockSelectionTests(unittest.TestCase):
    def test_single_valid_block(self):
        self.assertEqual(extract(*BLOCK), (1, True, GOOD_V, GOOD_MODE))

    def test_no_block(self):
        self.assertEqual(extract("I think the mode is M2."), (0, False, None, None))

    def test_prose_around_the_block(self):
        self.assertTrue(extract("Here is my judgment:", *BLOCK, "Done.")[1])

    def test_field_shaped_line_after_r_rejects(self):
        self.assertFalse(extract(*BLOCK, "X:extra")[1])
        self.assertFalse(extract(*BLOCK, "Note: consistent with f_v5")[1])

    def test_declaration_blank_or_fence_after_r_is_allowed(self):
        for nxt in ("::STATE{@X, a:b}", "", "```"):
            with self.subTest(next_line=nxt):
                self.assertTrue(extract(*BLOCK, nxt)[1])
        self.assertTrue(extract("```ilang", *BLOCK, "```")[1])

    def test_last_block_wins(self):
        bad = list(BLOCK)
        bad[1] = bad[1].replace("int=0.80", "int=0.8")
        self.assertEqual(extract(*bad, *BLOCK)[:2], (2, True))
        self.assertEqual(extract(*BLOCK, *bad)[:2], (2, False))

    def test_header_in_the_last_three_lines_gives_a_short_invalid_block(self):
        self.assertEqual(extract(*BLOCK, BLOCK[0], BLOCK[1])[:2], (2, False))

    def test_three_headers_are_counted(self):
        self.assertEqual(extract(*BLOCK, *BLOCK, *BLOCK)[:2], (3, True))

    def test_surrounding_whitespace_and_crlf(self):
        self.assertTrue(extract(*("  " + x + " \t" for x in BLOCK))[1])
        self.assertTrue(score.judge_extract(jv, "\r\n".join(BLOCK) + "\r\n")[1])

    def test_header_variants_are_not_blocks(self):
        for header in ("::JUDGE{v5}", "::judge{v5.0}", "::JUDGE {v5.0}", "JUDGE{v5.0}"):
            with self.subTest(header=header):
                self.assertEqual(extract(header, *BLOCK[1:])[0], 0)


class SchemaLineTests(unittest.TestCase):
    def assertInvalid(self, lines):
        self.assertFalse(extract(*lines)[1])

    def test_v_line_format(self):
        for old, new in ((",cap=", ", cap="), ("int=0.80,", ""), ("int=0.80", "int=0.8"),
                         ("int=0.80,cap=0.60", "cap=0.60,int=0.80"), ("int=0.80", "int=1.01")):
            b = list(BLOCK)
            b[1] = b[1].replace(old, new, 1)
            with self.subTest(v_line=b[1]):
                self.assertInvalid(b)

    def test_value_one_is_accepted(self):
        v = dict(GOOD_V, int=1.0)
        self.assertTrue(extract(*judge_block(v, jv.f_v5(v)))[1])

    def test_m_line_format(self):
        for m_line in ("M:M2|conf:0.9", "M:M9|conf:0.90", "M:M2", "M: M2|conf:0.90", "M:none|conf:0.90"):
            b = list(BLOCK)
            b[2] = m_line
            with self.subTest(m_line=m_line):
                self.assertInvalid(b)

    def test_r_line_length(self):
        self.assertTrue(extract(*judge_block(GOOD_V, GOOD_MODE, reason="r" * 120))[1])
        self.assertInvalid(judge_block(GOOD_V, GOOD_MODE, reason="r" * 121))
        self.assertInvalid(judge_block(GOOD_V, GOOD_MODE, reason=""))

    def test_abstain_rule(self):
        v = dict(GOOD_V, cer=0.20)
        self.assertEqual(jv.f_v5(v), "M5")
        self.assertInvalid(judge_block(v, "M2"))
        self.assertTrue(extract(*judge_block(v, "M5"))[1])


class AbstainExceptionTests(unittest.TestCase):
    """SPEC-v5.0-PRE §4 T:abstain_rule as amended by the upstream erratum of 2026-09-14 (v5:506): under
    the epistemic gate (cer < 0.30 or evd < 0.25) parse_judge_block admits M5, and also M8 when a STEP-1
    survival gate fires, where M8 is the f_v5 mode (§3 conflict total order SURVIVAL > EPISTEMIC). Every
    other mode is still rejected. Before the erratum the f_v5 answer for such a vector was never
    schema-valid; a re-pin that brings that back fails this test, validate_cases J9 and the judge tests
    in test_mock_oracle.py."""

    def test_f_v5_answer_is_schema_valid_under_survival_and_epistemic_gate(self):
        for v in (dict(GOOD_V, sov=0.10, cer=0.20), dict(GOOD_V, ext=0.05, evd=0.10),
                  dict(GOOD_V, csq=0.05, rev=0.10, cer=0.20)):
            with self.subTest(v=v):
                self.assertEqual(jv.f_v5(v), "M8")
                self.assertTrue(extract(*judge_block(v, "M8"))[1])
                self.assertTrue(extract(*judge_block(v, "M5"))[1])
                for m in ("M1", "M2", "M3", "M4", "M6", "M7"):
                    self.assertFalse(extract(*judge_block(v, m))[1], m)

    def test_m8_without_a_survival_hit_is_still_rejected_under_the_epistemic_gate(self):
        v = dict(GOOD_V, csq=0.05, cer=0.20)
        self.assertEqual(jv.f_v5(v), "M5")
        self.assertFalse(extract(*judge_block(v, "M8"))[1])


class PaddingAndEvalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = [{"id": "judge-0001", "gold_v": GOOD_V, "boundary": False},
                     {"id": "judge-0002", "gold_v": GOOD_V, "boundary": True},
                     {"id": "judge-0003", "gold_v": GOOD_V, "boundary": False}]
        recs = {"judge-0001": {"status": "ok", "text": "\n".join(BLOCK)},
                "judge-0002": {"status": "ok", "text": "no block here"},
                "judge-0003": {"status": "error", "text": None}}
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "judge").mkdir()
            cls.result = score.score_judge(cls.cases, recs, td)
            cls.eval_bytes = (Path(td) / "judge" / "eval.jsonl").read_bytes()

    def test_eval_rows_are_canonical_and_padded(self):
        text = self.eval_bytes.decode("utf-8")
        rows = [json.loads(x) for x in text.splitlines()]
        self.assertEqual(text, "".join(support.canon(r) for r in rows))
        pad = {d: 0.5 for d in support.DIMS}
        self.assertEqual(rows[0], {"block_count": 1, "boundary": False, "gold_v": GOOD_V, "id": "judge-0001",
                                   "pred_mode": GOOD_MODE, "pred_v": GOOD_V, "schema_valid": True})
        self.assertEqual(rows[1], {"block_count": 0, "boundary": True, "gold_v": GOOD_V, "id": "judge-0002",
                                   "pred_mode": "none", "pred_v": pad, "schema_valid": False})
        self.assertEqual(rows[2], {"block_count": 0, "boundary": False, "gold_v": GOOD_V, "id": "judge-0003",
                                   "pred_mode": "none", "pred_v": pad, "schema_valid": False})

    def test_case_rows(self):
        self.assertEqual([(c["status"], c["schema_valid"], c["pred_mode"], c["gold_mode"], c["mode_hit"])
                          for c in self.result["cases"]],
                         [("ok", True, GOOD_MODE, GOOD_MODE, True), ("ok", False, "none", GOOD_MODE, False),
                          ("error", False, "none", GOOD_MODE, False)])
        self.assertEqual((self.result["n"], self.result["error_count"], self.result["multi_block_count"]), (3, 1, 0))

    def test_metrics_match_an_independent_recomputation_of_the_eval_formula(self):
        row_mae = sum(abs(0.5 - GOOD_V[d]) for d in support.DIMS) / len(support.DIMS)
        schema_rate, mode_acc, mae, boundary_acc = 1 / 3, 1 / 3, 2 * row_mae / 3, 0.0
        vector_score = max(0.0, 1 - mae / 0.25)
        jcs = 0.20 * schema_rate + 0.40 * mode_acc + 0.20 * vector_score + 0.20 * boundary_acc
        for key, want in (("schema_rate", schema_rate), ("mode_acc", mode_acc), ("mae", mae),
                          ("vector_score", vector_score), ("boundary_acc", boundary_acc), ("jcs", jcs)):
            with self.subTest(metric=key):
                self.assertAlmostEqual(self.result[key], want, delta=6e-5)
        self.assertEqual(self.result["boundary_n"], 1)


if __name__ == "__main__":
    unittest.main()
