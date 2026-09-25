# -*- coding: utf-8 -*-
"""run.py key handling, redaction, 2xx replies without text and per-vendor sampling fields
(book §1 GENE secrets_never_in_repo, §4.3, §5.3 error_count; cases/SCHEMA.md §2.4, §8.6, §8.7 with the
amendments proposed in the review round). Offline: scripted transports and a fake socket object,
never the network."""

import http.client
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import support
from support import ScriptedTransport, runner

KEY = "sk-or-v1-" + "0123456789abcdef" * 4          # 73 characters, longer than any shortened note


def openai_vendor(**extra):
    entry = {"name": "stub", "api": "openai_compatible", "base_url": "https://stub.invalid/v1",
             "model": "stub/model", "auth_env": "STUB_KEY", "max_tokens": 64}
    entry.update(extra)
    return runner.check_vendor(entry)


def anthropic_vendor(**extra):
    entry = {"name": "stub-a", "api": "anthropic", "base_url": "https://stub.invalid", "model": "claude-opus-5",
             "auth_env": "STUB_KEY", "max_tokens": 16000}
    entry.update(extra)
    return runner.check_vendor(entry)


def longest_key_prefix(text):
    k = 0
    while k < len(KEY) and KEY[:k + 1] in text:
        k += 1
    return k


class KeySourceTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.td = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_key_comes_only_from_the_env_file(self):
        env = support.write_env_file(self.td / "keys.env", STUB_KEY=KEY)
        with mock.patch.dict(os.environ, {"STUB_KEY": "sk-from-the-environment"}):
            self.assertEqual(runner.load_key("STUB_KEY", env), KEY)
            self.assertIsNone(runner.load_key("STUB_KEY", self.td / "missing.env"))
            self.assertIsNone(runner.load_key("OTHER_KEY", env))

    def test_crlf_env_file_gives_the_key_without_the_carriage_return(self):
        path = self.td / "crlf.env"
        path.write_bytes(("STUB_KEY=%s\r\n" % KEY).encode("ascii"))
        if os.name == "posix":
            os.chmod(path, 0o600)
        self.assertEqual(runner.load_key("STUB_KEY", path), KEY)

    def test_values_with_whitespace_or_control_characters_are_refused_without_quoting_them(self):
        path = self.td / "bad.env"
        path.write_bytes(b"TAB=sk-one\ttwo\nDEL=sk-one\x7ftwo\nNBSP=sk-one\xc2\xa0two\n")
        if os.name == "posix":
            os.chmod(path, 0o600)
        for name in ("TAB", "DEL", "NBSP"):
            with self.subTest(name=name):
                with self.assertRaises(runner.ConfigError) as ctx:
                    runner.load_key(name, path)
                self.assertIn(name, str(ctx.exception))
                self.assertNotIn("sk-one", str(ctx.exception))

    @unittest.skipUnless(os.name == "posix", "file mode bits are POSIX only")
    def test_env_file_accessible_to_group_or_others_is_refused(self):
        path = support.write_env_file(self.td / "keys.env", STUB_KEY=KEY)
        os.chmod(path, 0o640)
        with self.assertRaises(runner.ConfigError) as ctx:
            runner.load_key("STUB_KEY", path)
        self.assertIn("chmod 600", str(ctx.exception))
        self.assertNotIn(KEY, str(ctx.exception))


