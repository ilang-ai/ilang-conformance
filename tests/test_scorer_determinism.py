# -*- coding: utf-8 -*-
"""Scorer determinism on the fixture corpus (book §5.4 RULE determinism_scope, score_json_canonical;
cases/SCHEMA.md §8.4, §8.9, §8.10): two mock runs, each scored twice, plus a copy scored from another
path and working directory, give byte-identical canonical score.json; refusals leave report/ untouched."""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

import support
from support import score

CASES = support.RUNNER_CASES


class ScorerDeterminismTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.td = Path(cls._tmp.name)
        cls.run_a = cls.td / "runs" / "mock-20260101-000001"
        cls.run_b = cls.td / "runs" / "mock-20260101-000002"
        cls.run_codes = [support.run_main(["--vendor", "mock", "--cases-dir", CASES, "--run-dir", cls.run_a])[0],
                         support.run_main(["--vendor", "mock", "--cases-dir", CASES, "--run-dir", cls.run_b,
                                           "--concurrency", "3"])[0]]
        cls.scores = {}
        for run in (cls.run_a, cls.run_b):
            for k in (1, 2):
                report = cls.td / ("report-%s-%d" % (run.name, k))
                code, out, err = support.score_cli([run, "--vendor", "mock", "--cases", CASES, "--report", report])
                data = (report / run.name / "score.json").read_bytes() if code == 0 else None
                cls.scores["%s/%d" % (run.name, k)] = (code, err, data, report)
        cls.copy = cls.td / "elsewhere" / "nested" / cls.run_a.name
        shutil.copytree(cls.run_a, cls.copy)
        report = cls.td / "report-copy"
        code, out, err = support.score_cli([cls.copy, "--cases", CASES, "--report", report], cwd=cls.td / "elsewhere")
        cls.scores["copy"] = (code, err, (report / cls.copy.name / "score.json").read_bytes() if code == 0 else None,
                              report)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def score_bytes(self, key="mock-20260101-000001/1"):
        code, err, data, _ = self.scores[key]
        self.assertEqual(code, 0, err)
        return data

    def test_runs_complete(self):
        self.assertEqual(self.run_codes, [0, 0])

    def test_two_mock_runs_are_byte_identical(self):
        self.assertEqual(support.tree(self.run_a), support.tree(self.run_b))

    def test_every_scoring_gives_identical_score_json(self):
        for key in self.scores:
            self.score_bytes(key)
        blobs = {key: v[2] for key, v in self.scores.items()}
        self.assertEqual(len(set(blobs.values())), 1, {k: support.sha256(v or b"") for k, v in blobs.items()})

    def test_score_json_is_canonical(self):
        data = self.score_bytes()
        self.assertEqual(data, support.canon(json.loads(data.decode("utf-8"))).encode("utf-8"))
        self.assertTrue(data.endswith(b"}\n"))

    def test_score_json_has_no_run_name_path_or_timestamp(self):
        text = self.score_bytes().decode("utf-8")
        for needle in ("mock-2026", "20260101", str(self.td), self.td.as_posix(), "eval.jsonl", ".ilang",
                       "runs/", "report"):
            with self.subTest(needle=needle):
                self.assertNotIn(needle, text)

    def test_floats_are_rounded_to_four_places(self):
        for x in support.floats_in(json.loads(self.score_bytes())):
            self.assertEqual(x, round(x, 4))

    def test_perfect_fixture_answers_reach_l1(self):
        s = json.loads(self.score_bytes())["summary"]
        self.assertEqual((s["grammar_pass_rate"], s["exec_pass_rate"], s["judge_jcs"], s["judge_schema"],
                          s["weighted_total"], s["weighted_pass"], s["l1"], s["error_count"], s["degraded_count"]),
                         (1.0, 1.0, 1.0, 1.0, 1.0, True, "L1", 0, 0))

    def test_eval_jsonl_identical_across_runs(self):
        self.assertEqual((self.run_a / "judge" / "eval.jsonl").read_bytes(),
                         (self.run_b / "judge" / "eval.jsonl").read_bytes())

    def test_report_outputs(self):
        _, _, _, report = self.scores["mock-20260101-000001/1"]
        self.assertEqual((report / self.run_a.name / "MANIFEST.sha256").read_bytes(),
                         (self.run_a / "MANIFEST.sha256").read_bytes())
        board = (report / "SCOREBOARD.md").read_bytes().decode("utf-8")
        lines = board.split("\n")
        self.assertEqual(lines[0], "# ilang-conformance scoreboard")
        self.assertEqual(lines[1], "")
        self.assertTrue(board.endswith("\n") and not board.endswith("\n\n"))
        row = [x for x in lines if x.startswith("| mock |")]
        self.assertEqual(len(row), 1)
        self.assertIn("| 2026-01-01 |", row[0])
        self.assertIn("| L1 |", row[0])
        self.assertIn("| %s |" % self.run_a.name, row[0])


class RefusalTests(unittest.TestCase):
    """SCHEMA §8.9: a refused scoring exits non-zero and writes nothing to the report directory."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.td = Path(cls._tmp.name)
        cls.base = cls.td / "base" / "mock-20260101-000001"
        code, log = support.run_main(["--vendor", "mock", "--cases-dir", CASES, "--run-dir", cls.base])
        assert code == 0, log

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def variant(self, name):
        run = self.td / name / self.base.name
        shutil.copytree(self.base, run)
        return run

    def refused(self, run, code_expected):
        report = run.parent / "report"
        code, out, err = support.score_cli([run, "--cases", CASES, "--report", report])
        self.assertEqual(code, code_expected, err)
        self.assertFalse(report.exists())
        return err

    def test_unfinished_run_exits_3_and_names_run_log(self):
        run = self.variant("undone")
        (run / "DONE").unlink()
        self.assertIn("run.log", self.refused(run, 3))

    def test_tampered_record(self):
        run = self.variant("tampered")
        p = run / "grammar" / "grammar-0001.json"
        p.write_bytes(p.read_bytes().replace(b'"status":"ok"', b'"status":"ok" '))
        self.assertIn("MANIFEST.sha256", self.refused(run, 1))

    def test_unlisted_record(self):
        run = self.variant("unlisted")
        shutil.copy(run / "grammar" / "grammar-0001.json", run / "grammar" / "grammar-0099.json")
        self.assertIn("not listed", self.refused(run, 1))

    def test_done_not_bound_to_manifest(self):
        run = self.variant("rebound")
        (run / "DONE").write_bytes(b"0" * 64 + b"\n")
        self.refused(run, 1)

    def test_missing_corpus_record(self):
        run = self.variant("missing")
        manifest = (run / "MANIFEST.sha256").read_bytes().decode("ascii").splitlines()
        kept = [x for x in manifest if not x.endswith("judge/judge-0002.json")]
        (run / "judge" / "judge-0002.json").unlink()
        data = "".join(x + "\n" for x in kept).encode("ascii")
        (run / "MANIFEST.sha256").write_bytes(data)
        (run / "DONE").write_bytes((support.sha256(data) + "\n").encode("ascii"))
        self.assertIn("judge-0002", self.refused(run, 1))


if __name__ == "__main__":
    unittest.main()
