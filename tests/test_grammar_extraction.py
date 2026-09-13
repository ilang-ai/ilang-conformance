# -*- coding: utf-8 -*-
"""Grammar payload extraction, header prepend, assertions and lint scoring edge cases
(cases/SCHEMA.md §3.1-§3.6, §7, §8.1; book §5.0 grammar载荷, grammar封装, grammar断言)."""

import tempfile
import unittest
from pathlib import Path

import support
from support import score

import validate_cases

CHAIN = "[READ:@GH|path=config.json]=>[FMT|fmt=json]=>[Ω]"
EXPECT = {"lint_errors": 0, "must_contain": [["[READ:", "[READ|"], "fmt=json"], "must_not_contain": ["fmt=JSON"]}

# responses shared by the extraction tests and the score.py / validate_cases.py agreement test
SAMPLES = {
    "unterminated": "```ilang\n[READ:@SRC]\nThanks!",
    "any_delimiter_closes": "```ilang\n[READ:@A]\n````text trailing\n[READ:@B]",
    "tilde": "~~~ilang\n[READ:@SRC]\n~~~",
    "text_fence": "```text\n[READ:@SRC]=>[Ω]\n```",
    "unlabeled_ilang": "```\n\n  [READ:@SRC]\nprose after\n```",
    "unlabeled_prose": "```\nhello\n[READ:@SRC]\n```",
    "last_nonempty_wins": "```ilang\n[READ:@A]\n```\ntext\n```ilang\n[READ:@B]\n```\n```ilang\n   \n```",
    "empty_fence_only": "```ilang\n\n```\nSorry.",
    "empty_fence_then_bare": "```ilang\n```\n[READ:@SRC]",
    "bare_last_segment": "[READ:@A]\n\n[READ:@B]\n=>[Ω]\nThat is all.",
    "bare_indent": "  [READ:@A]\n    =>[Ω]",
    "bare_declaration_body": "::GENE{g|conf:confirmed}\n  T:check_before_execute",
    "crlf": "```ilang\r\n[READ:@SRC]\r\n```\r\n",
    "prose_only": "I would read the file and output JSON.",
    "header_in_fence": "```ilang\n::ILANG::v4.0\n" + CHAIN + "\n```",
    "greek_bare": "Answer:\n[φ:@LOG|whr=lvl:fatal]=>[CNT]=>[Ω]",
}


class IlangLineTests(unittest.TestCase):
    def test_lines_that_start_ilang(self):
        for s in ("::ILANG::v4.0", "::FACT{key:a|value:b}", "[READ:@SRC]", "[Ω]", "[φ:@LOG]",
                  "=>[FMT|fmt=json]", "T[1] ::STATE{@X}", "[README](https://example.com)"):
            with self.subTest(line=s):
                self.assertTrue(score.ILANG_LINE.match(s))

    def test_lines_that_do_not(self):
        for s in ("", "[read:@SRC]", "- [READ:@SRC]", "T:check", "[1]", "Here [READ:@SRC]",
                  "⇒[FMT]", "`[READ:@SRC]`", "> [READ:@SRC]"):
            with self.subTest(line=s):
                self.assertIsNone(score.ILANG_LINE.match(s))


