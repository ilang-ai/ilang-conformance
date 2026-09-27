#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Recompute, from the run records, the figures of the paper that score.py, refusal.py and
controls/compare_arms.py do not print. Standard library only.

  python paper/paper_checks.py --runs DIR [--cases DIR] [--replicate-a FILE --replicate-b FILE]

--runs         directory holding one directory per run (the unpacked records)
--cases        the corpus (default: cases/ of this repository)
--replicate-a  score.json of the run of 18 September (deepseek-v4-flash-free through orcarouter.ai)
--replicate-b  score.json of the run of 24 September (same model, same route, same specification)
"""
import argparse
import collections
import glob
import hashlib
import json
import math
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)
TRACKS = ("grammar", "exec", "judge")
REC = re.compile(r"(grammar|exec|judge)-[0-9]+[.]json$")


def records(run_dir):
    for track in TRACKS:
        for path in sorted(glob.glob(os.path.join(run_dir, track, "*.json"))):
            if REC.search(os.path.basename(path)):
                with open(path, encoding="utf-8") as f:
                    yield track, os.path.basename(path)[:-5], json.load(f)


def corpus(cases_dir):
    out = {}
    for path in sorted(glob.glob(os.path.join(cases_dir, "*", "*.jsonl"))):
        if "fixture" in os.path.basename(path):
            continue
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    case = json.loads(line)
                    out[case["id"]] = case
    return out


def mcnemar(b, c):
    """Exact two-sided McNemar test on the discordant counts."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    return min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n)


