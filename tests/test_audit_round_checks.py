# -*- coding: utf-8 -*-
"""Checks added after the audit of 2026-11-26 (release 2.2.2): validate_cases.py X10 (the runtime ::BUDGET quoted
in an exec prompt states the case's budget object) and J10 (a boundary_note re-derives with f_v5), and the stderr
warning of score.py when the records of a run were sent another system message than the one this checkout builds.
Mutations are made on copies of real cases in memory; scorer runs work on copies in a temporary directory, so
nothing is written into the repository."""

import copy
import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path

import support
from support import runner, score

import validate_cases

REAL = support.REAL_CASES
SCORER = support.FIXTURES / "scorer"
SCORE_KEYS = ["format", "model", "spec_pin", "summary", "tracks", "vendor"]


def by_id(track):
    return {c["id"]: c for c in support.load_cases(REAL, track)}


class BudgetQuoteTests(unittest.TestCase):
    """X10, SCHEMA §1.6."""

    @classmethod
    def setUpClass(cls):
        cls.cases = by_id("exec")

    def test_real_corpus_states_every_runtime_budget_as_its_budget_object(self):
        quoted = []
        for cid, case in sorted(self.cases.items()):
            if "budget" not in case:
                continue
            with self.subTest(id=cid):
                self.assertEqual(validate_cases.budget_quote_problems(case), [])
            if any("authority:@RUNTIME" in m.group(1) for m in validate_cases.BUDGET_QUOTE.finditer(case["prompt"])):
                quoted.append(cid)
        self.assertEqual(len(quoted), 24, quoted)

    def test_a_budget_object_that_disagrees_with_its_prompt_fails(self):
        for key, value, word in (("used", 4, "used"), ("kind", "tokens", "kind"), ("reserve_audit", 2, "reserve_audit"),
                                 ("limit", 11, "limit")):
            case = copy.deepcopy(self.cases["exec-0089"])
            case["budget"][key] = value
            with self.subTest(key=key):
                problems = validate_cases.budget_quote_problems(case)
                self.assertEqual(len(problems), 1, problems)
                self.assertIn(word, problems[0])

    def test_a_reserve_the_prompt_leaves_out_counts_as_zero(self):
        case = copy.deepcopy(self.cases["exec-0085"])            # rounds, limit 6, used 2, no reserves
        self.assertEqual(validate_cases.budget_quote_problems(case), [])
        case["budget"]["reserve_summary"] = 1
        self.assertIn("reserve_summary", " ".join(validate_cases.budget_quote_problems(case)))

    def test_quotes_without_runtime_authority_are_not_compared(self):
        case = copy.deepcopy(self.cases["exec-0081"])            # also quotes a template with remaining:4,800
        self.assertEqual(validate_cases.budget_quote_problems(case), [])
        case["prompt"] += " Template: ::BUDGET{id:b9|kind:time|limit:1|used:0|authority:@SELF}."
        self.assertEqual(validate_cases.budget_quote_problems(case), [])

    def test_a_case_without_a_string_prompt_is_left_to_c6(self):
        case = copy.deepcopy(self.cases["exec-0089"])
        del case["prompt"]
        self.assertEqual(validate_cases.budget_quote_problems(case), [])
        case["prompt"] = 5
        self.assertEqual(validate_cases.budget_quote_problems(case), [])

    def test_x10_and_j10_have_a_place_in_the_output_order(self):
        for check in ("X10", "J10"):
            self.assertIn(check, validate_cases.CHECK_ORDER)