class FenceAndPayloadTests(unittest.TestCase):
    def payload(self, key):
        return score.grammar_payload(SAMPLES[key])

    def test_unterminated_fence_runs_to_the_end(self):
        self.assertEqual(score.fences(["```ilang", "[READ:@SRC]"]), [("ilang", ["[READ:@SRC]"])])
        self.assertEqual(self.payload("unterminated"), ("fence", ["[READ:@SRC]", "Thanks!"]))

    def test_any_delimiter_line_closes_the_fence(self):
        self.assertEqual(self.payload("any_delimiter_closes"), ("fence", ["[READ:@A]"]))

    def test_tilde_fences_are_not_fences(self):
        self.assertEqual(score.fences(SAMPLES["tilde"].splitlines()), [])
        self.assertEqual(self.payload("tilde"), ("bare", ["[READ:@SRC]"]))

    def test_info_word_is_case_insensitive_and_first_word_only(self):
        for info in ("ilang", "ILANG", "i-lang", "I-Lang", "ilang extra words", " ilang"):
            with self.subTest(info=info):
                self.assertEqual(score.grammar_payload("```%s\nhello\n```" % info), ("fence", ["hello"]))
        self.assertEqual(score.grammar_payload("   ```ilang\nhello\n   ```"), ("fence", ["hello"]))

    def test_other_info_fence_is_scanned_as_bare_lines(self):
        self.assertEqual(self.payload("text_fence"), ("bare", ["[READ:@SRC]=>[Ω]"]))
        self.assertEqual(score.grammar_payload("```json\n[READ:@SRC]\n```"), ("bare", ["[READ:@SRC]"]))

    def test_unlabeled_fence_is_judged_by_its_first_nonblank_line(self):
        self.assertEqual(self.payload("unlabeled_ilang"), ("fence", ["", "  [READ:@SRC]", "prose after"]))
        self.assertEqual(self.payload("unlabeled_prose"), ("bare", ["[READ:@SRC]"]))

    def test_last_nonempty_ilang_fence_wins(self):
        self.assertEqual(self.payload("last_nonempty_wins"), ("fence", ["[READ:@B]"]))

    def test_empty_ilang_fence_is_never_the_payload(self):
        self.assertEqual(self.payload("empty_fence_only"), ("none", []))
        self.assertEqual(self.payload("empty_fence_then_bare"), ("bare", ["[READ:@SRC]"]))

    def test_bare_scan_takes_the_last_maximal_segment_unstripped(self):
        self.assertEqual(self.payload("bare_last_segment"), ("bare", ["[READ:@B]", "=>[Ω]"]))
        self.assertEqual(self.payload("bare_indent"), ("bare", ["  [READ:@A]", "    =>[Ω]"]))
        self.assertEqual(self.payload("greek_bare"), ("bare", ["[φ:@LOG|whr=lvl:fatal]=>[CNT]=>[Ω]"]))

    def test_declaration_body_lines_break_a_bare_segment_but_not_a_fence(self):
        self.assertEqual(self.payload("bare_declaration_body"), ("bare", ["::GENE{g|conf:confirmed}"]))
        fenced = "```ilang\n" + SAMPLES["bare_declaration_body"] + "\n```"
        self.assertEqual(score.grammar_payload(fenced),
                         ("fence", ["::GENE{g|conf:confirmed}", "  T:check_before_execute"]))

    def test_crlf_response(self):
        self.assertEqual(self.payload("crlf"), ("fence", ["[READ:@SRC]"]))

    def test_prose_only_response_has_no_payload(self):
        self.assertEqual(self.payload("prose_only"), ("none", []))


class HeaderPrependTests(unittest.TestCase):
    def test_header_and_preamble_break_prepended_when_missing(self):
        self.assertEqual(score.lint_input(["[READ:@SRC]"]),
                         (True, "::ILANG::v4.0\nT[0]\n[READ:@SRC]\n".encode("utf-8")))

    def test_existing_header_after_blank_and_indent_is_kept_and_followed_by_the_break(self):
        self.assertEqual(score.lint_input(["", "  ::ILANG::v4.1", "[READ:@SRC]"]),
                         (False, b"\n  ::ILANG::v4.1\nT[0]\n[READ:@SRC]\n"))

    def test_lone_surrogate_is_replaced_not_fatal(self):
        prepended, data = score.lint_input(["[READ:@SRC|path=a\ud800]"])
        self.assertTrue(prepended)
        self.assertEqual(data, b"::ILANG::v4.0\nT[0]\n[READ:@SRC|path=a?]\n")

    def test_preamble_break_is_the_documented_constant(self):
        self.assertEqual((score.LINT_PREAMBLE_BREAK, validate_cases.LINT_PREAMBLE_BREAK), ("T[0]", "T[0]"))


