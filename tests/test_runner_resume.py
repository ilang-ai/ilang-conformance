# -*- coding: utf-8 -*-
"""run.py resume, retry and completion signalling (book §5.5; cases/SCHEMA.md §8.5-§8.8), offline:
the mock adapter and an in-process scripted transport, never a socket."""

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import support
from support import ScriptedTransport, openai_body, runner

CASES = support.RUNNER_CASES
SECRET = "sk-test-SECRET-5d1e"


def manifest_lines(run):
    return (Path(run) / "MANIFEST.sha256").read_bytes().decode("ascii").splitlines()


class MockResumeTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.td = Path(self._tmp.name)
        self.run = self.td / "runs" / "mock-20260101-000001"

    def tearDown(self):
        self._tmp.cleanup()

    def go(self, *extra):
        return support.run_main(["--vendor", "mock", "--cases-dir", CASES, "--run-dir", self.run] + list(extra))

    def assertDoneBoundToManifest(self):
        data = (self.run / "MANIFEST.sha256").read_bytes()
        self.assertEqual((self.run / "DONE").read_bytes(), (support.sha256(data) + "\n").encode("ascii"))
        for line in data.decode("ascii").splitlines():
            digest, rel = line.split("  ")
            self.assertEqual(support.sha256((self.run / rel).read_bytes()), digest)

    def test_resume_redoes_only_missing_corrupt_non_object_and_error_records(self):
        code, log = self.go()
        self.assertEqual(code, 0, log)
        before = support.tree(self.run)
        self.assertEqual(len(manifest_lines(self.run)), 9)
        (self.run / "grammar" / "grammar-0002.json").unlink()
        (self.run / "exec" / "exec-0001.json").write_bytes(b"{not json")
        (self.run / "judge" / "judge-0001.json").write_bytes(b"[1, 2]\n")
        rec = json.loads(before["judge/judge-0003.json"])
        rec["status"] = "error"
        (self.run / "judge" / "judge-0003.json").write_bytes(json.dumps(rec).encode("ascii"))
        (self.run / "grammar" / ".grammar-0001.json.tmp123-456").write_bytes(b"partial")
        code, log = self.go()
        self.assertEqual(code, 0, log)
        self.assertIn(" skip=5 todo=4 ", log)
        self.assertIn("removed stale DONE", log)
        self.assertIn("removed stale MANIFEST.sha256", log)
        self.assertEqual(support.tree(self.run), before)
        self.assertDoneBoundToManifest()

    def test_interrupted_run_is_refused_by_score_then_resumed(self):
        code, log = self.go()
        self.assertEqual(code, 0, log)
        (self.run / "DONE").unlink()
        (self.run / "MANIFEST.sha256").unlink()
        (self.run / "exec" / "exec-0002.json").unlink()
        code, out, err = support.score_cli([self.run, "--cases", CASES, "--report", self.td / "report"])
        self.assertEqual(code, 3, err)
        self.assertIn("run.log", err)
        code, log = self.go()
        self.assertEqual(code, 0, log)
        self.assertIn(" skip=8 todo=1 ", log)
        self.assertDoneBoundToManifest()
        code, out, err = support.score_cli([self.run, "--cases", CASES, "--report", self.td / "report"])
        self.assertEqual(code, 0, err)

    def test_tracks_run_one_at_a_time_share_one_manifest(self):
        code, log = self.go("--track", "grammar")
        self.assertEqual(code, 0, log)
        self.assertEqual([x.split("  ")[1] for x in manifest_lines(self.run)],
                         ["grammar/grammar-0001.json", "grammar/grammar-0002.json", "grammar/grammar-0003.json"])
        code, log = self.go("--track", "judge")
        self.assertEqual(code, 0, log)
        self.assertIn(" skip=0 todo=3 ", log)
        self.assertEqual([x.split("  ")[1] for x in manifest_lines(self.run)],
                         ["grammar/grammar-0001.json", "grammar/grammar-0002.json", "grammar/grammar-0003.json",
                          "judge/judge-0001.json", "judge/judge-0002.json", "judge/judge-0003.json"])
        self.assertDoneBoundToManifest()
        code, out, err = support.score_cli([self.run, "--cases", CASES, "--report", self.td / "report"])
        self.assertEqual(code, 0, err)
        doc = json.loads((self.td / "report" / self.run.name / "score.json").read_bytes())
        self.assertEqual(sorted(doc["tracks"]), ["grammar", "judge"])
        self.assertIsNone(doc["summary"]["weighted_total"])
        self.assertEqual(doc["summary"]["l1"], "below_L1")

    def test_dry_run_writes_nothing_and_limit_selects_by_id(self):
        code, log = self.go("--dry-run")
        self.assertEqual(code, 0, log)
        self.assertIn(" todo=9 ", log)
        self.assertFalse(self.run.exists())
        code, log = self.go("--track", "exec", "--limit", "2")
        self.assertEqual(code, 0, log)
        self.assertIn("score.py refuses a --limit run", log)
        self.assertEqual(sorted(support.tree(self.run)),
                         ["DONE", "MANIFEST.sha256", "exec/exec-0001.json", "exec/exec-0002.json"])
        code, out, err = support.score_cli([self.run, "--cases", CASES, "--report", self.td / "report"])
        self.assertEqual(code, 1, err)
        self.assertIn("exec-0003 has no listed raw record", err)

    def test_configuration_errors_exit_2_before_any_write(self):
        for argv, needle in (
                (["--vendor", "orcarouter-deepseek-free", "--cases-dir", CASES,
                  "--run-dir", self.td / "runs" / "orcarouter-deepseek-free-20260101-000001"], "ORCA_API_KEY"),
                (["--vendor", "mock", "--cases-dir", CASES, "--run-dir", self.td / "runs" / "other-20260101-000001"],
                 "must be mock-"),
                (["--vendor", "mock", "--cases-dir", self.td / "no-cases", "--run-dir", self.run], "no grammar cases")):
            with self.subTest(needle=needle):
                code, log = support.run_main(argv)
                self.assertEqual(code, 2, log)
                self.assertIn(needle, log)
        self.assertFalse((self.td / "runs").exists())


class ScriptedVendorResumeTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.td = Path(self._tmp.name)
        self.vendors = self.td / "vendors.json"
        self.vendors.write_bytes(json.dumps([
            {"name": "stub", "api": "openai_compatible", "base_url": "https://stub.invalid/v1",
             "model": "stub/model", "auth_env": "STUB_KEY", "max_tokens": 64, "seed": True}]).encode("utf-8"))
        self.run = self.td / "runs" / "stub-20260101-000001"
        self.keys = support.write_env_file(self.td / "keys.env", STUB_KEY=SECRET)

    def tearDown(self):
        self._tmp.cleanup()

    def go(self, transport, cases=CASES):
        return support.run_main(["--vendor", "stub", "--track", "grammar", "--cases-dir", cases, "--run-dir", self.run],
                                vendors_path=self.vendors, env_file=self.keys, transport=transport)

    def test_ok_record_with_a_stale_request_is_requested_again(self):
        code, log = self.go(ScriptedTransport([(200, {}, openai_body("a"))] * 3))
        self.assertEqual(code, 0, log)
        cases = self.td / "cases"
        shutil.copytree(CASES, cases)
        f = cases / "grammar" / "fixture.jsonl"
        f.write_bytes(f.read_bytes().replace(b"translated.md", b"translated-v2.md", 1))
        again = ScriptedTransport([(200, {}, openai_body("b"))])
        code, log = self.go(again, cases)
        self.assertEqual(code, 0, log)
        self.assertIn(" skip=2 todo=1 ", log)
        self.assertEqual(len(again.calls), 1)
        self.assertEqual((self.record("grammar-0002")["text"], self.record("grammar-0001")["text"]), ("b", "a"))
        vendors = json.loads(self.vendors.read_bytes())
        vendors[0]["max_tokens"] = 128
        self.vendors.write_bytes(json.dumps(vendors).encode("utf-8"))
        third = ScriptedTransport([(200, {}, openai_body("c"))] * 3)
        code, log = self.go(third, cases)
        self.assertEqual((code, len(third.calls)), (0, 3), log)

    def test_process_environment_key_is_not_used(self):
        with mock.patch.dict(os.environ, {"STUB_KEY": SECRET}):
            code, log = support.run_main(
                ["--vendor", "stub", "--track", "grammar", "--cases-dir", CASES, "--run-dir", self.run],
                vendors_path=self.vendors, env_file=self.td / "missing.env")
        self.assertEqual(code, 2, log)
        self.assertIn("no API key", log)
        self.assertNotIn(SECRET, log)
        self.assertFalse(self.run.exists())

    def record(self, cid):
        return json.loads((self.run / "grammar" / (cid + ".json")).read_bytes())

    def test_error_record_is_retried_on_resume_and_ok_records_are_not_requested(self):
        fail = (500, {}, b'{"error":{"message":"upstream"}}')
        first = ScriptedTransport([(200, {}, openai_body("```ilang\n[READ:@SRC]\n```")),
                                   (200, {}, openai_body("second")), fail, fail, fail, fail])
        code, log = self.go(first)
        self.assertEqual(code, 0, log)
        self.assertEqual(len(first.calls), 6)
        self.assertTrue(all(c["timeout"] == 120 for c in first.calls))
        g3 = self.record("grammar-0003")
        self.assertEqual((g3["status"], g3["attempts"], g3["http_status"], g3["text"]), ("error", 4, 500, None))
        self.assertTrue((self.run / "DONE").exists())
        ok_before = {k: v for k, v in support.tree(self.run).items() if k in
                     ("grammar/grammar-0001.json", "grammar/grammar-0002.json")}

        second = ScriptedTransport([(200, {}, openai_body("again"))])
        code, log = self.go(second)
        self.assertEqual(code, 0, log)
        self.assertIn(" skip=2 todo=1 ", log)
        self.assertEqual(len(second.calls), 1)
        case3 = [c for c in support.load_cases(CASES, "grammar") if c["id"] == "grammar-0003"][0]
        body = json.loads(second.calls[0]["body"])
        self.assertEqual(body["messages"][1]["content"], runner.user_message(case3))
        self.assertEqual((body["temperature"], body["seed"], body["max_tokens"]), (0, 42, 64))
        g3 = self.record("grammar-0003")
        self.assertEqual((g3["status"], g3["attempts"], g3["text"], g3["response_model"]),
                         ("ok", 1, "again", "stub-model-ga"))
        after = support.tree(self.run)
        for k, v in ok_before.items():
            self.assertEqual(after[k], v)
        for name, data in after.items():
            self.assertNotIn(SECRET.encode("ascii"), data, name)
        self.assertNotIn(SECRET, log)

    def test_empty_content_with_finish_reason_length_is_ok_and_not_retried(self):
        stub = ScriptedTransport([(200, {}, openai_body(None, "length"))] * 3)
        code, log = self.go(stub)
        self.assertEqual(code, 0, log)
        self.assertEqual(len(stub.calls), 3)
        for cid in ("grammar-0001", "grammar-0002", "grammar-0003"):
            rec = self.record(cid)
            self.assertEqual((rec["status"], rec["text"], rec["finish_reason"], rec["attempts"]),
                             ("ok", "", "length", 1))
        again = ScriptedTransport([])
        code, log = self.go(again)
        self.assertEqual((code, len(again.calls)), (0, 0))


if __name__ == "__main__":
    unittest.main()
