# -*- coding: utf-8 -*-
"""batch.py: the pure helpers in process, and the whole driver on mock vendors in a temporary
copy of the repository (subprocesses; nothing is written into the repository, no socket is
opened). The parameter ladder against a live endpoint is exercised outside this suite, because
the runner's retry backoff makes each rejected request take 42 seconds."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import support
import batch

REPO = support.REPO


class HelperTests(unittest.TestCase):
    def test_slug(self):
        self.assertEqual(batch.slug("deepseek/deepseek-v4-flash:free"), "deepseek-deepseek-v4-flash-free")
        self.assertEqual(batch.slug("gpt-4.1"), "gpt-4.1")
        self.assertEqual(batch.slug("///"), "model")

    def test_chat_filter(self):
        for m in ("gpt-4.1", "claude-opus-5", "grok-4.6", "qwen3-235b-a22b", "gemini-3.8-flash", "glm-5.3-flash"):
            self.assertTrue(batch.is_chat_candidate(m), m)
        for m in ("text-embedding-3-large", "tts-1", "whisper-1", "dall-e-3", "gpt-image-1",
                  "omni-moderation-latest", "jina-reranker-v2", "sora-2", "veo-3"):
            self.assertFalse(batch.is_chat_candidate(m), m)

    def test_ladder_follows_the_error_text_first(self):
        base = {"temperature": 0, "seed": True, "max_tokens_field": "max_tokens", "max_tokens": 8192}
        self.assertEqual(batch.next_params(base, "attempt 1: http 400: Unsupported parameter: 'seed'."),
                         (dict(base, seed=False), "seed"))
        p, step = batch.next_params(dict(base, temperature=None),
                                    "http 400: 'max_tokens' is not supported with this model, use 'max_completion_tokens'")
        self.assertEqual((p["max_tokens_field"], step), ("max_completion_tokens", "field"))
        p, step = batch.next_params(base, "http 200 reply: choices[0].message.content is not a string (finish_reason length)")
        self.assertEqual((p["max_tokens"], step), (16000, "max_tokens"))
        p, step = batch.next_params(base, "empty reply (finish_reason length)")
        self.assertEqual((p["max_tokens"], step), (16000, "max_tokens"))

    def test_ladder_lowers_a_limit_called_too_large_and_never_raises_it_again(self):
        base = {"temperature": 0, "seed": True, "max_tokens_field": "max_tokens", "max_tokens": 8192}
        p, step = batch.next_params(base, "http 400: max_tokens is too large: 8192. This model supports at most 4096")
        self.assertEqual((p["max_tokens"], step), (4096, "lower"))
        p, step = batch.next_params(dict(base, max_tokens=4096, temperature=None, seed=False,
                                         max_tokens_field="max_completion_tokens"),
                                    "http 400: something else", lowered=True)
        self.assertEqual((p, step), (None, None))

    def test_ladder_without_a_hint_walks_the_fixed_order_and_ends(self):
        p = {"temperature": 0, "seed": True, "max_tokens_field": "max_tokens", "max_tokens": 8192}
        steps = []
        while True:
            p, step = batch.next_params(p, "http 400: bad request")
            if p is None:
                break
            steps.append(step)
        self.assertEqual(steps, ["temperature", "seed", "field", "max_tokens", "max_tokens"])

    def test_failure_text(self):
        ok = {"status": "ok", "text": "x"}
        self.assertEqual(batch.failure_text([ok, ok, ok]), "")
        self.assertIn("finish_reason length",
                      batch.failure_text([ok, {"status": "ok", "text": "  ", "finish_reason": "length"}, ok]))
        self.assertIn("http 400", batch.failure_text([ok, {"status": "error", "error": "attempt 1: http 400: x"}, ok]))

    def test_split_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.tar.gz"
            p.write_bytes(bytes(range(256)) * 10)
            parts = batch.split_file(p, 1000)
            self.assertEqual([q.name for q in parts], ["x.tar.gz.part01", "x.tar.gz.part02", "x.tar.gz.part03"])
            self.assertEqual(b"".join(q.read_bytes() for q in parts), p.read_bytes())
            self.assertEqual(batch.split_file(p, 5000), [])


@unittest.skipIf(shutil.which("bash") is None, "run.sh needs bash")
class MockBatchTests(unittest.TestCase):
    """vendors, screen, run, status and pack on three mock vendors, then the two resume paths
    and the key scan, all in a copy of the repository under a temporary home directory."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        cls.repo = root / "repo"
        shutil.copytree(REPO, cls.repo, ignore=shutil.ignore_patterns(
            ".git", "runs", "report", "batch", "__pycache__", "*.pyc"))
        cls.home = root / "home"
        cls.home.mkdir()
        cls.env = dict(support.child_env(), HOME=str(cls.home), USERPROFILE=str(cls.home), PYTHON=sys.executable)
        models = root / "models.txt"
        models.write_text("alpha\nbeta\ngamma\n", encoding="utf-8")
        cls.batch("vendors", "--prefix", "t", "--base-url", "", "--auth-env", "", "--api", "mock",
                  "--models", str(models))
        cls.batch("screen", "--workers", "2")
        cls.batch("run", "--parallel", "2", "--concurrency", "1", "--poll", "0.5")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    @classmethod
    def batch(cls, *args, check=True):
        cp = subprocess.run([sys.executable, "batch.py"] + list(args), cwd=cls.repo, env=cls.env,
                            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600)
        if check and cp.returncode != 0:
            raise AssertionError("batch.py %s exited %d: %s" % (" ".join(args), cp.returncode, cp.stderr[-500:]))
        return cp

    def full(self):
        return batch.read_tsv(self.repo / "batch" / "full.tsv", batch.FULL_COLS)

    def set_full(self, rows):
        batch.write_tsv(self.repo / "batch" / "full.tsv", batch.FULL_COLS, list(rows.values()))

    def test_a_every_model_screened_run_and_scored(self):
        screen = batch.read_tsv(self.repo / "batch" / "screen.tsv", batch.SCREEN_COLS)
        self.assertEqual({k: v["result"] for k, v in screen.items()}, {"t-alpha": "pass", "t-beta": "pass", "t-gamma": "pass"})
        full = self.full()
        self.assertEqual({k: v["state"] for k, v in full.items()}, {"t-alpha": "scored", "t-beta": "scored", "t-gamma": "scored"})
        for row in full.values():
            self.assertTrue((self.repo / "report" / Path(row["run_dir"]).name / "score.json").is_file())
        board = (self.repo / "report" / "SCOREBOARD.md").read_text(encoding="utf-8")
        for name in ("t-alpha", "t-beta", "t-gamma"):
            self.assertIn("| %s |" % name, board)
        self.assertIn("scored", self.batch("status").stdout)

    def test_b_a_run_stopped_without_done_is_resumed(self):
        full = self.full()
        row = full["t-alpha"]
        (self.repo / row["run_dir"] / "DONE").unlink()
        row.update(state="running", resumes="0", note="")
        self.set_full(full)
        self.batch("run", "--parallel", "2", "--concurrency", "1", "--poll", "0.5")
        row = self.full()["t-alpha"]
        self.assertEqual((row["state"], row["resumes"]), ("scored", "1"))
        self.assertTrue((self.repo / row["run_dir"] / "DONE").is_file())

    def test_c_error_records_are_requested_again_before_scoring(self):
        full = self.full()
        row = full["t-beta"]
        rd = self.repo / row["run_dir"]
        rec_path = sorted((rd / "exec").glob("*.json"))[0]
        rec = json.loads(rec_path.read_text(encoding="utf-8"))
        rec.update(status="error", text=None, error="attempt 1: http 500: planted")
        rec_path.write_text(json.dumps(rec), encoding="utf-8")
        row.update(state="running", resumes="0", note="")
        self.set_full(full)
        self.batch("run", "--parallel", "2", "--concurrency", "1", "--poll", "0.5")
        row = self.full()["t-beta"]
        self.assertEqual((row["state"], row["resumes"]), ("scored", "1"))
        self.assertEqual(json.loads(rec_path.read_text(encoding="utf-8"))["status"], "ok")
        self.assertIn("error_count=0", row["note"])

    def test_d_pack_refuses_a_file_holding_a_key_prefix(self):
        (self.home / ".ilang-conformance.env").write_text("T_KEY=planted-key-0123456789\n", encoding="utf-8")
        os.chmod(self.home / ".ilang-conformance.env", 0o600)
        vendors = json.loads((self.repo / "vendors.json").read_text(encoding="utf-8"))
        vendors.append({"name": "t-keyed", "api": "openai_compatible", "base_url": "https://example.invalid/v1",
                        "model": "keyed", "auth_env": "T_KEY", "max_tokens": 4096, "seed": True})
        (self.repo / "vendors.json").write_text(json.dumps(vendors), encoding="utf-8")
        listed = (self.repo / "batch" / "vendors.txt").read_text(encoding="utf-8")
        (self.repo / "batch" / "vendors.txt").write_text(listed + "t-keyed\n", encoding="utf-8")
        log = self.repo / self.full()["t-gamma"]["run_dir"] / "run.log"
        clean = log.read_text(encoding="utf-8")
        log.write_text(clean + "leak planted-key-0\n", encoding="utf-8")
        cp = self.batch("pack", check=False)
        self.assertNotEqual(cp.returncode, 0)
        self.assertIn("key prefix", cp.stderr)
        log.write_text(clean, encoding="utf-8")
        cp = self.batch("pack")
        self.assertIn("key scan clean", cp.stdout)
        packs = sorted((self.repo / "batch").glob("pack-*.tar.gz"))
        self.assertEqual(len(packs), 1)


if __name__ == "__main__":
    unittest.main()
