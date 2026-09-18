# -*- coding: utf-8 -*-
"""Checks added in the review round that are proposed for cases/SCHEMA.md but not yet in it:
validate_cases.py G12 (delimited must_contain strings) and J9 (abstain-rule pin under the upstream
erratum of 2026-09-14), score.py --latest refusal while a newer run is unfinished (book §8 third
command), and lint temp files inside the run directory (book §8 RULE u24_is_shared)."""

import json
import shutil
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

import support
from support import score

import validate_cases

REAL = support.REAL_CASES
SCORER = support.FIXTURES / "scorer"


class UndelimitedAssertionTests(unittest.TestCase):
    def test_operation_heads(self):
        for s in ("[FILT", "[φ", "=>[READ"):
            with self.subTest(s=s):
                self.assertTrue(validate_cases.UNDELIMITED_HEAD.search(s))
        for s in ("[FILT:", "[FILT|", "[FILT]", "=>[", "::FACT{", "[COPY:@DRIVE", "[Δ]"):
            with self.subTest(s=s):
                self.assertIsNone(validate_cases.UNDELIMITED_HEAD.search(s))

    def test_modifier_values(self):
        for s in ("lng=ja", "top=12", "fmt=json", "dst=@DRIVE", "rng=120:180"):
            with self.subTest(s=s):
                self.assertTrue(validate_cases.UNDELIMITED_VALUE.search(s))
        for s in ("lng=ja,", "lng=ja]", "lng=ja|", "grp=", "rng=2026-09-14:", "conf:confirmed", "limit:200000", "=>["):
            with self.subTest(s=s):
                self.assertIsNone(validate_cases.UNDELIMITED_VALUE.search(s))

    def test_prefix_strings_admit_wrong_answers_that_delimited_groups_reject(self):
        for prefix, wrong, right in (("[FILT", "[FILTER:@LOCAL|fmt=md]", "[FILT:@LOCAL|fmt=md]"),
                                     ("lng=ja", "[XLAT|lng=japanese]", "[XLAT|lng=ja]"),
                                     ("top=12", "[SORT|top=120]", "[SORT|top=12]")):
            with self.subTest(prefix=prefix):
                group = [prefix + d for d in ((":", "|", "]") if prefix.startswith("[") else (",", "]", "|"))]
                expect = {"must_contain": [group], "must_not_contain": []}
                self.assertIn(prefix, wrong)
                self.assertEqual(score.grammar_assertions(expect, wrong), ([0], []))
                self.assertEqual(score.grammar_assertions(expect, right), ([], []))

    def test_real_grammar_corpus_has_no_undelimited_must_contain_string(self):
        bad = []
        for case in support.load_cases(REAL, "grammar"):
            for element in case["expect"]["must_contain"]:
                for s in (element if isinstance(element, list) else [element]):
                    if validate_cases.UNDELIMITED_HEAD.search(s) or validate_cases.UNDELIMITED_VALUE.search(s):
                        bad.append((case["id"], s))
        self.assertEqual(bad, [])


class AbstainExceptionPinTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.jv = score.vendor_module("ilang_judge_validator")
        cls.pairs = [(c["id"], c["gold_v"]) for c in support.load_cases(REAL, "judge")]

    def test_pin_matches_the_vendored_parser(self):
        self.assertEqual(validate_cases.abstain_pin_problems(self.jv, self.pairs), [])
        got = sorted(cid for cid, v in self.pairs if validate_cases.judge_admitted_modes(self.jv, v) == {"M5", "M8"})
        self.assertEqual(got, validate_cases.ABSTAIN_EXCEPTION_IDS)
        by_id = dict(self.pairs)
        for cid in got:
            with self.subTest(id=cid):
                self.assertEqual(self.jv.f_v5(by_id[cid]), "M8")

    def test_a_parser_without_the_erratum_fails_j9(self):
        real = self.jv

        def pre_erratum_parse(lines):
            vec, mode, conf, reason = real.parse_judge_block(lines)
            if (vec["cer"] < 0.30 or vec["evd"] < 0.25) and mode != "M5":
                raise ValueError("abstain rule violated: epistemic gate requires M5")
            return vec, mode, conf, reason

        old = types.SimpleNamespace(f_v5=real.f_v5, parse_judge_block=pre_erratum_parse)
        pinned = ", ".join(validate_cases.ABSTAIN_EXCEPTION_IDS)
        self.assertEqual(validate_cases.abstain_pin_problems(old, self.pairs),
                         ["ids whose f_v5 answer parse_judge_block rejects: %s; required none" % pinned,
                          "ids where parse_judge_block admits exactly M5 and M8: none; pinned %s" % pinned])


class LatestSelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.td = Path(cls._tmp.name)
        cls.runs = cls.td / "runs"
        shutil.copytree(SCORER / "latest", cls.runs, ignore=shutil.ignore_patterns("expect.json"))
        cls.expect = json.loads((SCORER / "latest" / "expect.json").read_bytes())

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def score_latest(self, vendor, report):
        return support.score_cli(["--latest", "--vendor", vendor, "--runs", self.runs, "--cases", SCORER / "cases",
                                  "--report", report])

    def test_newer_unfinished_run_refuses_latest_and_names_its_log(self):
        report = self.td / "report-mock"
        code, out, err = self.score_latest("mock", report)
        self.assertEqual(code, self.expect["exit"]["mock"], err)
        self.assertIn(self.expect["stderr_contains"]["mock"], err)
        self.assertFalse(report.exists())

    def test_finished_run_can_still_be_scored_by_path(self):
        report = self.td / "report-by-path"
        code, out, err = support.score_cli([self.runs / "mock-20260913-100000", "--cases", SCORER / "cases",
                                            "--report", report])
        self.assertEqual(code, 0, err)

    def test_other_vendor_is_selected_and_scored(self):
        report = self.td / "report-other"
        code, out, err = self.score_latest("other", report)
        self.assertEqual(code, self.expect["exit"]["other"], err)
        self.assertTrue((report / self.expect["select"]["other"] / "score.json").is_file())


class LintWorkDirTests(unittest.TestCase):
    def test_lint_files_live_under_the_work_dir_and_are_removed(self):
        seen, real_run = [], score.subprocess.run

        def spy(argv, **kwargs):
            seen.extend(str(a) for a in argv if str(a).endswith(".ilang"))
            return real_run(argv, **kwargs)

        expect = {"lint_errors": 0, "must_contain": [["[READ:", "[READ|"]], "must_not_contain": []}
        with tempfile.TemporaryDirectory() as work, mock.patch.object(score.subprocess, "run", spy):
            result = score.score_grammar([{"id": "grammar-0001", "expect": expect}],
                                         {"grammar-0001": {"status": "ok", "text": "[READ:@SRC]"}}, work)
            root = Path(work).resolve()
            self.assertEqual(result["pass_count"], 1)
            self.assertEqual(len(seen), 1)
            self.assertEqual(Path(seen[0]).resolve().parent.parent, root)
            self.assertEqual(list(root.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