class BoundaryNoteTests(unittest.TestCase):
    """J10, SCHEMA §1.6."""

    @classmethod
    def setUpClass(cls):
        cls.jv = score.vendor_module("ilang_judge_validator")
        cls.cases = by_id("judge")

    def test_every_real_boundary_note_parses_and_re_derives(self):
        notes = [c for c in self.cases.values() if "boundary_note" in c]
        self.assertEqual(len(notes), 20)
        for case in notes:
            with self.subTest(id=case["id"]):
                self.assertTrue(validate_cases.BOUNDARY_NOTE.match(case["boundary_note"]))
                self.assertEqual(validate_cases.boundary_note_problems(self.jv, case["gold_v"], case["boundary_note"]), [])

    def test_a_gold_value_the_note_does_not_describe_fails(self):
        case = self.cases["judge-0061"]                          # sov 0.15 -> 0.10 flips M3 to M8
        gold = dict(case["gold_v"], sov=0.60)
        problems = validate_cases.boundary_note_problems(self.jv, gold, case["boundary_note"])
        self.assertTrue(any("before the step" in p for p in problems), problems)

    def test_a_gold_vector_with_another_mode_fails(self):
        case = self.cases["judge-0062"]
        gold = {d: 0.90 for d in support.DIMS}
        self.assertEqual(self.jv.f_v5(gold), "M1")
        problems = validate_cases.boundary_note_problems(self.jv, gold, case["boundary_note"])
        self.assertTrue(any("f_v5 returns M1" in p for p in problems), problems)

    def test_a_note_that_does_not_parse_fails_closed(self):
        case = self.cases["judge-0063"]
        for note in ("Critical dimension ext.", case["boundary_note"].replace("perturbing", "moving"),
                     case["boundary_note"].replace("-0.05", "-0.10")):
            with self.subTest(note=note[:60]):
                problems = validate_cases.boundary_note_problems(self.jv, case["gold_v"], note)
                self.assertEqual(len(problems), 1)
                self.assertIn("does not parse", problems[0])


class CanonWarningTests(unittest.TestCase):
    """score.py, SCHEMA §8.3: a warning on stderr, never a refusal and never a field of score.json."""

    def checkout_sha(self, track):
        return hashlib.sha256(runner.system_message(track).encode("utf-8")).hexdigest()

    def test_records_sent_this_checkouts_system_message_give_no_warning(self):
        records = {"%s/%s-0001.json" % (t, t): {"system_sha256": self.checkout_sha(t)} for t in ("grammar", "exec", "judge")}
        self.assertEqual(score.canon_warnings("mock-20260101-000001", records, ["grammar", "exec", "judge"]), [])

    def test_one_line_per_track_whose_records_were_sent_another_system_message(self):
        records = {"exec/exec-0001.json": {"system_sha256": "ab" * 32},
                   "exec/exec-0002.json": {"system_sha256": self.checkout_sha("exec")},
                   "judge/judge-0001.json": {"system_sha256": None},
                   "grammar/grammar-0001.json": {"system_sha256": self.checkout_sha("grammar")}}
        lines = score.canon_warnings("x-20260101-000001", records, ["grammar", "exec", "judge"])
        self.assertEqual(len(lines), 2, lines)
        self.assertTrue(lines[0].startswith("score.py: warning: x-20260101-000001: exec: 1 of 2 records "), lines[0])
        self.assertIn("sha256 abababababababab", lines[0])
        self.assertTrue(lines[1].startswith("score.py: warning: x-20260101-000001: judge: 1 of 1 records "), lines[1])
        self.assertIn("sha256 none", lines[1])

    def test_an_older_run_is_scored_with_a_warning_and_score_json_keeps_its_keys(self):
        expect = json.loads((SCORER / "perfect" / "expect.json").read_bytes().decode("utf-8"))
        with tempfile.TemporaryDirectory() as td:
            runs, report = Path(td) / "runs", Path(td) / "report"
            shutil.copytree(SCORER / "perfect", runs, ignore=shutil.ignore_patterns("expect.json"))
            code, out, err = support.score_cli([runs / expect["run"], "--cases", SCORER / "cases", "--report", report])
            self.assertEqual(code, 0, err)
            warned = sorted(ln.split(": ")[3] for ln in err.splitlines() if ln.startswith("score.py: warning: "))
            obj = json.loads((report / expect["run"] / "score.json").read_bytes().decode("utf-8"))
        self.assertEqual(warned, sorted(obj["tracks"]))
        self.assertEqual(sorted(obj), SCORE_KEYS)
        self.assertTrue(out.startswith("scored %s: " % expect["run"]), out)

    def test_a_mock_run_made_at_this_checkout_scores_without_a_warning(self):
        with tempfile.TemporaryDirectory() as td:
            run = Path(td) / "runs" / "mock-20260101-000001"
            code, log = support.run_main(["--vendor", "mock", "--track", "all", "--cases-dir", support.RUNNER_CASES,
                                          "--run-dir", run])
            self.assertEqual(code, 0, log[-400:])
            code, out, err = support.score_cli([run, "--vendor", "mock", "--cases", support.RUNNER_CASES,
                                                "--report", Path(td) / "report"])
        self.assertEqual(code, 0, err)
        self.assertNotIn("warning", err)


if __name__ == "__main__":
    unittest.main()
