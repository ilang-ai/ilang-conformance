# -*- coding: utf-8 -*-
"""controls/compare_arms.py: the judge "same mode" agreement between two arms counts only the cases where both
arms gave a schema-valid block. score.py pads a reply without one with pred_mode "none", and two padded replies
are not an agreement. Synthetic records, scored by score.score_judge; temporary directories only, no socket."""

import io
import json
import sys
import tempfile
import unittest
import warnings
from contextlib import redirect_stdout
from pathlib import Path

import support
from support import score

sys.path.insert(0, str(support.REPO / "controls"))
import compare_arms  # noqa: E402

jv = score.vendor_module("ilang_judge_validator")
VECTOR = {d: 0.5 for d in support.DIMS}
GOLD_MODE = jv.f_v5(VECTOR)
OTHER_MODE = "M1" if GOLD_MODE != "M1" else "M2"
CASES = [{"id": "judge-%04d" % k, "boundary": False, "gold_v": VECTOR} for k in range(1, 6)]
VALID = "\n".join(support.judge_block(VECTOR, GOLD_MODE))
VALID_OTHER_MODE = "\n".join(support.judge_block(VECTOR, OTHER_MODE))
EXPECTED = {"n": 5, "same_mode": 1, "both_valid": 2, "both_parsed": 2, "same_vector": 2}


def arm(root, name, texts):
    """A run directory holding the judge records, its score object with the scorer's own rows, and the records."""
    run = Path(root, "runs", name)
    (run / "judge").mkdir(parents=True)
    recs = {}
    for case, text in zip(CASES, texts):
        recs[case["id"]] = {"id": case["id"], "track": "judge", "status": "ok", "text": text, "finish_reason": "stop",
                            "usage": {"prompt_tokens": 1}, "request": {"vendor": name, "model": "stub/model"}}
        (run / "judge" / (case["id"] + ".json")).write_text(json.dumps(recs[case["id"]], ensure_ascii=False),
                                                           encoding="utf-8")
    track = score.score_judge(CASES, recs, run)
    return run, {"summary": {}, "tracks": {"judge": track}}, {"judge": list(recs.values())}


class SameModeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.td = Path(cls._tmp.name)
        compare_arms.JV = jv
        # judge-0001 neither arm parses; 0002 both valid, same mode; 0003 both valid, different modes;
        # 0004 only arm a valid; 0005 neither arm parses
        cls.run_a, cls.score_a, cls.recs_a = arm(cls.td, "arm-a-20260101-000001", [
            "I cannot produce a block.", VALID, VALID, VALID, ""])
        cls.run_b, cls.score_b, cls.recs_b = arm(cls.td, "arm-b-20260101-000002", [
            "No block here either.", VALID, VALID_OTHER_MODE, "prose only", "::JUDGE{v5.0}\nV:[int=0.5]"])

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_the_scorer_pads_an_unparsed_reply_with_mode_none(self):
        for obj in (self.score_a, self.score_b):
            rows = {r["id"]: r for r in obj["tracks"]["judge"]["cases"]}
            for cid in ("judge-0001", "judge-0005"):
                with self.subTest(id=cid):
                    self.assertEqual((rows[cid]["schema_valid"], rows[cid]["pred_mode"]), (False, "none"))

    def test_same_mode_counts_only_cases_both_arms_parsed(self):
        judge = compare_arms.agreement(self.recs_a, self.score_a, self.recs_b, self.score_b)["judge"]
        self.assertEqual(judge["same_mode"], 1)
        self.assertEqual(judge, EXPECTED)

    def test_two_arms_that_never_parse_agree_on_nothing(self):
        rows = [dict(r, schema_valid=False, pred_mode="none") for r in self.score_a["tracks"]["judge"]["cases"]]
        blank = {"summary": {}, "tracks": {"judge": {"cases": rows}}}
        judge = compare_arms.agreement({}, blank, {}, blank)["judge"]
        self.assertEqual(judge["same_mode"], 0)
        self.assertEqual(judge["both_valid"], 0)

    def test_arms_md_prints_same_mode_over_the_cases_both_parsed(self):
        pairs = self.td / "pairs.json"
        pairs.write_text(json.dumps({"stub": {"arms": {"api.b.ai": self.run_a.name, "other route": self.run_b.name}}}),
                         encoding="utf-8")
        report = self.td / "report"
        for run, obj in ((self.run_a, self.score_a), (self.run_b, self.score_b)):
            (report / run.name).mkdir(parents=True)
            (report / run.name / "score.json").write_text(json.dumps(obj), encoding="utf-8")
        out = self.td / "out"
        with redirect_stdout(io.StringIO()), warnings.catch_warnings():
            warnings.simplefilter("ignore", ResourceWarning)     # the script leaves its input files to the collector
            code = compare_arms.main(["--pairs", str(pairs), "--runs-a", str(self.td / "runs"),
                                      "--report-a", str(report), "--report-b", str(report), "--out", str(out)])
        self.assertEqual(code, 0)
        lines = (out / "ARMS.md").read_text(encoding="utf-8").split("\n")
        row = [x for x in lines if x.startswith("| other route |") and "pass)" in x]      # the agreement row
        self.assertEqual(len(row), 1)
        self.assertTrue(row[0].endswith("| 1/2 parsed | 2/2 parsed |"), row[0])
        arms = json.loads((out / "arms.json").read_text(encoding="utf-8"))
        self.assertEqual(arms["stub"]["agreement_vs_api.b.ai"]["other route"]["judge"], EXPECTED)


if __name__ == "__main__":
    unittest.main()
