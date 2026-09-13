#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ilang-conformance scorer (@SCORER).

Implements book §5.0 (reply extraction), §5.1 (track pipelines), §5.3
(scoreboard) and §5.4 (canonical serialization) as fixed in cases/SCHEMA.md
§3 (extraction), §6 (judge scoring), §7 (grammar lint invocation) and §8
(scoring, serialization, run layout, preconditions, report outputs).

Usage:
  python3 score.py --latest --vendor NAME
  python3 score.py RUN_DIR [--vendor NAME]

Options:
  --latest        score the run directory under --runs whose name matches
                  <vendor>-<yyyymmdd-HHMMSS>, has vendor NAME, contains DONE and
                  is greatest in string order (book §5.4, SCHEMA §8.5); refused with
                  exit 3, naming its run.log, while a newer run of that vendor has
                  no DONE (book §8 third command)
  --vendor NAME   with --latest: the vendor to select; with RUN_DIR: the run
                  directory name must carry this vendor
  --runs DIR      directory holding run directories (default: <repo>/runs)
  --cases DIR     corpus root (default: <repo>/cases)
  --report DIR    report root (default: <repo>/report)

Outputs (SCHEMA §6.4, §8.10): RUN/judge/eval.jsonl when the judge track is
present; REPORT/<run>/score.json (canonical bytes, SCHEMA §8.4);
REPORT/<run>/MANIFEST.sha256 (byte copy); REPORT/SCOREBOARD.md (regenerated).
Nothing is written to REPORT when scoring is refused.

Exit status:
  0  scored
  1  refused: a SCHEMA §8.9 precondition failed, the run or corpus is malformed,
     or a validator's output broke SCHEMA §6.5 or §7
  2  usage error
  3  the run is not finished: no DONE (the message names RUN/run.log); with --latest
     also when the vendor's newest run has no DONE