class AssertionTests(unittest.TestCase):
    EXPECT = {"lint_errors": 0, "must_contain": [["[READ:", "[READ|"], "fmt=json", "grp="],
              "must_not_contain": ["fmt=JSON", "group_by="]}

    def test_synonym_group_case_sensitivity_and_hit_order(self):
        self.assertEqual(score.grammar_assertions(self.EXPECT, "[READ|src=@LOCAL]=>[FMT|group_by=x,fmt=JSON]"),
                         ([1, 2], ["fmt=JSON", "group_by="]))
        self.assertEqual(score.grammar_assertions(self.EXPECT, "[READ:@LOCAL]=>[GRP|grp=region]=>[FMT|fmt=json]"),
                         ([], []))

    def test_empty_payload_fails_every_must_contain_element(self):
        self.assertEqual(score.grammar_assertions(self.EXPECT, ""), ([0, 1, 2], []))


class ImplementationAgreementTests(unittest.TestCase):
    """score.py and validate_cases.py carry separate copies of SCHEMA §3.2-§3.5; they must agree."""

    def test_payload_and_lint_input_agree(self):
        for key, text in SAMPLES.items():
            with self.subTest(sample=key):
                source, payload_lines = score.grammar_payload(text)
                self.assertEqual(validate_cases.grammar_payload(text), (source, payload_lines))
                v_source, v_payload, v_nonempty, v_prepended, v_bytes = validate_cases.lint_input(text)
                self.assertEqual(v_payload, "\n".join(payload_lines))
                self.assertEqual(v_nonempty, any(x.strip() for x in payload_lines))
                if v_nonempty:
                    self.assertEqual((v_prepended, v_bytes), score.lint_input(payload_lines))


