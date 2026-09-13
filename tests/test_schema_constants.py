# -*- coding: utf-8 -*-
"""Constants embedded in run.py, score.py, validate_cases.py and gen_judge_cases.py are
byte-identical with their cases/SCHEMA.md blocks (SCHEMA §0.3 regex ownership, §0.4 text blocks)."""

import unittest

import support
from support import runner, score

import gen_judge_cases
import validate_cases


class SchemaConstantTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.texts, cls.regexes = support.schema_blocks()

    def check_regex(self, module, name):
        self.assertIn(name, self.regexes, "cases/SCHEMA.md has no regex block %s" % name)
        pattern, flags_line = self.regexes[name]
        self.assertTrue(flags_line.startswith("Flags:"), "%s: line after the block is %r" % (name, flags_line))
        rx = getattr(module, name)
        self.assertEqual(rx.pattern, pattern, "%s.%s pattern" % (module.__name__, name))
        self.assertEqual(rx.flags, support.expected_flags(flags_line), "%s.%s flags" % (module.__name__, name))

    def test_score_regexes(self):
        for name in ("ILANG_LINE", "FENCE_DELIM", "FENCE_INFO", "EVAL_SUMMARY_LINE", "EVAL_JCS_LINE",
                     "RUN_DIR_NAME", "MANIFEST_LINE", "PIN_COMMIT"):
            with self.subTest(name=name):
                self.check_regex(score, name)

    def test_validate_cases_regexes(self):
        for name in ("CASE_ID", "VECTOR_RENDER", "CANARY_FORMAT", "DECL_LINE", "ILANG_LINE",
                     "FENCE_DELIM", "FENCE_INFO"):
            with self.subTest(name=name):
                self.check_regex(validate_cases, name)

    def test_run_regexes(self):
        for name in ("CASE_ID", "RUN_DIR_NAME", "MANIFEST_LINE"):
            with self.subTest(name=name):
                self.check_regex(runner, name)

    def test_text_blocks(self):
        pairs = [(score, "LINT_HEADER"), (validate_cases, "LINT_HEADER"),
                 (validate_cases, "JUDGE_V2M_PROMPT"), (gen_judge_cases, "JUDGE_V2M_PROMPT")]
        pairs += [(runner, n) for n in ("SYSTEM_SEPARATOR", "CONTRACT_GRAMMAR", "CONTRACT_EXEC", "CONTRACT_JUDGE",
                                        "USER_TEMPLATE", "TAIL_GRAMMAR", "TAIL_EXEC", "TAIL_JUDGE")]
        for module, name in pairs:
            with self.subTest(module=module.__name__, name=name):
                self.assertIn(name, self.texts)
                self.assertEqual(getattr(module, name), self.texts[name])

    def test_dims_agree_with_the_vendored_judge_validator(self):
        jv = score.vendor_module("ilang_judge_validator")
        for dims in (validate_cases.DIMS, gen_judge_cases.DIMS, support.DIMS):
            self.assertEqual(list(dims), list(jv.DIMS))

    def test_mock_grammar_reply_is_gold_wrap(self):
        for case in support.load_cases(support.RUNNER_CASES, "grammar"):
            gold = (support.RUNNER_CASES / "grammar" / "gold" / (case["id"] + ".ilang")).read_bytes().decode("utf-8")
            with self.subTest(id=case["id"]):
                self.assertEqual(runner.mock_reply(case, support.RUNNER_CASES), validate_cases.GOLD_WRAP(gold))


if __name__ == "__main__":
    unittest.main()
