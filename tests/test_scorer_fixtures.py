# -*- coding: utf-8 -*-
"""Golden scorer fixtures: every tests/fixtures/scorer/<scenario>/expect.json is checked against what score.py
does with the run directories next to it, so an expect.json cannot drift from the scorer unnoticed (until
2026-11-26 `perfect` and `prose` described the lint file of SCHEMA §3.5 without LINT_PREAMBLE_BREAK, and no test
read them). Subprocesses on copies in a temporary directory; nothing is written into the repository."""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

import support

SCORER = support.FIXTURES / "scorer"
KEYS_ONE_RUN = {"description", "exit", "run", "score", "stderr_contains", "tracks"}
KEYS_LATEST = {"description", "exit", "select", "stderr_contains"}


def differences(expected, actual, path=""):
    """Paths at which `actual` departs from `expected`. A dict in expect.json names the keys it pins and may
    leave others out; lists and scalars must be equal, booleans and numbers kept apart."""
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return ["%s: expected an object, got %r" % (path, actual)]
        out = []
        for key, value in expected.items():
            if key not in actual:
                out.append("%s/%s: missing" % (path, key))
            else:
                out += differences(value, actual[key], "%s/%s" % (path, key))
        return out
    if isinstance(expected, list):
        if not isinstance(actual, list) or len(expected) != len(actual):
            return ["%s: expected %r, got %r" % (path, expected, actual)]
        out = []
        for k, (e, a) in enumerate(zip(expected, actual)):
            out += differences(e, a, "%s[%d]" % (path, k))
        return out
    if expected != actual or type(expected) is not type(actual):
        return ["%s: expected %r, got %r" % (path, expected, actual)]
    return []


class ScorerFixtureTests(unittest.TestCase):
    def one_run(self, expect, runs, report):
        code, out, err = support.score_cli([runs / expect["run"], "--cases", SCORER / "cases", "--report", report])
        self.assertEqual(code, expect["exit"], err)
        if "stderr_contains" in expect:
            self.assertIn(expect["stderr_contains"], err.replace("\\", "/"))
        if code != 0:
            self.assertFalse(report.exists())
            self.assertNotIn("score", expect)
            return
        actual = json.loads((report / expect["run"] / "score.json").read_bytes().decode("utf-8"))
        self.assertEqual(differences(expect["score"], actual), [])
        self.assertEqual(sorted(actual["tracks"]), expect["tracks"])

    def latest(self, expect, runs, td):
        for vendor in sorted(expect["exit"]):
            report = td / ("report-" + vendor)
            code, out, err = support.score_cli(["--latest", "--vendor", vendor, "--runs", runs,
                                                "--cases", SCORER / "cases", "--report", report])
            self.assertEqual(code, expect["exit"][vendor], err)
            if vendor in expect["stderr_contains"]:
                self.assertIn(expect["stderr_contains"][vendor], err.replace("\\", "/"))
            if code == 0:
                self.assertTrue((report / expect["select"][vendor] / "score.json").is_file())
            else:
                self.assertFalse(report.exists())

    def test_every_scenario_gives_what_its_expect_json_says(self):
        scenarios = sorted(p.name for p in SCORER.iterdir() if p.is_dir() and p.name != "cases")
        self.assertEqual(scenarios, sorted(p.parent.name for p in SCORER.glob("*/expect.json")))
        self.assertGreaterEqual(len(scenarios), 8)
        for name in scenarios:
            expect = json.loads((SCORER / name / "expect.json").read_bytes().decode("utf-8"))
            with self.subTest(scenario=name), tempfile.TemporaryDirectory() as tmp:
                td = Path(tmp)
                runs = td / "runs"
                shutil.copytree(SCORER / name, runs, ignore=shutil.ignore_patterns("expect.json"))
                if isinstance(expect.get("run"), str):
                    self.assertLessEqual(set(expect), KEYS_ONE_RUN)
                    self.one_run(expect, runs, td / "report")
                else:
                    self.assertEqual(set(expect), KEYS_LATEST)
                    self.latest(expect, runs, td)


if __name__ == "__main__":
    unittest.main()