def provider(rec):
    body = rec.get("response_body")
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except ValueError:
            return None
    return body.get("provider") if isinstance(body, dict) else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", required=True)
    ap.add_argument("--cases", default=os.path.join(REPO, "cases"))
    ap.add_argument("--replicate-a")
    ap.add_argument("--replicate-b")
    a = ap.parse_args()
    import refusal
    import run as runner

    cases = corpus(a.cases)
    lang = collections.Counter((c["track"], c.get("kind") or "", c["lang"]) for c in cases.values())

    def count(track=None, language=None, kind=None):
        return sum(v for k, v in lang.items()
                   if (track is None or k[0] == track) and (kind is None or k[1] == kind)
                   and (language is None or k[2] == language))

    print("corpus: %d cases; English %d, Chinese %d" % (len(cases), count(language="en"), count(language="zh")))
    for track in TRACKS:
        print("  %s: English %d, Chinese %d" % (track, count(track, "en"), count(track, "zh")))
    print("  judgment scenario cases: English %d, Chinese %d" % (
        count("judge", "en", "scenario_to_vector"), count("judge", "zh", "scenario_to_vector")))

    want = {cid: hashlib.sha256(runner.user_message(c).encode("utf-8")).hexdigest() for cid, c in cases.items()}
    runs = sorted(d for d in os.listdir(a.runs) if os.path.isdir(os.path.join(a.runs, d)))
    total = same_user = 0
    no_temperature = collections.Counter()
    system_hashes = collections.defaultdict(collections.Counter)
    limits = collections.Counter()
    for name in runs:
        for track, cid, rec in records(os.path.join(a.runs, name)):
            total += 1
            rq = rec["request"]
            same_user += rq.get("user_sha256") == want.get(cid)
            if rq.get("temperature") is None:
                no_temperature[name] += 1
            system_hashes[track][rq.get("system_sha256")] += 1
            limits[(rq.get("max_tokens"), rq.get("seed"))] += 1
    print("runs %d, records %d, user-message hash equal to the corpus: %d" % (len(runs), total, same_user))
    print("runs sent without a temperature: %d %s" % (len(no_temperature), sorted(no_temperature)))
    print("output limit and seed: %s" % dict(limits))
    for track in TRACKS:
        print("  records per system-message hash on %s: %s" % (
            track, sorted(system_hashes[track].values(), reverse=True)))

    def one(prefix):
        hits = [r for r in runs if r.startswith(prefix)]
        return os.path.join(a.runs, hits[0]) if hits else None

    haiku = one("relay-claude-haiku-4.5-")
    if haiku:
        report = os.path.join(REPO, "report", os.path.basename(haiku), "refusal.json")
        refused = set()
        if os.path.exists(report):
            with open(report, encoding="utf-8") as f:
                refused = set(json.load(f)["ids"]["refused"])
        named = collections.Counter()
        for track, cid, rec in records(haiku):
            names = [n for n, rx in refusal.FOREIGN if rx.search(rec.get("text") or "")]
            if names:
                named["replies"] += 1
                named["among the refusals"] += cid in refused
                for n in names:
                    named[n] += 1
        print("claude-haiku-4.5 through api.b.ai, replies naming a foreign product: %s" % dict(named))

    fable = one("orca-anthropic-claude-fable-5.1-")
    if fable:
        kinds = collections.Counter()
        for track, cid, rec in records(fable):
            if rec.get("finish_reason") == "content_filter":
                kinds[(track, cases[cid].get("kind") or cases[cid].get("category"))] += 1
        print("claude-fable-5.1 through orcarouter.ai: filtered replies %d, by kind %s" % (
            sum(kinds.values()), dict(kinds)))

    for prefix in ("openrouter-deepseek-deepseek-v4.1-flash-", "openrouter-z-ai-glm-5.3-flash-"):
        d = one(prefix)
        if d:
            hosts = collections.Counter(provider(rec) for _, _, rec in records(d))
            print("%s: %d hosts %s" % (os.path.basename(d), len([h for h in hosts if h]), hosts.most_common()))

    for prefix in ("relay-gpt-5.4-pro-", "openrouter-qwen-qwen3.8-flash-", "qwen-official-qwen3.8-flash-"):
        d = one(prefix)
        if d:
            report = os.path.join(REPO, "report", os.path.basename(d), "refusal.json")
            if os.path.exists(report):
                with open(report, encoding="utf-8") as f:
                    r = json.load(f)
                print("%s: unanswered %d, by cause %s" % (os.path.basename(d), r["totals"]["error"], r["errors"]))

    empties = {}
    for name in runs:
        report = os.path.join(REPO, "report", name, "refusal.json")
        if os.path.exists(report):
            with open(report, encoding="utf-8") as f:
                n = json.load(f)["totals"]["empty"]
            if n:
                empties[name] = n
    print("replies that ended empty at the output limit: %s" % empties)

    if a.replicate_a and a.replicate_b:
        with open(a.replicate_a, encoding="utf-8") as f:
            ra = json.load(f)
        with open(a.replicate_b, encoding="utf-8") as f:
            rb = json.load(f)
        print("replicate: specification pins equal: %s" % (ra.get("spec_pin") == rb.get("spec_pin")))
        for track in ("grammar", "exec"):
            x = {c["id"]: bool(c["pass"]) for c in ra["tracks"][track]["cases"]}
            y = {c["id"]: bool(c["pass"]) for c in rb["tracks"][track]["cases"]}
            only_x = sum(1 for k in x if x[k] and not y[k])
            only_y = sum(1 for k in x if y[k] and not x[k])
            print("  %s: same pass/fail %d of %d; discordant %d and %d; McNemar p = %.2f" % (
                track, sum(1 for k in x if x[k] == y[k]), len(x), only_x, only_y, mcnemar(only_x, only_y)))
        x = {c["id"]: c for c in ra["tracks"]["judge"]["cases"]}
        y = {c["id"]: c for c in rb["tracks"]["judge"]["cases"]}
        only_x = sum(1 for k in x if x[k].get("mode_hit") and not y[k].get("mode_hit"))
        only_y = sum(1 for k in x if y[k].get("mode_hit") and not x[k].get("mode_hit"))
        print("  judge: same mode %d of %d; mode hits discordant %d and %d; McNemar p = %.2f" % (
            sum(1 for k in x if x[k].get("pred_mode") == y[k].get("pred_mode")), len(x), only_x, only_y,
            mcnemar(only_x, only_y)))


if __name__ == "__main__":
    main()