class RedactionTests(unittest.TestCase):
    def test_key_echoed_in_a_long_vendor_message_is_redacted_before_shortening(self):
        message = ("Authentication failed: the Authorization header carried the key " + KEY
                   + " which is not valid for this route")
        log = io.StringIO()
        vendor = openai_vendor()
        res = runner.call_real(vendor, "S", "U", KEY,
                               ScriptedTransport([(401, {}, json.dumps({"error": {"message": message}}).encode())] * 4),
                               lambda seconds: None, runner.Log(log, KEY), "grammar-0001")
        record = runner.canon_ascii(runner.make_record({"id": "grammar-0001", "track": "grammar"},
                                                       runner.request_summary(vendor, "S", "U"), res, KEY))
        self.assertEqual(res["status"], "error")
        self.assertIn(runner.REDACTED, record)
        self.assertLess(longest_key_prefix(record), 4)
        self.assertLess(longest_key_prefix(log.getvalue()), 4)

    def test_invalid_header_value_never_reaches_the_transport_error_text(self):
        class FakeSock:
            def settimeout(self, seconds):
                pass

            def close(self):
                pass

        with mock.patch.object(http.client.HTTPConnection, "connect",
                               lambda self: setattr(self, "sock", FakeSock())):
            with self.assertRaises(runner.TransportError) as ctx:
                runner.http_transport("http://stub.invalid/v1/chat/completions",
                                      {"Authorization": "Bearer " + KEY + "\r"}, b"{}", 5)
        self.assertIn("withheld", str(ctx.exception))
        self.assertLess(longest_key_prefix(str(ctx.exception)), 4)

    def test_key_echoed_in_the_reply_text_is_redacted_from_the_record(self):
        vendor = openai_vendor()
        body = support.openai_body("echo " + KEY)
        res = runner.call_real(vendor, "S", "U", KEY, ScriptedTransport([(200, {}, body)]), lambda seconds: None,
                               runner.Log(io.StringIO(), KEY), "grammar-0001")
        record = runner.canon_ascii(runner.make_record({"id": "grammar-0001", "track": "grammar"},
                                                       runner.request_summary(vendor, "S", "U"), res, KEY))
        self.assertNotIn(KEY, record)
        self.assertEqual(json.loads(record)["text"], "echo " + runner.REDACTED)


class EmptyReplyTests(unittest.TestCase):
    def attempt(self, vendor, body):
        waits = []
        res = runner.call_real(vendor, "S", "U", "k", ScriptedTransport([(200, {}, json.dumps(body).encode())]),
                               waits.append, runner.Log(io.StringIO(), "k"), "exec-0001")
        return res, waits

    def test_documented_2xx_replies_without_text_are_ok_and_not_retried(self):
        replies = [
            (anthropic_vendor(), {"model": "claude-opus-5", "content": [], "stop_reason": "refusal",
                                  "stop_details": {"type": "refusal", "category": None}}),
            (anthropic_vendor(), {"model": "claude-opus-5", "content": [], "stop_reason": "end_turn"}),
            (anthropic_vendor(), {"model": "claude-opus-5", "content": [{"type": "thinking", "thinking": ""}],
                                  "stop_reason": "max_tokens"}),
            (openai_vendor(), {"model": "m", "choices": [{"finish_reason": "stop", "message": {
                "role": "assistant", "content": None, "refusal": "I can't help with that."}}]}),
            (openai_vendor(), {"model": "m", "choices": [{"finish_reason": "content_filter",
                                                          "message": {"role": "assistant", "content": None}}]}),
            (openai_vendor(), {"model": "m", "choices": [{"finish_reason": "length",
                                                          "message": {"role": "assistant", "content": None}}]}),
        ]
        for vendor, body in replies:
            with self.subTest(body=body):
                res, waits = self.attempt(vendor, body)
                self.assertEqual((res["status"], res["text"], res["attempts"], waits, res["error"]),
                                 ("ok", "", 1, [], None))

    def test_malformed_2xx_bodies_are_still_failed_attempts(self):
        for vendor, body in ((openai_vendor(), {"choices": [{"finish_reason": "stop", "message": {"content": None}}]}),
                             (anthropic_vendor(), {"content": [], "stop_reason": "pause_turn"}),
                             (anthropic_vendor(), {"stop_reason": "end_turn"})):
            with self.subTest(body=body):
                with self.assertRaises(runner.ReplyError):
                    runner.extract_reply(vendor["api"], body)