class LintScoringTests(unittest.TestCase):
    """score_grammar end to end through the vendored linter (one batched --lint --json call)."""

    @classmethod
    def setUpClass(cls):
        responses = [
            ("```ilang\n" + CHAIN + "\n```", "ok"),                                         # 0001 pass, header prepended
            ("Here you go:\n" + CHAIN, "ok"),                                               # 0002 pass, bare
            ("```ilang\nI would use [READ: on config.json and fmt=json.\n```", "ok"),       # 0003 prose in fence: E300
            ("I would use [READ: on config.json and fmt=json.", "ok"),                      # 0004 prose, no payload
            ("```ilang\n" + CHAIN.replace("fmt=json", "fmt=JSON") + "\n```", "ok"),         # 0005 wrong value, lint 0
            (None, "error"),                                                                # 0006 error record
            (SAMPLES["header_in_fence"], "ok"),                                             # 0007 own header
            ("```ilang\n" + CHAIN + "\nThen save it.\n```", "ok"),                          # 0008 trailing prose: E300
            ("```ilang\n[READ:@LOCAL|path=config.json]\n  =>[FMT|fmt=json]\n  =>[Ω]\n```", "ok"),  # 0009 multi-line chain
            ("```ilang\n[READ:@LOCAL|path=config.json,fmt=json,tone=formal]\n```", "ok"),     # 0010 unregistered key: E302
            ("```ilang\n[READ:config|path=config.json,fmt=json]\n```", "ok"),                 # 0011 bareword target: E300
            ("```ilang\n::ILANG::v4.0\n[READ:@LOCAL|path=config.json]\n  =>[FMT|fmt=json]\n```", "ok"),  # 0012 own header
        ]
        cls.cases, recs = [], {}
        for k, (text, status) in enumerate(responses, 1):
            cid = "grammar-%04d" % k
            cls.cases.append({"id": cid, "expect": EXPECT})
            recs[cid] = {"status": status, "text": text}
        cls._tmp = tempfile.TemporaryDirectory()
        cls.work = Path(cls._tmp.name)
        cls.result = score.score_grammar(cls.cases, recs, cls.work)
        cls.rows = {r["id"]: r for r in cls.result["cases"]}

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def row(self, k):
        return self.rows["grammar-%04d" % k]

    def test_fenced_chain_passes_with_prepended_header(self):
        r = self.row(1)
        self.assertEqual((r["pass"], r["payload_source"], r["header_prepended"], r["lint_errors"]),
                         (True, "fence", True, 0))

    def test_bare_chain_after_prose_passes(self):
        r = self.row(2)
        self.assertEqual((r["pass"], r["payload_source"], r["lint_errors"]), (True, "bare", 0))

    def test_prose_inside_fence_fails_lint_even_when_assertions_pass(self):
        r = self.row(3)
        self.assertFalse(r["pass"])
        self.assertEqual((r["must_contain_failed"], r["must_not_contain_hit"]), ([], []))
        self.assertGreaterEqual(r["lint_errors"], 1)
        self.assertIn("E300", r["lint_error_codes"])

    def test_unfenced_prose_has_empty_payload_and_is_not_linted(self):
        r = self.row(4)
        self.assertEqual((r["pass"], r["payload_source"], r["payload_nonempty"], r["header_prepended"],
                          r["lint_errors"], r["lint_warnings"], r["must_contain_failed"]),
                         (False, "none", False, False, None, None, [0, 1]))

    def test_wrong_value_is_caught_by_assertions_not_lint(self):
        r = self.row(5)
        self.assertEqual((r["pass"], r["lint_errors"], r["must_contain_failed"], r["must_not_contain_hit"]),
                         (False, 0, [1], ["fmt=JSON"]))

    def test_error_record_row(self):
        self.assertEqual(self.row(6), {"id": "grammar-0006", "status": "error", "payload_source": "none",
                                       "payload_nonempty": False, "header_prepended": False, "lint_errors": None,
                                       "lint_warnings": None, "lint_error_codes": [], "must_contain_failed": [],
                                       "must_not_contain_hit": [], "pass": False})

    def test_payload_with_its_own_header_is_not_prepended(self):
        r = self.row(7)
        self.assertEqual((r["pass"], r["header_prepended"], r["lint_errors"]), (True, False, 0))

    def test_prose_after_an_operation_fails_lint(self):
        r = self.row(8)
        self.assertFalse(r["pass"])
        self.assertIn("E300", r["lint_error_codes"])

    def test_multi_line_chain_opening_with_a_targeted_operation_passes(self):
        # without the preamble break the first line sat in the §1.7 preamble position and every
        # `=>` line after it was an orphan E300
        r = self.row(9)
        self.assertEqual((r["pass"], r["payload_source"], r["header_prepended"], r["lint_errors"]),
                         (True, "fence", True, 0))

    def test_unregistered_modifier_on_a_single_operation_is_e302(self):
        r = self.row(10)
        self.assertFalse(r["pass"])
        self.assertEqual((r["must_contain_failed"], r["must_not_contain_hit"], r["lint_error_codes"]), ([], [], ["E302"]))

    def test_bareword_target_on_a_single_operation_is_e300(self):
        r = self.row(11)
        self.assertFalse(r["pass"])
        self.assertEqual((r["must_contain_failed"], r["lint_error_codes"]), ([], ["E300"]))

    def test_multi_line_chain_after_its_own_header_passes(self):
        r = self.row(12)
        self.assertEqual((r["pass"], r["header_prepended"], r["lint_errors"]), (True, False, 0))

    def test_lint_files_are_removed_from_the_work_dir(self):
        self.assertEqual(list(self.work.iterdir()), [])

    def test_track_counts(self):
        self.assertEqual((self.result["n"], self.result["pass_count"], self.result["pass_rate"],
                          self.result["error_count"]), (12, 5, 0.4167, 1))


if __name__ == "__main__":
    unittest.main()
