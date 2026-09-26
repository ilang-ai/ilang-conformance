#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Compare arms of the relay-interference study: the same model, the same 320 cases, through different routes.

For each model, one arm is the api.b.ai run of 18-20 September 2026 (report/<run>/score.json and the raw
records) and the others are control runs (OpenRouter pinned to the vendor, the vendor's own endpoint, or another
relay). Everything here is read from the raw records and the score.json files; nothing is judged by a model.

  python controls/compare_arms.py --pairs controls/pairs.json --runs-a DIR [--runs-a DIR ...] --report-a DIR
                                  --report-b DIR --out DIR

pairs.json: {"<model label>": {"arms": {"<arm label>": "<run dir name>", ...}}}; run directories are looked up in
every --runs-a directory and in the repository's runs/; score.json under --report-a for api.b.ai runs and
--report-b for control runs (a run is looked up in both).

Output: <out>/arms.json (canonical) and <out>/ARMS.md with, per model and arm: served model id, records, status ok,
median prompt tokens per track and the ratio against the request we sent, upper-cased replies, refused and filtered
(refusal.py's rules), pass rates per track, and, between the api.b.ai arm and each control arm, the per-case
agreement: same pass/fail on grammar and exec, same mode on judge, and the share of judge vectors identical to the
other arm's.
"""
import argparse
import glob
import json
import os
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO))
import refusal  # noqa: E402

TRACKS = ("grammar", "exec", "judge")


def find_run(name, runs_dirs):
    for d in list(runs_dirs) + [REPO / "runs"]:
        p = Path(d) / name
        if p.is_dir():
            return p
    raise SystemExit("run directory not found: %s" % name)


def find_score(name, report_dirs):
    for d in report_dirs:
        p = Path(d) / name / "score.json"
        if p.is_file():
            return json.load(open(p, encoding="utf-8"))
    return None


def per_case(score):
    out = {}
    if not score:
        return out
    for t in TRACKS:
        for c in (score.get("tracks", {}).get(t, {}).get("cases") or []):
            out[c["id"]] = c
    return out


def judge_vector(text):
    for block, _ in JV.extract_blocks(text or ""):
        try:
            vec, mode, conf, reason = JV.parse_judge_block(block)
            return vec, mode
        except ValueError:
            return None, None
    return None, None


def arm_summary(run_dir, score, cases, systems, user_message):
    recs = refusal.read_run(str(run_dir))
    ana = refusal.analyse(str(run_dir), cases, systems, user_message)
    served = {}
    prompt = {}
    for t in TRACKS:
        pts = []
        for r in recs.get(t, []):
            name = r.get("response_model") or "(no reply)"
            served[name] = served.get(name, 0) + 1
            pt = refusal.prompt_tokens(r)
            if r.get("status") == "ok" and pt:
                pts.append(pt)
        if pts:
            prompt[t] = int(statistics.median(pts))
    summ = score.get("summary", {}) if score else {}
    return {
        "run": run_dir.name, "served_model": served, "records": ana["totals"]["records"], "ok": ana["totals"]["ok"],
        "median_prompt_tokens": prompt, "prompt_ratio": {t: v["ratio"] for t, v in ana["prompt_size"].items()},
        "upper_cased": {t: v["upper"] for t, v in ana["casing"].items()},
        "refused": ana["totals"]["refused"], "filtered": ana["totals"]["filtered"], "empty": ana["totals"]["empty"],
        "errors": ana["totals"]["error"],
        "scores": {k: summ.get(k) for k in ("grammar_pass_rate", "exec_pass_rate", "judge_jcs", "judge_schema", "weighted_total")},
    }, recs


def agreement(recs_a, score_a, recs_b, score_b):
    ca, cb = per_case(score_a), per_case(score_b)
    out = {}
    for t in ("grammar", "exec"):
        ids = [i for i in ca if i.startswith(t) and i in cb]
        same = sum(1 for i in ids if bool(ca[i].get("pass")) == bool(cb[i].get("pass")))
        out[t] = {"n": len(ids), "same_pass_fail": same, "a_pass": sum(1 for i in ids if ca[i].get("pass")),
                  "b_pass": sum(1 for i in ids if cb[i].get("pass"))}
    ids = [i for i in ca if i.startswith("judge") and i in cb]
    same_mode = sum(1 for i in ids if ca[i].get("pred_mode") and ca[i].get("pred_mode") == cb[i].get("pred_mode"))
    ta = {r["id"]: r.get("text") for r in recs_a.get("judge", [])}
    tb = {r["id"]: r.get("text") for r in recs_b.get("judge", [])}
    same_vec = both = 0
    for i in ids:
        va, ma = judge_vector(ta.get(i))
        vb, mb = judge_vector(tb.get(i))
        if va and vb:
            both += 1
            same_vec += va == vb
    out["judge"] = {"n": len(ids), "same_mode": same_mode, "both_parsed": both, "same_vector": same_vec}
    return out


def dumps(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--pairs", required=True)
    p.add_argument("--runs-a", action="append", default=[])
    p.add_argument("--report-a", default=str(REPO / "report"))
    p.add_argument("--report-b", required=True)
    p.add_argument("--out", required=True)
    a = p.parse_args(argv)
    global JV
    import importlib.util
    spec = importlib.util.spec_from_file_location("jv", str(REPO / "vendor" / "ilang_judge_validator.py"))
    JV = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(JV)
    pairs = json.load(open(a.pairs, encoding="utf-8"))
    cases = refusal.load_cases(str(REPO / "cases"))
    systems, user_message = refusal.request_texts()
    reports = [a.report_a, a.report_b]
    result = {}
    lines = ["# Arms compared", "", "Same model, same 320 cases, different routes. Prompt ratio: median prompt tokens "
             "against the characters we sent over %.1f (see refusal.py). Agreement is per case between the api.b.ai arm "
             "and each control arm." % refusal.CHARS_PER_TOKEN, ""]
    for model, spec_ in pairs.items():
        arms = {}
        recs = {}
        for label, run_name in spec_["arms"].items():
            rd = find_run(run_name, a.runs_a)
            score = find_score(run_name, reports)
            arms[label], recs[label] = arm_summary(rd, score, cases, systems, user_message)
            arms[label]["score"] = score
        base = next((l for l in arms if l == "api.b.ai"), next(iter(arms)))
        agree = {}
        for label in arms:
            if label != base:
                agree[label] = agreement(recs[base], arms[base]["score"], recs[label], arms[label]["score"])
        for v in arms.values():
            v.pop("score", None)
        result[model] = {"arms": arms, "agreement_vs_" + base: agree}
        lines += ["## %s" % model, "", "| arm | run | served as | ok/records | prompt tokens g/e/j | ratio g/e/j | upper-cased g/e/j | refused | filtered | empty | grammar | exec | JCS | schema | weighted |",
                  "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for label, v in arms.items():
            s = v["scores"]
            f = lambda x: "-" if x is None else ("%.4f" % x)
            lines.append("| %s | %s | %s | %d/%d | %s | %s | %s | %d | %d | %d | %s | %s | %s | %s | %s |" % (
                label, v["run"], ", ".join("%s×%d" % (k, n) for k, n in v["served_model"].items()), v["ok"], v["records"],
                "/".join(str(v["median_prompt_tokens"].get(t, "-")) for t in TRACKS),
                "/".join(str(v["prompt_ratio"].get(t, "-")) for t in TRACKS),
                "/".join(str(v["upper_cased"].get(t, "-")) for t in TRACKS),
                v["refused"], v["filtered"], v["empty"], f(s["grammar_pass_rate"]), f(s["exec_pass_rate"]), f(s["judge_jcs"]),
                f(s["judge_schema"]), f(s["weighted_total"])))
        if agree:
            lines += ["", "| control arm | grammar same pass/fail | exec same pass/fail | judge same mode | judge same vector |", "|---|---|---|---|---|"]
            for label, g in agree.items():
                lines.append("| %s | %d/%d (a %d, b %d pass) | %d/%d (a %d, b %d pass) | %d/%d | %d/%d parsed |" % (
                    label, g["grammar"]["same_pass_fail"], g["grammar"]["n"], g["grammar"]["a_pass"], g["grammar"]["b_pass"],
                    g["exec"]["same_pass_fail"], g["exec"]["n"], g["exec"]["a_pass"], g["exec"]["b_pass"],
                    g["judge"]["same_mode"], g["judge"]["n"], g["judge"]["same_vector"], g["judge"]["both_parsed"]))
        lines.append("")
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "arms.json").write_text(dumps(result), encoding="utf-8", newline="\n")
    (out / "ARMS.md").write_text("\n".join(lines), encoding="utf-8", newline="\n")
    print("wrote", out / "ARMS.md", "models", len(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