class SamplingFieldTests(unittest.TestCase):
    def test_default_temperature_is_zero_and_recorded(self):
        vendor = openai_vendor()
        body = json.loads(runner.build_request(vendor, "S", "U", "k")[2])
        summary = runner.request_summary(vendor, "S", "U")
        self.assertEqual((body["temperature"], body["max_tokens"], body["seed"]), (0, 64, 42))
        self.assertEqual((summary["temperature"], summary["max_tokens"], summary["max_tokens_field"], summary["seed"]),
                         (0, 64, "max_tokens", 42))

    def test_temperature_null_is_omitted_and_recorded_as_null(self):
        vendor = anthropic_vendor(temperature=None)
        body = json.loads(runner.build_request(vendor, "S", "U", "k")[2])
        self.assertNotIn("temperature", body)
        self.assertEqual(body["max_tokens"], 16000)
        self.assertIsNone(runner.request_summary(vendor, "S", "U")["temperature"])

    def test_max_completion_tokens_field(self):
        vendor = openai_vendor(max_tokens_field="max_completion_tokens", seed=False)
        body = json.loads(runner.build_request(vendor, "S", "U", "k")[2])
        self.assertEqual(body.get("max_completion_tokens"), 64)
        self.assertNotIn("max_tokens", body)
        self.assertNotIn("seed", body)
        self.assertEqual(runner.request_summary(vendor, "S", "U")["max_tokens_field"], "max_completion_tokens")

    def test_invalid_entries_are_configuration_errors(self):
        for extra in ({"temperature": 0.7}, {"temperature": True}, {"max_tokens_field": "tokens"},
                      {"cache_system": "yes"}, {"extra_body": []}, {"extra_body": {}},
                      {"extra_body": {"model": "other"}}, {"extra_body": {"max_tokens": 1}}):
            with self.subTest(extra=extra), self.assertRaises(runner.ConfigError):
                openai_vendor(**extra)
        with self.assertRaises(runner.ConfigError):
            anthropic_vendor(max_tokens_field="max_completion_tokens")
        with self.assertRaises(runner.ConfigError):
            anthropic_vendor(extra_body={"provider": {"order": ["Anthropic"]}})
        with self.assertRaises(runner.ConfigError):
            runner.check_vendor({"name": "m", "api": "mock", "base_url": "", "model": "m", "auth_env": "", "cache_system": True})

    def test_cache_system_and_extra_body(self):
        routing = {"provider": {"order": ["Anthropic"], "allow_fallbacks": False}}
        vendor = openai_vendor(cache_system=True, extra_body=routing)
        body = json.loads(runner.build_request(vendor, "S", "U", "k")[2])
        self.assertEqual(body["messages"][0], {"role": "system", "content": [
            {"type": "text", "text": "S", "cache_control": {"type": "ephemeral"}}]})
        self.assertEqual(body["messages"][1], {"role": "user", "content": "U"})
        self.assertEqual(body["provider"], routing["provider"])
        self.assertEqual((body["model"], body["temperature"], body["max_tokens"], body["seed"]), ("stub/model", 0, 64, 42))
        summary = runner.request_summary(vendor, "S", "U")
        self.assertEqual((summary["cache_system"], summary["extra_body"]), (True, routing))
        self.assertEqual(summary["system_sha256"], runner.request_summary(openai_vendor(), "S", "U")["system_sha256"])
        plain = runner.request_summary(openai_vendor(), "S", "U")
        self.assertNotIn("cache_system", plain)
        self.assertNotIn("extra_body", plain)
        self.assertEqual(json.loads(runner.build_request(openai_vendor(), "S", "U", "k")[2])["messages"][0]["content"], "S")
        anth = anthropic_vendor(cache_system=True)
        self.assertEqual(json.loads(runner.build_request(anth, "S", "U", "k")[2])["system"],
                         [{"type": "text", "text": "S", "cache_control": {"type": "ephemeral"}}])

    def test_shipped_vendor_entries(self):
        entries = json.loads((support.REPO / "vendors.json").read_bytes())
        checked = {e["name"]: runner.check_vendor(e) for e in entries}
        self.assertEqual((checked["anthropic"]["temperature"], checked["anthropic"]["max_tokens"]), (None, 16000))
        for name in ("orcarouter-deepseek-free", "orcarouter-glm-free", "deepseek"):
            self.assertEqual((checked[name]["temperature"], checked[name]["max_tokens_field"]), (0, "max_tokens"))
        self.assertIsNone(checked["mock"]["temperature"])


if __name__ == "__main__":
    unittest.main()
