# -*- coding: utf-8 -*-
"""The run.py mock adapter as an oracle on the real corpus (book §6 R:mock_full_run, §5.4 determinism).

Grammar: the mock reply (the gold file in one ilang fence) passes the scorer for every case.
Judge: the mock reply is the gold vector with the f_v5 mode. Since the upstream abstain-rule erratum
of 2026-09-14 (SPEC-v5.0-PRE v5:506) the vendored parser admits that mode for every vector, including
M8 on a STEP-1 survival hit under the epistemic gate (AbstainExceptionTests in
test_judge_extraction.py, validate_cases.ABSTAIN_EXCEPTION_IDS), so the mock judge schema_rate,
mode_acc and JCS are 1.0.
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


def survival_under_epistemic_gate(v):
    """A STEP-1 survival gate (sov<0.15, ext<0.10, or csq<0.10 with rev<0.20; v5:461-464) fires together
    with the epistemic gate (cer<0.30 or evd<0.25; v5:466-467). The thresholds are literals from the
    spec, independent of the vendored TH table."""
    survival = v["sov"] < 0.15 or v["ext"] < 0.10 or (v["csq"] < 0.10 and v["rev"] < 0.20)
    return survival and (v["cer"] < 0.30 or v["evd"] < 0.25)


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
    def test_mock_block_is_always_valid_and_answers_the_f_v5_mode(self):
        for c in support.load_cases(REAL, "judge"):
            v = c["gold_v"]
            block_count, valid, vec, mode = score.judge_extract(jv, runner.mock_reply(c, REAL))
            with self.subTest(id=c["id"]):
                self.assertEqual((block_count, valid), (1, True))
                self.assertEqual(vec, {d: float("%.2f" % v[d]) for d in support.DIMS})
                self.assertEqual(mode, jv.f_v5(v))

    def test_survival_under_epistemic_gate_ids_are_the_pinned_ids(self):
        cases = support.load_cases(REAL, "judge")
        got = sorted(c["id"] for c in cases if survival_under_epistemic_gate(c["gold_v"]))
        self.assertEqual(got, validate_cases.ABSTAIN_EXCEPTION_IDS)
        self.assertEqual({jv.f_v5(c["gold_v"]) for c in cases if c["id"] in got}, {"M8"})


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

    def test_judge_track_scores_one(self):
        cases = support.load_cases(REAL, "judge")
        doc = self.doc()
        j = doc["tracks"]["judge"]
        self.assertEqual([c["id"] for c in j["cases"] if not (c["schema_valid"] and c["mode_hit"])], [])
        self.assertEqual((j["n"], j["schema_rate"], j["mode_acc"], j["mae"], j["vector_score"], j["boundary_acc"],
                          j["error_count"], j["multi_block_count"]), (len(cases), 1.0, 1.0, 0.0, 1.0, 1.0, 0, 0))
        self.assertAlmostEqual(j["jcs"], 1.0, delta=6e-5)
        self.assertEqual(doc["summary"]["judge_schema"], 1.0)


if __name__ == "__main__":
    unittest.main()
