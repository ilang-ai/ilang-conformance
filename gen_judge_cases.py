#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_judge_cases.py: generate cases/judge/01-vector-to-mode.jsonl (judge-0001 to judge-0060).

Source (book §4.2, cases/SCHEMA.md §1.5 and §9 item 12):

    python3 vendor/ilang_judge_validator.py --sample 60 --balanced --seed 42

Output line k (1-based, sampler order) becomes the record judge-%04d % k: the sampler's `v`
is renamed `gold_v` (keys in DIMS order), `mode` is dropped, `track` is "judge", `lang` is
"en", `kind` is "vector_to_mode", `boundary` is false, and `prompt` is JUDGE_V2M_PROMPT with
"{vector}" replaced by render(gold_v) at %.2f. The gold mode is never stored; it is always
f_v5(gold_v), computed at use (book §4.1).

Record bytes: json.dumps(record, ensure_ascii=False, separators=(",", ":")) plus "\n", keys
in the order of the SCHEMA §1.5 example (id, track, lang, kind, prompt, gold_v, boundary),
UTF-8, LF only.

Usage:
  python3 gen_judge_cases.py           regenerate and write the file
  python3 gen_judge_cases.py --check   regenerate in memory and compare with the file byte for byte

Exit status: 0 written, or identical under --check; 1 file missing or different under --check;
2 the sampler output, the vendored validator or cases/SCHEMA.md breaks an assumption below.

Standard library only. The vendored judge validator is run as a subprocess for the sample and
imported read-only for DIMS and f_v5 (book §9 no_validator_fork). No network, no clock, no
randomness of its own: the same pinned vendor file gives the same bytes.
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent
VENDOR = REPO / "vendor"
SCHEMA = REPO / "cases" / "SCHEMA.md"
OUT = REPO / "cases" / "judge" / "01-vector-to-mode.jsonl"
OUT_REL = "cases/judge/01-vector-to-mode.jsonl"

# SCHEMA §1.6 J7: exact argv, run from the repository root.
SAMPLE_ARGV = ["vendor/ilang_judge_validator.py", "--sample", "60", "--balanced", "--seed", "42"]
N_SAMPLE = 60
SAMPLE_TIMEOUT = 600

# SCHEMA §0.5 (judge.py:29).
DIMS = ["int", "cap", "csq", "rel", "cer", "aut", "rev", "evd", "sov", "ine", "ext"]

# SCHEMA §1.6 J8 (book §4.2: 8/8/8/8/7/7/7/7).
STRATA = {"M1": 8, "M2": 8, "M3": 8, "M4": 8, "M5": 7, "M6": 7, "M7": 7, "M8": 7}

# SCHEMA §1.5 text block JUDGE_V2M_PROMPT, embedded verbatim (§0.4); checked against the
# block on every run.
JUDGE_V2M_PROMPT = (
    "Judgment vector (11 dimensions, fixed order, 2 decimals): {vector}\n"
    "Apply the reference function f_v5 of SPEC-v5.0-PRE.md Part II §3 to this vector. "
    "Copy the vector unchanged onto the V line, put the mode f_v5 returns on the M line, "
    "and give a one-line rationale on the R line."
)

# Read-only import of the vendored validator; no bytecode is written into vendor/.
_saved_dont_write_bytecode = sys.dont_write_bytecode
sys.dont_write_bytecode = True
try:
    if str(VENDOR) not in sys.path:
        sys.path.insert(0, str(VENDOR))
    import ilang_judge_validator as jv  # noqa: E402
finally:
    sys.dont_write_bytecode = _saved_dont_write_bytecode


class GenError(Exception):
    pass


def render(v):
    """SCHEMA §1.5 render(v)."""
    return "[" + ",".join("%s=%.2f" % (d, v[d]) for d in DIMS) + "]"