The vendored validators are used read-only (book §9 no_validator_fork): the
grammar validator through its --lint --json CLI, the judge validator through
imported functions and its --eval CLI. checker_exec.py is used through check().
Responses are untrusted text: parsed, never executed. Stdlib only.
"""

import argparse
import copy
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.dont_write_bytecode = True          # never leave __pycache__ inside vendor/

REPO = Path(__file__).resolve().parent
TRACKS = ("grammar", "exec", "judge")
FORMAT = "ilang-conformance-score/1"

# SCHEMA §0.5
RULE_ORDER = ["R1", "R2", "R3", "R4", "R7", "R8", "R9", "R10", "R11"]
STYLE_ORDER = ["S1", "S2"]
EXEC_OUTCOMES = ("pass", "fail_violation", "fail_missing", "degraded")
EXEC_COPY = ("outcome", "declaration_count", "effective_declaration_count",
             "violations", "expect_failed", "style_flags")

# book §5.3 RUBRIC r2 and FACT l1_claim_thresholds (conf:confirmed since v1.2)
W_GRAMMAR, W_EXEC, W_JUDGE = 0.35, 0.35, 0.30
R2_THRESHOLD = 0.85
L1_GRAMMAR, L1_EXEC, L1_JUDGE_SCHEMA, L1_JCS = 0.95, 0.90, 0.99, 0.80

SCOREBOARD_COLUMNS = ["vendor", "model", "date", "grammar", "exec", "judge_jcs",
                      "judge_schema", "weighted_total", "L1", "degraded_count",
                      "error_count", "run", "manifest_sha256"]

# ---------------------------------------------------------------- SCHEMA regexes
# Owned by score.py (SCHEMA §0.3); each pattern is byte-identical with its block.
ILANG_LINE = re.compile(r"^(?:::|\[[A-ZΣΔφ∇λ∂μψξζθΩΠ]|=>|T\[)")
FENCE_DELIM = re.compile(r"^\s*`{3}")
FENCE_INFO = re.compile(r"^\s*`{3,}\s*([^\s`]*)")
EVAL_SUMMARY_LINE = re.compile(r"^n=([0-9]+) schema_rate=([0-9]+\.[0-9]{4}) mode_acc=([0-9]+\.[0-9]{4}) MAE=([0-9]+\.[0-9]{4}) vector_score=([0-9]+\.[0-9]{4}) boundary_acc=([0-9]+\.[0-9]{4}) \(boundary n=([0-9]+)\)$", re.MULTILINE)
EVAL_JCS_LINE = re.compile(r"^JCS=([0-9]+\.[0-9]{4})  L2_pass=(?:YES|NO)$", re.MULTILINE)
RUN_DIR_NAME = re.compile(r"(.+)-([0-9]{8}-[0-9]{6})")
MANIFEST_LINE = re.compile(r"([0-9a-f]{64})  ((?:grammar|exec|judge)/(?:grammar|exec|judge)-[0-9]{4}\.json)")
PIN_COMMIT = re.compile(r"commit ([0-9a-f]{40})")

# SCHEMA §3.5 text block LINT_HEADER
LINT_HEADER = "::ILANG::v4.0"

# Harness line written directly after the document header of every lint file (proposed SCHEMA §3.5
# amendment; book deviation of 前置一行 ::ILANG::v4.0). Without it the payload's first line sits in
# the validator's §1.7 preamble position (grammar.py:228-230, 241), where a `[VERB:@X|...]` line
# without `]=>` is skipped as a metadata tag (grammar.py:258-262): its modifiers and target go
# unchecked and following `=>` lines become orphan E300. `T[0]` is a temporal note
# (grammar.py:111, 270-272) that ends the preamble and produces no finding.
LINT_PREAMBLE_BREAK = "T[0]"


class Refusal(Exception):
    """Scoring refused; message for stderr, exit code for the process."""

    def __init__(self, message, code=1):
        super().__init__(message)
        self.code = code


# ---------------------------------------------------------------- basics
def canon(obj):
    """SCHEMA §0.5 canon(obj) (book §5.4)."""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"


def lines(t):
    """SCHEMA §0.2 line model."""
    return t.splitlines()


def strip(s):
    return s.strip()


def sha256_hex(data):
    return hashlib.sha256(data).hexdigest()


def show(path):
    """A path for messages: relative to the repository when inside it, POSIX slashes."""
    p = Path(os.path.abspath(path))
    try:
        return p.relative_to(REPO).as_posix()
    except ValueError:
        return p.as_posix()


def read_bytes(path, what):
    try:
        return Path(path).read_bytes()
    except OSError as e:
        raise Refusal("cannot read %s %s: %s" % (what, show(path), e.strerror or e))


def decode_utf8(data, what):
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as e:
        raise Refusal("%s is not strict UTF-8: %s" % (what, e))


def child_env():
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def is_int(x):
    return isinstance(x, int) and not isinstance(x, bool)


def is_number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def atomic_write(path, data):
    path = Path(path)
    fd, tmp = tempfile.mkstemp(prefix="." + path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp, str(path))
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


_MODULES = {}


def vendor_module(name):
    """Import a vendored validator or checker_exec read-only (SCHEMA §6.1)."""
    if name not in _MODULES:
        for p in (str(REPO), str(REPO / "vendor")):
            if p not in sys.path:
                sys.path.insert(0, p)
        try:
            _MODULES[name] = __import__(name)
        except Exception as e:                      # noqa: BLE001 - any import failure refuses
            raise Refusal("cannot import %s: %s: %s" % (name, type(e).__name__, e))
    return _MODULES[name]


# ---------------------------------------------------------------- SCHEMA §3.2-§3.6 grammar extraction
def fences(L):
    """SCHEMA §3.2: (info, body lines) for every backtick fence; an unterminated fence runs to the end."""
    out, i, n = [], 0, len(L)
    while i < n:
        if FENCE_DELIM.match(L[i]):
            info = FENCE_INFO.match(L[i]).group(1).lower()
            j = i + 1
            while j < n and not FENCE_DELIM.match(L[j]):
                j += 1
            out.append((info, L[i + 1:j]))
            i = j + 1
        else:
            i += 1
    return out


def is_ilang_fence(info, body):
    """SCHEMA §3.3."""
    if info in ("ilang", "i-lang"):
        return True
    if info == "":
        first = next((strip(x) for x in body if strip(x)), "")
        return bool(first) and bool(ILANG_LINE.match(first))
    return False


def grammar_payload(text):
    """SCHEMA §3.4: (payload_source, payload_lines)."""
    L = lines(text)
    chosen = None
    for info, body in fences(L):
        if is_ilang_fence(info, body) and any(strip(x) for x in body):
            chosen = body                               # keeps the last non-empty I-Lang fence
    if chosen is not None:
        return "fence", chosen
    segments, cur = [], []
    for x in L:                                         # every line, fence lines included
        if ILANG_LINE.match(strip(x)):
            cur.append(x)
        else:
            if cur:
                segments.append(cur)
            cur = []
    if cur:
        segments.append(cur)
    if segments:
        return "bare", segments[-1]
    return "none", []


def lint_input(payload_lines):
    """SCHEMA §3.5: (header_prepended, lint file bytes) for a non-empty payload.

    The header test is SCHEMA §3.5's. The lint file is the payload with LINT_HEADER and
    LINT_PREAMBLE_BREAK in front when the payload has no header of its own, and otherwise the
    payload with LINT_PREAMBLE_BREAK inserted right after its own header line, so no payload line
    is ever read as preamble metadata."""
    payload_lines = list(payload_lines)
    k = next((i for i, x in enumerate(payload_lines) if strip(x)), None)
    first = strip(payload_lines[k]) if k is not None else ""
    header_prepended = not first.startswith("::ILANG::")
    if header_prepended:
        out = [LINT_HEADER, LINT_PREAMBLE_BREAK] + payload_lines
    else:
        out = payload_lines[:k + 1] + [LINT_PREAMBLE_BREAK] + payload_lines[k + 1:]
    return header_prepended, ("\n".join(out) + "\n").encode("utf-8", "replace")


def grammar_assertions(expect, payload):
    """SCHEMA §3.6: (must_contain_failed, must_not_contain_hit)."""
    failed = []
    for k, element in enumerate(expect["must_contain"]):
        members = element if isinstance(element, list) else [element]
        if not any(m in payload for m in members):
            failed.append(k)
    hit = [s for s in expect["must_not_contain"] if s in payload]
    return failed, hit


# ---------------------------------------------------------------- SCHEMA §7 lint invocation
def run_lint(items, work_dir):
    """items: [(case id, lint bytes)] in ascending id order -> {id: (errors, warnings, codes)}.

    The lint files live in a temporary directory inside work_dir (the run directory when scoring),
    never in the system temp directory: book §8 RULE u24_is_shared limits this project's files on
    @U24 to /root/ilang-conformance and the env file (proposed SCHEMA §7 amendment)."""
    if not items:
        return {}
    with tempfile.TemporaryDirectory(prefix=".score-lint-", dir=str(work_dir)) as tmp:
        paths = []
        for cid, data in items:
            path = os.path.join(tmp, cid + ".ilang")
            with open(path, "wb") as fh:
                fh.write(data)
            paths.append(path)
        try:
            proc = subprocess.run(
                [sys.executable, "vendor/ilang_grammar_validator.py", "--lint", *paths, "--json"],
                cwd=str(REPO), env=child_env(), stdin=subprocess.DEVNULL, capture_output=True)
        except OSError as e:
            raise Refusal("cannot run the grammar validator: %s" % e)
    where = "grammar validator --lint --json"
    if proc.returncode not in (0, 1):
        raise Refusal("%s exited %d (SCHEMA §7 accepts 0 or 1): %s"
                      % (where, proc.returncode, proc.stderr.decode("utf-8", "replace").strip()[-400:]))
    try:
        doc = json.loads(decode_utf8(proc.stdout, where + " stdout"))
    except ValueError as e:
        raise Refusal("%s stdout is not one JSON document: %s" % (where, e))
    files = doc.get("files") if isinstance(doc, dict) else None
    if not isinstance(files, list) or len(files) != len(paths):
        raise Refusal("%s reported %s files for %d paths (SCHEMA §7)"
                      % (where, len(files) if isinstance(files, list) else "no", len(paths)))
    out = {}
    for (cid, _), f in zip(items, files):
        if not isinstance(f, dict) or f.get("mode") != "raw":
            raise Refusal("%s: lint file of %s is in mode %r, not raw (SCHEMA §7, book §5.0 grammar封装)"
                          % (where, cid, f.get("mode") if isinstance(f, dict) else None))
        errors, warnings, findings = f.get("errors"), f.get("warnings"), f.get("findings")
        if not is_int(errors) or not is_int(warnings) or not isinstance(findings, list) or \
                not all(isinstance(x, dict) and isinstance(x.get("code"), str) for x in findings):
            raise Refusal("%s: malformed file entry for %s" % (where, cid))
        codes = sorted({x["code"] for x in findings if x.get("level") == "ERROR"})
        out[cid] = (errors, warnings, codes)
    return out


# ---------------------------------------------------------------- SCHEMA §6 judge
def judge_extract(jv, text):
    """SCHEMA §6.2: (block_count, schema_valid, vector, mode)."""
    blocks = jv.extract_blocks(text)
    block_count = len(blocks)
    schema_valid, vec, mode = False, None, None
    if blocks:
        block, nxt = blocks[-1]                         # last ::JUDGE{v5.0} header wins
        try:
            vec, mode, _conf, _reason = jv.parse_judge_block(block)
            parsed = True
        except ValueError:
            parsed = False
        extra = bool(jv.EXTRA_FIELD.match(nxt.strip())) and not nxt.strip().startswith("::")
        schema_valid = parsed and not extra
    return block_count, schema_valid, vec, mode


def run_eval(eval_path, n_rows):
    """SCHEMA §6.5: invoke --eval and parse its two summary lines."""
    p = Path(os.path.abspath(eval_path))
    try:
        arg = p.relative_to(REPO).as_posix()
    except ValueError:
        arg = str(p)
    try:
        proc = subprocess.run(
            [sys.executable, "vendor/ilang_judge_validator.py", "--eval", arg],
            cwd=str(REPO), env=child_env(), stdin=subprocess.DEVNULL, capture_output=True)
    except OSError as e:
        raise Refusal("cannot run the judge validator: %s" % e)
    where = "judge validator --eval"
    out = decode_utf8(proc.stdout, where + " stdout").replace("\r\n", "\n")
    summary = EVAL_SUMMARY_LINE.findall(out)
    jcs = EVAL_JCS_LINE.findall(out)
    if len(summary) != 1 or len(jcs) != 1:
        raise Refusal("%s output broke SCHEMA §6.5 (%d summary lines, %d JCS lines; exit %d): %s"
                      % (where, len(summary), len(jcs), proc.returncode,
                         (out + proc.stderr.decode("utf-8", "replace")).strip()[-400:]))
    n, schema_rate, mode_acc, mae, vector_score, boundary_acc, boundary_n = summary[0]
    if int(n) != n_rows:
        raise Refusal("%s reported n=%s for %d eval rows (SCHEMA §6.5)" % (where, n, n_rows))
    return {
        "jcs": round(float(jcs[0]), 4),
        "schema_rate": round(float(schema_rate), 4),
        "mode_acc": round(float(mode_acc), 4),
        "mae": round(float(mae), 4),
        "vector_score": round(float(vector_score), 4),
        "boundary_acc": round(float(boundary_acc), 4),
        "boundary_n": int(boundary_n),
    }


# ---------------------------------------------------------------- corpus (SCHEMA §1.1)
def load_corpus(cases_dir, track):
    """Records of one track in ascending id order, with the minimal shape score.py relies on."""
    d = Path(cases_dir) / track
    files = sorted((p for p in d.iterdir() if p.is_file() and p.name.endswith(".jsonl")),
                   key=lambda p: p.name) if d.is_dir() else []
    records = {}
    for f in files:
        text = decode_utf8(read_bytes(f, "corpus file"), "corpus file " + show(f))
        for k, ln in enumerate(lines(text), 1):
            where = "%s line %d" % (show(f), k)
            try:
                rec = json.loads(ln)
            except ValueError:
                rec = None
            if not isinstance(rec, dict):
                raise Refusal("%s is not a JSON object (run validate_cases.py)" % where)
            cid = rec.get("id")
            if not isinstance(cid, str) or rec.get("track") != track:
                raise Refusal("%s: id or track is wrong for track %s (run validate_cases.py)" % (where, track))
            if cid in records:
                raise Refusal("%s: duplicate corpus id %s (run validate_cases.py)" % (where, cid))
            check_case_shape(track, rec, where)
            records[cid] = rec
    if not records:
        raise Refusal("the %s corpus under %s is empty, but the run has %s records"
                      % (track, show(d), track))
    return [records[cid] for cid in sorted(records)]


def check_case_shape(track, rec, where):
    bad = False
    if track == "grammar":
        ex = rec.get("expect")
        bad = not (isinstance(ex, dict) and is_int(ex.get("lint_errors"))
                   and isinstance(ex.get("must_contain"), list)
                   and all(isinstance(e, str) or (isinstance(e, list) and all(isinstance(m, str) for m in e))
                           for e in ex["must_contain"])
                   and isinstance(ex.get("must_not_contain"), list)
                   and all(isinstance(e, str) for e in ex["must_not_contain"]))
    elif track == "exec":
        bad = not isinstance(rec.get("expect"), dict)
    elif track == "judge":
        jv = vendor_module("ilang_judge_validator")
        g = rec.get("gold_v")
        bad = not (isinstance(g, dict) and all(is_number(g.get(d)) for d in jv.DIMS)
                   and isinstance(rec.get("boundary"), bool))
    if bad:
        raise Refusal("%s: %s record %s lacks the fields score.py reads (run validate_cases.py)"
                      % (where, track, rec.get("id")))


# ---------------------------------------------------------------- run directory (SCHEMA §8.5-§8.9)
def spec_pin(pin_text):
    """SCHEMA §8.3/§8.9: the 40-hex commit of the one PIN line that fully matches PIN_COMMIT."""
    found = [m.group(1) for m in (PIN_COMMIT.fullmatch(x) for x in lines(pin_text)) if m]
    if len(found) != 1:
        raise Refusal("vendor/PIN has %d lines matching PIN_COMMIT, needs exactly 1 (SCHEMA §8.9)" % len(found))
    return found[0]


def parse_manifest(text):
    """SCHEMA §8.8: [(sha256, path)] in file order."""
    entries = []
    for k, ln in enumerate(lines(text), 1):
        m = MANIFEST_LINE.fullmatch(ln)
        if not m:
            raise Refusal("MANIFEST.sha256 line %d fails MANIFEST_LINE (SCHEMA §8.9): %r" % (k, ln[:120]))
        digest, rel = m.group(1), m.group(2)
        folder, name = rel.split("/")
        if not name.startswith(folder + "-"):
            raise Refusal("MANIFEST.sha256 line %d: directory of %s differs from its id prefix (SCHEMA §8.8)"
                          % (k, rel))
        entries.append((digest, rel))
    if not entries:
        raise Refusal("MANIFEST.sha256 lists no raw records")
    return entries


def is_record_name(track, name):
    """<track>-NNNN.json with four ASCII digits (SCHEMA §8.9 unlisted-file check)."""
    prefix = track + "-"
    digits = name[len(prefix):-len(".json")] if name.startswith(prefix) and name.endswith(".json") else ""
    return len(digits) == 4 and all(c in "0123456789" for c in digits)


def select_latest(runs_dir, vendor):
    """book §5.4 / SCHEMA §8.5 --latest."""
    runs_dir = Path(runs_dir)
    if not runs_dir.is_dir():
        raise Refusal("runs directory %s does not exist" % show(runs_dir))
    named = sorted(c.name for c in runs_dir.iterdir()
                   if c.is_dir() and RUN_DIR_NAME.fullmatch(c.name)
                   and RUN_DIR_NAME.fullmatch(c.name).group(1) == vendor)
    if not named:
        raise Refusal("no run directory for vendor %s under %s" % (vendor, show(runs_dir)))
    done = [n for n in named if (runs_dir / n / "DONE").is_file()]
    if not done:
        raise Refusal("no finished run for vendor %s: %s has no DONE yet; see %s"
                      % (vendor, show(runs_dir / named[-1]), show(runs_dir / named[-1] / "run.log")), 3)
    chosen = done[-1]
    newer = [n for n in named if n > chosen]
    if newer:
        # book §8: while the run is unfinished the third command reports an error and names the log.
        # Scoring the older finished run here would let an operator take its score for the new run.
        raise Refusal("newest run %s of vendor %s has no DONE yet; see %s. Wait for DONE, or score the "
                      "older finished run explicitly: python3 score.py %s"
                      % (show(runs_dir / newer[-1]), vendor, show(runs_dir / newer[-1] / "run.log"),
                         show(runs_dir / chosen)), 3)
    return runs_dir / chosen


def parse_record(rel, data):
    """The raw record fields score.py reads (SCHEMA §8.6): status, text, request.vendor, request.model."""
    try:
        rec = json.loads(decode_utf8(data, "raw record " + rel))
    except ValueError:
        rec = None
    if not isinstance(rec, dict):
        raise Refusal("raw record %s is not a JSON object (SCHEMA §8.6)" % rel)
    status = rec.get("status")
    if not isinstance(status, str) or status not in ("ok", "error"):
        raise Refusal("raw record %s: status must be \"ok\" or \"error\" (SCHEMA §8.6)" % rel)
    if status == "ok" and not isinstance(rec.get("text"), str):
        raise Refusal("raw record %s: status ok without a string text (SCHEMA §8.6)" % rel)
    req = rec.get("request")
    if not isinstance(req, dict) or not isinstance(req.get("vendor"), str) or not isinstance(req.get("model"), str):
        raise Refusal("raw record %s: request.vendor and request.model must be strings (SCHEMA §8.6)" % rel)
    return {"status": status, "text": rec["text"] if status == "ok" else None,
            "vendor": req["vendor"], "model": req["model"]}


# ---------------------------------------------------------------- tracks (SCHEMA §8.1)
def score_grammar(cases, recs, work_dir):
    """SCHEMA §8.1 grammar track; lint files are written under work_dir (see run_lint)."""
    rows, lint_items = [], []
    for case in cases:
        cid, rec = case["id"], recs[case["id"]]
        if rec["status"] != "ok":
            rows.append({"id": cid, "status": rec["status"], "payload_source": "none",
                         "payload_nonempty": False, "header_prepended": False, "lint_errors": None,
                         "lint_warnings": None, "lint_error_codes": [], "must_contain_failed": [],
                         "must_not_contain_hit": [], "pass": False})
            continue
        source, payload_lines = grammar_payload(rec["text"])
        payload = "\n".join(payload_lines)
        nonempty = any(strip(x) for x in payload_lines)
        header_prepended = False
        if nonempty:                                    # an empty payload is never linted (SCHEMA §3.4)
            header_prepended, data = lint_input(payload_lines)
            lint_items.append((cid, data))
        failed, hit = grammar_assertions(case["expect"], payload)
        rows.append({"id": cid, "status": "ok", "payload_source": source, "payload_nonempty": nonempty,
                     "header_prepended": header_prepended, "lint_errors": None, "lint_warnings": None,
                     "lint_error_codes": [], "must_contain_failed": failed, "must_not_contain_hit": hit,
                     "pass": False})
    lint = run_lint(lint_items, work_dir)
    by_id = {c["id"]: c for c in cases}
    for row in rows:
        if row["id"] in lint:
            row["lint_errors"], row["lint_warnings"], row["lint_error_codes"] = lint[row["id"]]
        row["pass"] = (row["status"] == "ok" and row["payload_nonempty"]
                       and row["lint_errors"] == by_id[row["id"]]["expect"]["lint_errors"]
                       and row["must_contain_failed"] == [] and row["must_not_contain_hit"] == [])
    n = len(rows)
    passed = sum(r["pass"] for r in rows)
    return {"n": n, "pass_count": passed, "pass_rate": round(passed / n, 4),
            "error_count": sum(r["status"] != "ok" for r in rows), "cases": rows}


def score_exec(cases, recs):
    ce = None
    rows = []
    rule_counts = {r: 0 for r in RULE_ORDER}
    style_counts = {s: 0 for s in STYLE_ORDER}
    for case in cases:
        cid, rec = case["id"], recs[case["id"]]
        if rec["status"] != "ok":                      # never passed to the checker (SCHEMA §4.3)
            rows.append({"id": cid, "status": rec["status"], "outcome": "error", "declaration_count": 0,
                         "effective_declaration_count": 0, "violations": [], "expect_failed": [],
                         "style_flags": [], "pass": False})
            continue
        if ce is None:
            ce = vendor_module("checker_exec")
        res = ce.check(copy.deepcopy(case), rec["text"])
        if not isinstance(res, dict) or any(k not in res for k in EXEC_COPY) or \
                res["outcome"] not in EXEC_OUTCOMES or \
                not all(is_int(res[k]) for k in ("declaration_count", "effective_declaration_count")) or \
                not set(res["violations"]) <= set(RULE_ORDER) or not set(res["style_flags"]) <= set(STYLE_ORDER):
            raise Refusal("checker_exec.check returned a result outside SCHEMA §5.5 for %s" % cid)
        row = {"id": cid, "status": "ok"}
        for k in EXEC_COPY:
            row[k] = list(res[k]) if isinstance(res[k], list) else res[k]
        row["pass"] = res["outcome"] == "pass"
        rows.append(row)
    for row in rows:
        for r in row["violations"]:
            rule_counts[r] += 1
        for s in row["style_flags"]:
            style_counts[s] += 1
    n = len(rows)
    passed = sum(r["pass"] for r in rows)
    return {"n": n, "pass_count": passed, "pass_rate": round(passed / n, 4),
            "degraded_count": sum(r["outcome"] == "degraded" for r in rows),
            "fail_missing_count": sum(r["outcome"] == "fail_missing" for r in rows),
            "fail_violation_count": sum(r["outcome"] == "fail_violation" for r in rows),
            "error_count": sum(r["status"] != "ok" for r in rows),
            "rule_fail_counts": rule_counts, "style_flag_counts": style_counts, "cases": rows}


def score_judge(cases, recs, run_dir):
    jv = vendor_module("ilang_judge_validator")
    eval_rows, rows = [], []
    for case in cases:
        cid, rec = case["id"], recs[case["id"]]
        if rec["status"] == "ok":
            block_count, schema_valid, vec, mode = judge_extract(jv, rec["text"])
        else:
            block_count, schema_valid, vec, mode = 0, False, None, None
        if schema_valid:
            pred_v, pred_mode = vec, mode
        else:                                           # padding (SCHEMA §6.3, book §5.0 judge填充)
            pred_v, pred_mode = {d: 0.5 for d in jv.DIMS}, "none"
        eval_rows.append({"block_count": block_count, "boundary": case["boundary"], "gold_v": case["gold_v"],
                          "id": cid, "pred_mode": pred_mode, "pred_v": pred_v, "schema_valid": schema_valid})
        gold_mode = jv.f_v5(case["gold_v"])
        rows.append({"id": cid, "status": rec["status"], "block_count": block_count,
                     "schema_valid": schema_valid, "pred_mode": pred_mode, "gold_mode": gold_mode,
                     "mode_hit": pred_mode == gold_mode, "boundary": case["boundary"]})
    eval_path = Path(run_dir) / "judge" / "eval.jsonl"
    atomic_write(eval_path, "".join(canon(r) for r in eval_rows).encode("utf-8"))
    metrics = run_eval(eval_path, len(eval_rows))
    out = {"n": len(rows), "multi_block_count": sum(r["block_count"] > 1 for r in rows),
           "error_count": sum(r["status"] != "ok" for r in rows), "cases": rows}
    out.update(metrics)
    return out


def summarize(tracks):
    """SCHEMA §8.2."""
    g = tracks["grammar"]["pass_rate"] if "grammar" in tracks else None
    e = tracks["exec"]["pass_rate"] if "exec" in tracks else None
    jcs = tracks["judge"]["jcs"] if "judge" in tracks else None
    schema = tracks["judge"]["schema_rate"] if "judge" in tracks else None
    error_count = sum(t["error_count"] for t in tracks.values())
    complete = all(t in tracks for t in TRACKS)
    weighted = round(W_GRAMMAR * g + W_EXEC * e + W_JUDGE * jcs, 4) if complete else None
    l1 = complete and g >= L1_GRAMMAR and e >= L1_EXEC and schema >= L1_JUDGE_SCHEMA \
        and jcs >= L1_JCS and error_count == 0
    return {"grammar_pass_rate": g, "exec_pass_rate": e, "judge_jcs": jcs, "judge_schema": schema,
            "weighted_total": weighted, "weighted_pass": (weighted >= R2_THRESHOLD) if complete else None,
            "degraded_count": tracks["exec"]["degraded_count"] if "exec" in tracks else 0,
            "error_count": error_count, "l1": "L1" if l1 else "below_L1"}


# ---------------------------------------------------------------- scoreboard (SCHEMA §8.10)
def md_cell(value):
    return str(value).replace("|", "\\|").replace("\n", " ")


def rate(x):
    return "-" if x is None else "%.4f" % x


def build_scoreboard(report_dir, run_name, score_obj, manifest_bytes):
    """REPORT/SCOREBOARD.md text with the current run as if already written."""
    report_dir = Path(report_dir)
    candidates = {run_name}
    if report_dir.is_dir():
        for child in report_dir.iterdir():
            if child.is_dir() and RUN_DIR_NAME.fullmatch(child.name) and \
                    (child / "score.json").is_file() and (child / "MANIFEST.sha256").is_file():
                candidates.add(child.name)
    latest = {}
    for name in candidates:
        vendor = RUN_DIR_NAME.fullmatch(name).group(1)
        if vendor not in latest or name > latest[vendor]:
            latest[vendor] = name
    out = ["# ilang-conformance scoreboard", "",
           "| " + " | ".join(SCOREBOARD_COLUMNS) + " |",
           "|" + "---|" * len(SCOREBOARD_COLUMNS)]
    for vendor in sorted(latest):
        name = latest[vendor]
        if name == run_name:
            doc, msha = score_obj, sha256_hex(manifest_bytes)
        else:
            sj = report_dir / name / "score.json"
            try:
                doc = json.loads(decode_utf8(read_bytes(sj, "report file"), show(sj)))
            except ValueError:
                doc = None
            s = doc.get("summary") if isinstance(doc, dict) else None
            if not isinstance(s, dict) or not isinstance(doc.get("model"), str) or \
                    any(k not in s for k in ("grammar_pass_rate", "exec_pass_rate", "judge_jcs", "judge_schema",
                                             "weighted_total", "l1", "degraded_count", "error_count")):
                raise Refusal("%s is not a score.json of this format; cannot rebuild the scoreboard" % show(sj))
            msha = sha256_hex(read_bytes(report_dir / name / "MANIFEST.sha256", "report file"))
        s = doc["summary"]
        ts = RUN_DIR_NAME.fullmatch(name).group(2)
        run_cell = name + (" (incomplete)" if s["error_count"] > 0 else "")
        cells = [md_cell(vendor), md_cell(doc["model"]), "%s-%s-%s" % (ts[0:4], ts[4:6], ts[6:8]),
                 rate(s["grammar_pass_rate"]), rate(s["exec_pass_rate"]), rate(s["judge_jcs"]),
                 rate(s["judge_schema"]), rate(s["weighted_total"]), md_cell(s["l1"]),
                 str(s["degraded_count"]), str(s["error_count"]), md_cell(run_cell), msha]
        out.append("| " + " | ".join(cells) + " |")
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------- driver
def score_run(run_dir, cases_dir, report_dir, vendor=None):
    """Score one run directory; returns (run name, score object, score.json bytes)."""
    run_dir = Path(os.path.abspath(run_dir))
    if not run_dir.is_dir():
        raise Refusal("run directory %s does not exist" % show(run_dir))
    name = run_dir.name
    m = RUN_DIR_NAME.fullmatch(name)
    if not m:
        raise Refusal("run directory name %r does not match <vendor>-<yyyymmdd-HHMMSS> (SCHEMA §8.5)" % name)
    if vendor is not None and m.group(1) != vendor:
        raise Refusal("run directory %s belongs to vendor %s, not %s" % (name, m.group(1), vendor))

    # SCHEMA §8.9 preconditions
    if not (run_dir / "DONE").is_file():
        raise Refusal("run %s is not finished: no DONE; see %s" % (show(run_dir), show(run_dir / "run.log")), 3)
    pin = spec_pin(decode_utf8(read_bytes(REPO / "vendor" / "PIN", "pin file"), "vendor/PIN"))
    manifest_path = run_dir / "MANIFEST.sha256"
    if not manifest_path.is_file():
        raise Refusal("run %s has DONE but no MANIFEST.sha256 (SCHEMA §8.9)" % show(run_dir))
    manifest_bytes = read_bytes(manifest_path, "manifest")
    done_bytes = read_bytes(run_dir / "DONE", "DONE marker")
    if done_bytes != (sha256_hex(manifest_bytes) + "\n").encode("ascii"):
        raise Refusal("DONE of %s does not equal the sha256 of MANIFEST.sha256 (SCHEMA §8.8, §8.9)" % show(run_dir))
    entries = parse_manifest(decode_utf8(manifest_bytes, "MANIFEST.sha256"))
    listed, datas = set(), {}
    for digest, rel in entries:
        path = run_dir / rel
        if not path.is_file():
            raise Refusal("listed record %s is missing (SCHEMA §8.9)" % rel)
        data = read_bytes(path, "raw record")
        if sha256_hex(data) != digest:
            raise Refusal("listed record %s does not match its MANIFEST.sha256 hash (SCHEMA §8.9)" % rel)
        listed.add(rel)
        datas[rel] = data
    for track in TRACKS:
        d = run_dir / track
        if d.is_dir():
            for child in sorted(d.iterdir(), key=lambda p: p.name):
                if child.is_file() and is_record_name(track, child.name) and \
                        track + "/" + child.name not in listed:
                    raise Refusal("record %s/%s is not listed in MANIFEST.sha256 (SCHEMA §8.9)"
                                  % (track, child.name))
    present = [t for t in TRACKS if any(rel.startswith(t + "/") for rel in listed)]
    corpus = {t: load_corpus(cases_dir, t) for t in present}
    records = {rel: parse_record(rel, datas[rel]) for rel in sorted(listed)}
    for t in present:
        for case in corpus[t]:
            if "%s/%s.json" % (t, case["id"]) not in listed:
                raise Refusal("corpus id %s has no listed raw record in %s (SCHEMA §8.1, §8.9)"
                              % (case["id"], show(run_dir)))
    vendors = sorted({r["vendor"] for r in records.values()})
    models = sorted({r["model"] for r in records.values()})
    if len(vendors) != 1 or len(models) != 1:
        raise Refusal("raw records disagree on request.vendor %s or request.model %s (SCHEMA §8.3)"
                      % (vendors, models))
    if vendors[0] != m.group(1):
        raise Refusal("raw records name vendor %s but the run directory is %s" % (vendors[0], name))

    tracks = {}
    for t in present:
        recs = {c["id"]: records["%s/%s.json" % (t, c["id"])] for c in corpus[t]}
        if t == "grammar":
            tracks[t] = score_grammar(corpus[t], recs, run_dir)
        elif t == "exec":
            tracks[t] = score_exec(corpus[t], recs)
        else:
            tracks[t] = score_judge(corpus[t], recs, run_dir)
    obj = {"format": FORMAT, "spec_pin": pin, "vendor": vendors[0], "model": models[0],
           "summary": summarize(tracks), "tracks": tracks}
    data = canon(obj).encode("utf-8")

    # SCHEMA §8.10 outputs: everything is computed before the first write to REPORT
    board = build_scoreboard(report_dir, name, obj, manifest_bytes)
    out_dir = Path(report_dir) / name
    out_dir.mkdir(parents=True, exist_ok=True)
    atomic_write(out_dir / "score.json", data)
    atomic_write(out_dir / "MANIFEST.sha256", manifest_bytes)
    atomic_write(Path(report_dir) / "SCOREBOARD.md", board.encode("utf-8"))
    return name, obj, data


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    p = argparse.ArgumentParser(description="ilang-conformance scorer (book §5, cases/SCHEMA.md §3, §6-§8)")
    p.add_argument("run_dir", nargs="?", metavar="RUN_DIR", help="run directory to score")
    p.add_argument("--latest", action="store_true", help="score the latest finished run of --vendor")
    p.add_argument("--vendor", metavar="NAME", help="vendor name (vendors.json)")
    p.add_argument("--runs", metavar="DIR", default=str(REPO / "runs"), help="runs root (default: repo/runs)")
    p.add_argument("--cases", metavar="DIR", default=str(REPO / "cases"), help="corpus root (default: repo/cases)")
    p.add_argument("--report", metavar="DIR", default=str(REPO / "report"), help="report root (default: repo/report)")
    a = p.parse_args(argv)
    if a.latest == (a.run_dir is not None):
        p.error("give either RUN_DIR or --latest --vendor NAME")
    if a.latest and not a.vendor:
        p.error("--latest requires --vendor NAME")
    try:
        run_dir = select_latest(a.runs, a.vendor) if a.latest else Path(a.run_dir)
        name, obj, data = score_run(run_dir, a.cases, a.report, a.vendor)
    except Refusal as r:
        print("score.py: refused: %s" % r, file=sys.stderr)
        return r.code
    except OSError as e:
        print("score.py: failed: %s: %s" % (type(e).__name__, e), file=sys.stderr)
        return 1
    s = obj["summary"]
    print("scored %s: vendor=%s model=%s tracks=%s" % (name, obj["vendor"], obj["model"], ",".join(obj["tracks"])))
    print("grammar=%s exec=%s judge_jcs=%s judge_schema=%s weighted_total=%s L1=%s degraded_count=%d error_count=%d"
          % (rate(s["grammar_pass_rate"]), rate(s["exec_pass_rate"]), rate(s["judge_jcs"]),
             rate(s["judge_schema"]), rate(s["weighted_total"]), s["l1"], s["degraded_count"], s["error_count"]))
    print("wrote %s sha256=%s" % (show(Path(a.report) / name / "score.json"), sha256_hex(data)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
