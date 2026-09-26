#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Put the control runs on the public board (2026-09-25, his call: 「加进记分板」).

score.py regenerates REPORT/SCOREBOARD.md whenever it scores into REPORT, and the public board is written by hand,
so the control runs are scored into a side directory and this script copies what belongs in the repository:

  python controls/publish_controls.py --from DIR [--research DIR] [--apply]

For every <run>/score.json under --from whose run name starts with a control vendor prefix, it copies score.json,
MANIFEST.sha256 and refusal.json into report/<run>/ (score.json bytes are canonical, so they are identical to what
score.py would have written there), prints the SCOREBOARD rows (ranking-style and evidence-table style), and,
with --research, appends the run's rows to runs.tsv and exec-rule-failures.tsv of the research dataset copy.
Without --apply it only prints what it would do.
"""
import argparse
import glob
import json
import os
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PREFIXES = ("openrouter-", "deepseek-official-", "qwen-official-")
ROUTES = {
    "openrouter-anthropic-": "openrouter.ai, provider pinned to Anthropic",
    "openrouter-": "openrouter.ai",
    "deepseek-official-": "api.deepseek.com (vendor endpoint)",
    "qwen-official-": "maas.qwencloudapi.com (Alibaba Cloud endpoint)",
}
RUNS_COLS = ["run_id", "vendor", "model", "spec_pin", "weighted_total", "l1", "grammar_pass_rate", "exec_pass_rate", "judge_jcs",
             "judge_schema", "judge_mode_acc", "judge_vector_score", "judge_mae", "judge_boundary_acc", "grammar_pass_count",
             "exec_pass_count", "exec_fail_violation", "exec_fail_missing", "error_count", "degraded_count"]
RULES = ["R1", "R2", "R3", "R4", "R7", "R8", "R9", "R10", "R11"]


def route_of(run):
    for p, r in ROUTES.items():
        if run.startswith(p):
            return r
    return "?"


def sha256_file(p):
    import hashlib
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def fmt(x):
    return "%.4f" % x if isinstance(x, (int, float)) else str(x)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="src", required=True)
    ap.add_argument("--research")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)
    rows, evidence, runs_tsv, rules_tsv = [], [], [], []
    for sj in sorted(glob.glob(os.path.join(a.src, "*", "score.json"))):
        run = os.path.basename(os.path.dirname(sj))
        if not run.startswith(PREFIXES):
            continue
        d = json.load(open(sj, encoding="utf-8"))
        s, t = d["summary"], d["tracks"]
        note = "%d of 320 unanswered after four attempts (request timeouts)" % s["error_count"] if s["error_count"] else ""
        src_dir = Path(a.src) / run
        dst = REPO / "report" / run
        if a.apply:
            dst.mkdir(parents=True, exist_ok=True)
            for name in ("score.json", "MANIFEST.sha256", "refusal.json"):
                if (src_dir / name).is_file():
                    shutil.copyfile(src_dir / name, dst / name)
        date = run[-15:-7]
        date = "%s-%s-%s" % (date[0:4], date[4:6], date[6:8])
        rows.append("| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
            d["model"], route_of(run), date, fmt(s["weighted_total"]), fmt(s["grammar_pass_rate"]), fmt(s["exec_pass_rate"]),
            fmt(s["judge_jcs"]), fmt(s["judge_schema"]), s["l1"], note))
        evidence.append("| %s | %s | %s | %d | %s |" % (d["vendor"], d["model"], run, s["error_count"], sha256_file(src_dir / "MANIFEST.sha256")))
        j, e, g = t["judge"], t["exec"], t["grammar"]
        runs_tsv.append("\t".join(str(x) for x in [run, d["vendor"], d["model"], d["spec_pin"], s["weighted_total"], s["l1"], s["grammar_pass_rate"],
                                                   s["exec_pass_rate"], s["judge_jcs"], s["judge_schema"], j["mode_acc"], j["vector_score"], j["mae"],
                                                   j["boundary_acc"], g["pass_count"], e["pass_count"], e["fail_violation_count"], e["fail_missing_count"],
                                                   s["error_count"], s["degraded_count"]]))
        rc = e.get("rule_fail_counts", {})
        rules_tsv.append("\t".join([run, d["model"]] + [str(rc.get(r, 0)) for r in RULES]))
    print("\n".join(rows)); print(); print("\n".join(evidence))
    if a.research:
        for name, lines in (("runs.tsv", runs_tsv), ("exec-rule-failures.tsv", rules_tsv)):
            p = Path(a.research) / name
            have = p.read_text(encoding="utf-8")
            new = [l for l in lines if l.split("\t")[0] not in have]
            print("%s: %d new rows" % (name, len(new)))
            if a.apply and new:
                with open(p, "a", encoding="utf-8", newline="\n") as fh:
                    fh.write("".join(l + "\n" for l in new))
    print("applied" if a.apply else "dry run")
    return 0


if __name__ == "__main__":
    sys.exit(main())