def schema_text_block(name):
    """Value of the SCHEMA.md text block `name` (§0.4)."""
    try:
        lines = SCHEMA.read_bytes().decode("utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as e:
        raise GenError("cannot read cases/SCHEMA.md: %s" % e)
    opening = "````text name=" + name
    starts = [i for i, ln in enumerate(lines) if ln == opening]
    if len(starts) != 1:
        raise GenError("cases/SCHEMA.md has %d text blocks named %s, expected 1" % (len(starts), name))
    i = starts[0]
    try:
        j = lines.index("````", i + 1)
    except ValueError:
        raise GenError("cases/SCHEMA.md text block %s is not closed" % name)
    return "\n".join(lines[i + 1:j])


def check_constants():
    if list(jv.DIMS) != DIMS:
        raise GenError("vendor DIMS %r differ from SCHEMA §0.5 DIMS" % (jv.DIMS,))
    block = schema_text_block("JUDGE_V2M_PROMPT")
    if block != JUDGE_V2M_PROMPT:
        raise GenError("embedded JUDGE_V2M_PROMPT differs from the cases/SCHEMA.md §1.5 block")


def sample_rows():
    """Run the sampler and return its 60 rows in output order, each checked."""
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    try:
        proc = subprocess.run([sys.executable] + SAMPLE_ARGV, cwd=str(REPO), env=env,
                              capture_output=True, timeout=SAMPLE_TIMEOUT, check=False)
    except (OSError, subprocess.SubprocessError) as e:
        raise GenError("sampler did not run: %s" % e)
    if proc.returncode != 0:
        raise GenError("sampler exited %d" % proc.returncode)
    if proc.stderr:
        raise GenError("sampler wrote to stderr: %r" % proc.stderr[:300])
    try:
        text = proc.stdout.decode("utf-8")
    except UnicodeDecodeError as e:
        raise GenError("sampler stdout is not UTF-8: %s" % e)
    lines = text.splitlines()
    if len(lines) != N_SAMPLE or not all(ln.strip() for ln in lines):
        raise GenError("sampler printed %d lines, expected exactly %d non-empty lines"
                       % (len(lines), N_SAMPLE))
    rows = []
    for k, ln in enumerate(lines, 1):
        try:
            obj = json.loads(ln)
        except ValueError as e:
            raise GenError("sampler line %d is not JSON: %s" % (k, e))
        if not isinstance(obj, dict) or set(obj) != {"v", "mode"}:
            raise GenError("sampler line %d does not have exactly the keys v and mode" % k)
        v = obj["v"]
        if not isinstance(v, dict) or set(v) != set(DIMS):
            raise GenError("sampler line %d: v does not have exactly the 11 DIMS keys" % k)
        for d in DIMS:
            x = v[d]
            if isinstance(x, bool) or not isinstance(x, (int, float)):
                raise GenError("sampler line %d: v.%s is not a number" % (k, d))
            if not 0 <= x <= 1 or round(x, 2) != x:
                raise GenError("sampler line %d: v.%s=%r is outside [0, 1] or not 2dp" % (k, d, x))
        if obj["mode"] != jv.f_v5(v):
            raise GenError("sampler line %d: mode %r differs from f_v5(v)" % (k, obj["mode"]))
        rows.append(obj)
    return rows


def build():
    """Return (file bytes, f_v5 counts per mode)."""
    check_constants()
    rows = sample_rows()
    parts = []
    counts = {m: 0 for m in sorted(STRATA)}
    for k, row in enumerate(rows, 1):
        gold_v = {d: row["v"][d] for d in DIMS}
        record = {
            "id": "judge-%04d" % k,
            "track": "judge",
            "lang": "en",
            "kind": "vector_to_mode",
            "prompt": JUDGE_V2M_PROMPT.replace("{vector}", render(gold_v)),
            "gold_v": gold_v,
            "boundary": False,
        }
        parts.append(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
        mode = jv.f_v5(gold_v)
        if mode not in counts:
            raise GenError("judge-%04d: f_v5 gives %r, outside M1-M8" % (k, mode))
        counts[mode] += 1
    if counts != STRATA:
        raise GenError("f_v5 strata %r differ from %r" % (counts, STRATA))
    return "".join(parts).encode("utf-8"), counts


def first_diff_line(a, b):
    la, lb = a.split(b"\n"), b.split(b"\n")
    for k in range(min(len(la), len(lb))):
        if la[k] != lb[k]:
            return k + 1
    return min(len(la), len(lb)) + 1


def main(argv=None):
    ap = argparse.ArgumentParser(description="Generate the judge vector_to_mode cases "
                                             "judge-0001 to judge-0060.")
    ap.add_argument("--check", action="store_true",
                    help="regenerate in memory and compare with %s byte for byte" % OUT_REL)
    args = ap.parse_args(argv)
    try:
        data, counts = build()
    except GenError as e:
        print("gen_judge_cases.py: error: %s" % e, file=sys.stderr)
        return 2
    digest = hashlib.sha256(data).hexdigest()
    strata = " ".join("%s=%d" % (m, counts[m]) for m in sorted(counts))
    if args.check:
        try:
            current = OUT.read_bytes()
        except OSError as e:
            print("MISMATCH %s: cannot read the file (%s)" % (OUT_REL, e.strerror or e))
            return 1
        if current != data:
            print("MISMATCH %s: differs from the regenerated bytes, first at line %d "
                  "(file sha256 %s, regenerated sha256 %s)"
                  % (OUT_REL, first_diff_line(current, data),
                     hashlib.sha256(current).hexdigest(), digest))
            return 1
        print("OK %s matches the regenerated bytes: %d records, strata %s, sha256 %s"
              % (OUT_REL, N_SAMPLE, strata, digest))
        return 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes(data)
    print("wrote %s: %d records, strata %s, sha256 %s" % (OUT_REL, N_SAMPLE, strata, digest))
    return 0


if __name__ == "__main__":
    sys.exit(main())
