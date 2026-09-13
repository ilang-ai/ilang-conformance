# -*- coding: utf-8 -*-
"""The run.py mock adapter as an oracle on the real corpus (book §6 R:mock_full_run, §5.4 determinism).

Grammar: the mock reply (the gold file in one ilang fence) passes the scorer for every case.
Judge: the mock reply is the gold vector with the f_v5 mode, except where the vendored parser's
abstain rule rejects that mode: at the pinned commit f_v5 returns M8 at STEP-1 for six sampled
vectors with cer < 0.30 or evd < 0.25 (see AbstainConflictTests in test_judge_extraction.py and
validate_cases.ABSTAIN_CONFLICT_IDS), and there the mock answers M5, the only schema-valid answer.
So the mock judge schema_rate is 1.0 and mode_acc is the admissible share.
Exec: the mock reply is checker_exec.compliant_response(case) and passes the checker."""

import json
import tempfile
import unittest
from pathlib import Path

import support
from support import runner, score

import validate_cases

REAL = support.REAL_CASES
jv = score.vendor_module("ilang_judge_validator")


def abstain_conflict(v):
    """SPEC-v5.0-PRE §4 T:abstain_rule (cer<0.30 or evd<0.25 requires M5) against the f_v5 mode."""
    return (v["cer"] < 0.30 or v["evd"] < 0.25) and jv.f_v5(v) != "M5"


def has_track(cases_dir, track):
    d = Path(cases_dir) / track
    return d.is_dir() and any(p.name.endswith(".jsonl") for p in d.iterdir())


@unittest.skipUnless(has_track(REAL, "grammar"), "no grammar corpus")
class GrammarOracleTests(unittest.TestCase):
    def test_every_grammar_case_passes_the_scorer(self):
        cases = support.load_cases(REAL, "grammar")
        recs = {c["id"]: {"status": "ok", "text": runner.mock_reply(c, REAL)} for c in cases}
        with tempfile.TemporaryDirectory() as work:
            result = score.score_grammar(cases, recs, work)
        self.assertEqual([r["id"] for r in result["cases"] if not r["pass"]], [])
        for r in result["cases"]:
            with self.subTest(id=r["id"]):
                self.assertEqual((r["payload_source"], r["header_prepended"], r["lint_errors"]), ("fence", False, 0))

    def test_mock_reply_is_deterministic(self):
        for c in support.load_cases(REAL, "grammar")[:10]:
            self.assertEqual(runner.mock_reply(c, REAL), runner.mock_reply(c, REAL))


@unittest.skipUnless(has_track(REAL, "judge"), "no judge corpus")
class JudgeOracleTests(unittest.TestCase):
    def test_mock_block_is_always_valid_and_answers_m5_only_under_the_abstain_conflict(self):
        for c in support.load_cases(REAL, "judge"):
            v = c["gold_v"]
            block_count, valid, vec, mode = score.judge_extract(jv, runner.mock_reply(c, REAL))
            with self.subTest(id=c["id"]):
                self.assertEqual((block_count, valid), (1, True))
                self.assertEqual(vec, {d: float("%.2f" % v[d]) for d in support.DIMS})
                self.assertEqual(mode, "M5" if abstain_conflict(v) else jv.f_v5(v))

    def test_abstain_conflicts_are_the_pinned_ids(self):
        conflicts = sorted(c["id"] for c in support.load_cases(REAL, "judge") if abstain_conflict(c["gold_v"]))
        self.assertEqual(conflicts, validate_cases.ABSTAIN_CONFLICT_IDS)

    def test_hand_written_scenarios_have_no_abstain_conflict(self):
        bad = [c["id"] for c in support.load_cases(REAL, "judge")
               if c["kind"] == "scenario_to_vector" and abstain_conflict(c["gold_v"])]
        self.assertEqual(bad, [])


class ExecOracleTests(unittest.TestCase):
    def check_all(self, cases_dir):
        ce = score.vendor_module("checker_exec")
        for c in support.load_cases(cases_dir, "exec"):
            with self.subTest(id=c["id"]):
                self.assertEqual(ce.check(c, runner.mock_reply(c, cases_dir))["outcome"], "pass")

    def test_fixture_exec_cases_pass_the_checker(self):
        self.check_all(support.RUNNER_CASES)

    @unittest.skipUnless(has_track(REAL, "exec"), "no exec corpus yet")
    def test_real_exec_cases_pass_the_checker(self):
        self.check_all(REAL)


@unittest.skipUnless(has_track(REAL, "grammar") and has_track(REAL, "judge"), "grammar or judge corpus missing")
class RealCorpusEndToEndTests(unittest.TestCase):
    """Two mock runs (grammar then judge into one run directory), each scored twice."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        td = Path(cls._tmp.name)
        cls.logs, cls.scores = [], {}
        for k, extra in ((1, []), (2, ["--concurrency", "4"])):
            run = td / "runs" / ("mock-20260101-00000%d" % k)
            for track in ("grammar", "judge"):
                cls.logs.append(support.run_main(["--vendor", "mock", "--track", track, "--cases-dir", REAL,
                                                  "--run-dir", run] + extra))
            for j in (1, 2):
                report = td / ("report-%d-%d" % (k, j))
                code, out, err = support.score_cli([run, "--vendor", "mock", "--cases", REAL, "--report", report])
                cls.scores[(k, j)] = (code, err, (report / run.name / "score.json").read_bytes() if code == 0 else b"")

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def doc(self):
        code, err, data = self.scores[(1, 1)]
        self.assertEqual(code, 0, err)
        return json.loads(data)

    def test_runs_complete(self):
        self.assertEqual([c for c, _ in self.logs], [0, 0, 0, 0], [log[-400:] for _, log in self.logs])

    def test_four_score_json_files_are_byte_identical(self):
        for key, (code, err, _) in self.scores.items():
            self.assertEqual(code, 0, err)
        self.assertEqual(len({data for _, _, data in self.scores.values()}), 1)

    def test_grammar_track_scores_one(self):
        g = self.doc()["tracks"]["grammar"]
        self.assertEqual((g["n"], g["pass_count"], g["pass_rate"], g["error_count"]),
                         (len(support.load_cases(REAL, "grammar")), g["n"], 1.0, 0))

    def test_judge_track_schema_is_one_and_mode_accuracy_is_the_admissible_share(self):
        cases = support.load_cases(REAL, "judge")
        conflicts = sorted(c["id"] for c in cases if abstain_conflict(c["gold_v"]))
        doc = self.doc()
        j = doc["tracks"]["judge"]
        share = round((len(cases) - len(conflicts)) / len(cases), 4)
        self.assertEqual([c["id"] for c in j["cases"] if not c["schema_valid"]], [])
        self.assertEqual(sorted(c["id"] for c in j["cases"] if not c["mode_hit"]), conflicts)
        self.assertEqual((j["n"], j["schema_rate"], j["mode_acc"], j["mae"], j["vector_score"], j["boundary_acc"],
                          j["error_count"], j["multi_block_count"]), (len(cases), 1.0, share, 0.0, 1.0, 1.0, 0, 0))
        self.assertAlmostEqual(j["jcs"], 0.20 + 0.40 * share + 0.20 + 0.20, delta=6e-5)
        self.assertEqual(doc["summary"]["judge_schema"], 1.0)


if __name__ == "__main__":
    unittest.main()
