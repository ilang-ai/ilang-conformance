#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Recompute every published result from the run records and compare it with the published file.

  python paper/reproduce_all.py --runs DIR [--out DIR]

For each run directory under --runs that has a report in report/, runs score.py and refusal.py on the records and
compares score.json and refusal.json with the published ones; then runs controls/compare_arms.py and compares the
arm comparison. Standard library only. Writes under --out (default: a temporary directory).

Three outcomes are counted per file:
  identical          the recomputed file equals the published one byte for byte
  identical but for  the two differ only in the fields that depend on the specification vendored in this
  the specification  checkout: spec_pin in score.json, prompt_size in refusal.json (its denominator is the
                     length of the system message, which is built from the vendored specification)
  different          anything else

Release 1.2.0 vendors the specification the runs of September 2026 were made with, and gives "identical" for all
of them. Later releases vendor a later specification and give "identical but for the specification".
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SPEC_FIELDS = {"score.json": ("spec_pin",), "refusal.json": ("prompt_size",)}


def read(path):
    with open(path, "rb") as f:
        return f.read()


def compare(made, published, name):
    a, b = read(made), read(published)
    if a == b:
        return "identical"
    try:
        x, y = json.loads(a.decode("utf-8")), json.loads(b.decode("utf-8"))
    except ValueError:
        return "different"
    for field in SPEC_FIELDS.get(name, ()):
        x.pop(field, None)
        y.pop(field, None)
    return "identical but for the specification" if x == y else "different"


def strip_arms(obj):
    """The arm comparison carries the prompt-size ratio of each arm; set it aside the same way."""
    if isinstance(obj, dict):
        return {k: strip_arms(v) for k, v in obj.items() if "ratio" not in k and k != "prompt_size"}
    if isinstance(obj, list):
        return [strip_arms(v) for v in obj]
    return obj


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", required=True)
    ap.add_argument("--out")
    a = ap.parse_args()
    out = a.out or tempfile.mkdtemp(prefix="reproduce-")
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    with open(os.path.join(REPO, "vendors.json"), encoding="utf-8") as f:
        vendors = json.load(f)
    entries = vendors if isinstance(vendors, list) else vendors.get("vendors", vendors)
    names = set(v["name"] for v in entries) if isinstance(entries, list) else set(entries)
    runs = sorted(d for d in os.listdir(os.path.join(REPO, "report"))
                  if os.path.isdir(os.path.join(REPO, "report", d)))
    counts = {"score.json": {}, "refusal.json": {}}
    problems = []
    absent = []
    for run in runs:
        src = os.path.join(a.runs, run)
        if not os.path.isdir(src):
            absent.append(run)
            continue
        vendor = run.rsplit("-", 2)[0]
        if vendor not in names:
            problems.append((run, "no vendor entry"))
            continue
        for tool, args, name in (("score.py", ["--vendor", vendor], "score.json"), ("refusal.py", [], "refusal.json")):
            target = os.path.join(out, tool[:-3])
            p = subprocess.run([sys.executable, os.path.join(REPO, tool), src] + args + ["--report", target],
                               capture_output=True, text=True, encoding="utf-8", env=env, cwd=REPO)
            made = os.path.join(target, run, name)
            if p.returncode != 0 or not os.path.exists(made):
                problems.append((run, tool + " failed: " + (p.stderr or p.stdout)[-200:]))
                continue
            result = compare(made, os.path.join(REPO, "report", run, name), name)
            counts[name][result] = counts[name].get(result, 0) + 1
            if result == "different":
                problems.append((run, name + " differs from the published file"))
    print("runs with a published report: %d; records found for %d" % (len(runs), len(runs) - len(absent)))
    for name in ("score.json", "refusal.json"):
        for result in ("identical", "identical but for the specification", "different"):
            if counts[name].get(result):
                print("%s %s: %d" % (name, result, counts[name][result]))
    if absent:
        print("no records under --runs for: %s" % ", ".join(absent))

    pairs = os.path.join(REPO, "controls", "pairs-2026-09-26.json")
    if os.path.exists(pairs):
        target = os.path.join(out, "arms")
        os.makedirs(target, exist_ok=True)
        p = subprocess.run([sys.executable, os.path.join(REPO, "controls", "compare_arms.py"), "--pairs", pairs,
                            "--runs-a", a.runs, "--report-a", os.path.join(REPO, "report"),
                            "--report-b", os.path.join(REPO, "report"), "--out", target],
                           capture_output=True, text=True, encoding="utf-8", env=env, cwd=REPO)
        made = os.path.join(target, "arms.json")
        published = os.path.join(REPO, "controls", "arms-2026-09-26.json")
        if p.returncode != 0 or not os.path.exists(made):
            problems.append(("arm comparison", "compare_arms.py failed: " + (p.stderr or p.stdout)[-200:]))
        elif read(made) == read(published):
            print("arm comparison: identical")
        else:
            x, y = json.loads(read(made).decode("utf-8")), json.loads(read(published).decode("utf-8"))
            if strip_arms(x) == strip_arms(y):
                print("arm comparison: identical but for the specification")
            else:
                print("arm comparison: different")
                problems.append(("arm comparison", "arms.json differs from the published file"))
    for run, what in problems:
        print("PROBLEM %s: %s" % (run, what))
    print("written under %s" % out)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
