#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ilang-conformance refusal track (added 2026-09-24).

How often a model refuses or is filtered on the same corpus, and what triggered it. Like the scorer, it is
deterministic code over the raw run records: no model grades another, and the same run always gives the same bytes.
It changes no score; read it beside score.json when a model, a wording or a relay changes.

Usage:
  python3 refusal.py RUN_DIR [RUN_DIR ...]   write REPORT/<run>/refusal.json for each run
  python3 refusal.py --table                 regenerate REPORT/REFUSALS.md from every REPORT/*/refusal.json
  python3 refusal.py --compare BEFORE AFTER  compare two runs of the same corpus, case by case (run names or
                                             paths to their refusal.json)

Options:
  --cases DIR     corpus root (default: <repo>/cases)
  --report DIR    report root (default: <repo>/report)

Each record gets exactly one outcome:
  answered  the reply carries the track's artifact (judge: a ::JUDGE block; grammar, exec: an iLang declaration or
            operation), whatever words surround it
  refused   no artifact, and the reply declines (REFUSE markers)
  filtered  the provider withheld the reply: finish_reason content_filter or another filter value
  empty     no text and no filter, e.g. finish_reason length when reasoning used the whole output budget
  other     text without the artifact that does not decline (prose, leaked reasoning, the wrong format)
  error     no reply at all (status error); its cause is counted apart: relay_billing, rate_limit,
            unavailable, timeout, other
Refused and filtered records get trigger tags and one primary trigger, in this order of precedence:
  relay       the relay changed the request: the run's prompt is far smaller than what we sent (our system message
              was not passed on), or the reply names a product our request never mentions (an identity the relay
              injected)
  identity    identity or role: the reply declines to take one, or the case prompt asks the model to act as someone
  permission  authority or access: the reply says it lacks them, or the case prompt claims or spoofs them
  safety      rules and safety: the reply cites its rules or policies, or the case prompt is on a security topic or
              asks to set rules aside
  system      filtered only: the case prompt carries none of the markers above, and the filter acted on the input
              before any output was written, so what it reacted to includes our system message (the canon and the
              output contract), the same for every case of the track
  unknown     none of these
A refused record is tagged from its reply. A filtered record has no reply to read, so it is tagged from the case
prompt (source=prompt), or from the partial reply when the filter cut one off (source=reply).
Rates: refused and filtered over the records that got a reply (status ok); error over all records.
Two partitions of the records that got a reply show where refusals and filters fall, so a count can be read against
how common its kind of case is: by case group (the corpus's category for exec, kind for grammar and judge) and by
the first prompt marker (identity, permission, safety, or none) found in the case prompt.
Casing: the canon writes modifier and field keys in lower case (path=, state:), so a reply in which at least 90% of
those keys are upper case (three keys or more) is counted as upper-cased, per track; the validators reject every
such reply (E302) whatever it says. A track with half or more of its replies upper-cased is flagged `upper_cased`.
Two api.b.ai runs of Claude models were found this way on 2026-09-25; the same requests through another relay came
back in lower case with the same content, so the casing is the relay's, and such a run measures the relay, not the
model.

Compare: the two runs must cover the same case ids. A case "flips" when its outcome is filtered or refused in one
run and not in the other. McNemar's exact test on those flips gives the two-sided p value that the difference is
chance; with few flips no difference can be significant, which the output says.

Exit status: 0 done, 1 a run directory or report is missing or malformed, 2 usage error.
"""
import argparse
import glob
import json
import math
import os
import re
import statistics
import sys
from pathlib import Path

sys.dont_write_bytecode = True
REPO = Path(__file__).resolve().parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
VERSION = "1.0"
TRACKS = ("grammar", "exec", "judge")
OUTCOMES = ("answered", "refused", "filtered", "empty", "other", "error")

ARTIFACT = {
    "judge": re.compile(r"::JUDGE", re.I),
    "grammar": re.compile(r"::[A-Z_]{3,}|\[[A-ZΣΔφ∇λ∂μψξζθΩΠ]{1,5}[:|\]]"),
    "exec": re.compile(r"::[A-Z_]{3,}|\[[A-ZΣΔφ∇λ∂μψξζθΩΠ]{1,5}[:|\]]"),
}
FILTER_REASONS = {"content_filter", "safety", "blocked", "prohibited_content", "recitation", "spii", "refusal"}
APOS = "['’]"
REFUSE = re.compile(
    r"\bI (?:can" + APOS + r"?t|cannot|can not) (?:help|assist|comply|do (?:that|this)|provide|continue|proceed|follow"
    r"|fulfil|complete|process|pretend|act as|role-?play|adopt|take on|operate)"
    r"|\bI (?:won" + APOS + r"t|will not|must decline|need to decline|have to decline|am not able to|" + APOS + r"m not able to"
    r"|am unable to|" + APOS + r"m unable to|" + APOS + r"m not going to|am not going to)\b"
    r"|\bI (?:need|have|want) to be (?:direct|straightforward|honest|upfront|clear|transparent)\b"
    r"|\bI need to (?:clarify|point out|flag) (?:my|what|that|something)"
    r"|\bI(?:" + APOS + r"m| am) not (?:\"?Droid|\"?Factory|going to pretend|able to pretend)"
    r"|我不能|我无法|无法帮|不能帮|我不会(?:扮演|假装|冒充|执行)|抱歉[，,]?\s*我(?:不能|无法)|拒绝(?:执行|这个|该|此)", re.I)
REPLY_TAGS = (
    ("identity", re.compile(
        r"\bI(?:" + APOS + r"m| am) (?:Claude|ChatGPT|Gemini|an AI (?:assistant|model)|a (?:large )?language model)\b"
        r"|\bmade by (?:Anthropic|OpenAI|Google)\b|\bpretend(?:ing)? to be\b|\brole-?play|\bimperson|\bpersona\b"
        r"|\b(?:assume|adopt|take on) (?:a |an |the )?(?:different |new )?(?:identity|role)\b|\bmy (?:actual )?role\b"
        r"|扮演|冒充|假装|我是\s*Claude|我是一个?(?:AI|人工智能)", re.I)),
    ("permission", re.compile(
        r"authori[sz]|permission|privilege|\bdon" + APOS + r"?t have (?:direct |any )?access|\bdo not have (?:direct |any )?access"
        r"|\bno access\b|\bcan" + APOS + r"?t access|\bcannot access|权限|授权|无权|越权", re.I)),
    ("safety", re.compile(
        r"guideline|polic(?:y|ies)|\bsafety\b|\bharm(?:ful)?\b|\bethic|\bmy (?:values|rules|principles)\b|against my|violat"
        r"|安全(?:准则|规则|政策)|准则|政策|有害|违反|伦理", re.I)),
)
PROMPT_TAGS = (
    ("identity", re.compile(
        r"\byou are now\b|\bact as\b|\bpretend\b|\brole-?play\b|\bimpersonat|\bpose as\b|\bas @RUNTIME\b"
        r"|\bin the name of @|以\s*@?\w+\s*(?:的)?身份|冒充|假装|扮演|你现在是", re.I)),
    ("permission", re.compile(
        r"authority\s*:|\bauthori[sz]|\bpermission|\bprivilege|\bescalat|\bsudo\b|\broot\b|\badmin\b|@RUNTIME"
        r"|\bcommit\b|\bapprov|\bAPI key\b|\bcredential|\btoken\b|授权|权限|批准|审批|密钥", re.I)),
    ("safety", re.compile(
        r"ignore (?:all |any |the )?(?:previous|prior|above|earlier) (?:instructions|rules)|\bbypass|\bjailbreak|\bdisable"
        r"|\bexploit|\bmalware|\bpayload|\bbase64|\bdecod|\bpacket|\bcapture|\bcert(?:ificate)?s?\b|\.pem\b|\bprivate key"
        r"|\bcompromised|\bwipe|\bdestroy|\bforensic|忽略(?:之前|上面|以上)|绕过|越狱|抓包|解码|证书|私钥|入侵|擦除|销毁|取证", re.I)),
)
# Product names that, in a reply, show an identity injected by a relay. A name counts only when our own request
# (system message and case prompt) never mentions it.
FOREIGN = (("Droid", re.compile(r"\bDroid\b")), ("Factory", re.compile(r"\bFactory\b")),
           ("Claude Code", re.compile(r"\bClaude Code\b")), ("Kiro", re.compile(r"\bKiro\b")),
           ("Windsurf", re.compile(r"\bWindsurf\b")), ("Cline", re.compile(r"\bCline\b")),
           ("Roo Code", re.compile(r"\bRoo Code\b")), ("Augment Code", re.compile(r"\bAugment Code\b")))
# Prompt size: prompt tokens against the characters we sent over CHARS_PER_TOKEN. The runs so far that kept our
# system message lie between 1.0 and 2.7 (tokenizers differ by family), so only a ratio outside both bounds is flagged.
CHARS_PER_TOKEN = 3.6
DROPPED, INFLATED = 0.25, 3.0
UPPER_MIN_KEYS, UPPER_SHARE, UPPER_TRACK_SHARE = 3, 0.9, 0.5
# Modifier and vector keys (after | , or [ and before =) and declaration field keys (after { or | and before :).
# Verbs after [ are followed by :@ and line keys such as V: M: R: stand at a line start, so neither is matched.
KEY_RX = re.compile(r"(?<=[|,\[])([A-Za-z_][A-Za-z0-9_]*)(?==)|(?<=[{|])([A-Za-z_][A-Za-z0-9_]*)(?=:)")


def upper_cased(text):
    """True when almost every modifier or field key of the reply is upper case: PATH= or STATE: for path= or state:."""
    keys = [a or b for a, b in KEY_RX.findall(text or "")]
    keys = [k for k in keys if re.search(r"[A-Za-z]", k)]
    return len(keys) >= UPPER_MIN_KEYS and sum(k == k.upper() for k in keys) / len(keys) >= UPPER_SHARE


def dumps(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"


def load_cases(cases_dir):
    out = {}
    for f in sorted(glob.glob(os.path.join(str(cases_dir), "*", "*.jsonl"))):
        with open(f, encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    c = json.loads(line)
                    out[c["id"]] = c
    return out


def request_texts():
    """System message per track and a function for the user message, both exactly as run.py builds them."""
    import run
    return {t: run.system_message(t) for t in TRACKS}, run.user_message


def foreign_names(text, request_text):
    return [name for name, rx in FOREIGN if rx.search(text) and not rx.search(request_text)]


def error_cause(rec):
    body = rec.get("response_body")
    body = body if isinstance(body, str) else json.dumps(body, ensure_ascii=False)
    body += " " + str(rec.get("error") or "")
    code = rec.get("http_status")
    if code == 402 or re.search(r"insufficient balance|insufficient credit|credit balance|deposit required|quota|余额|充值", body, re.I):
        return "relay_billing"
    if code == 429 or re.search(r"rate limit|resource exhausted|too many requests", body, re.I):
        return "rate_limit"
    if code in (500, 502, 503, 504) or re.search(r"temporarily unavailable|temporarily_unavailable|no available channel|overloaded", body, re.I):
        return "unavailable"
    if re.search(r"timed out|timeout", body, re.I):
        return "timeout"
    return "other"


def classify(rec, track, request_text, prompt, relay_run):
    """(outcome, primary, tags, source, foreign) for one record."""
    if rec.get("status") != "ok":
        return "error", error_cause(rec), [], None, []
    text = rec.get("text") or ""
    finish = str(rec.get("finish_reason") or "").lower()
    if finish in FILTER_REASONS:
        if text.strip():
            foreign = foreign_names(text, request_text)
            tags = [n for n, rx in REPLY_TAGS if rx.search(text)]
            source = "reply"
        else:
            foreign = []
            tags = [n for n, rx in PROMPT_TAGS if rx.search(prompt)] or ["system"]
            source = "prompt"
        if relay_run or foreign:
            tags = ["relay"] + tags
        return "filtered", tags[0], tags, source, foreign
    if not text.strip():
        return "empty", finish or "none", [], None, []
    if ARTIFACT[track].search(text):
        return "answered", None, [], None, []
    if REFUSE.search(text):
        foreign = foreign_names(text, request_text)
        tags = [n for n, rx in REPLY_TAGS if rx.search(text)]
        if relay_run or foreign:
            tags = ["relay"] + tags
        return "refused", (tags[0] if tags else "unknown"), tags, "reply", foreign
    return "other", None, (["relay"] if relay_run else []), None, []


def prompt_tokens(rec):
    u = rec.get("usage") or {}
    return u.get("prompt_tokens") or u.get("input_tokens")


def read_run(run_dir):
    recs = {}
    for t in TRACKS:
        for f in sorted(glob.glob(os.path.join(str(run_dir), t, "*.json"))):
            with open(f, encoding="utf-8") as fh:
                recs.setdefault(t, []).append(json.load(fh))
    return recs


def analyse(run_dir, cases, systems, user_message):
    recs = read_run(run_dir)
    if not recs:
        raise ValueError("%s holds no track records" % run_dir)
    name = os.path.basename(os.path.normpath(str(run_dir)))
    prompt_size, relay_track = {}, {}
    for t in TRACKS:
        ratios = []
        for r in recs.get(t, []):
            case = cases.get(r.get("id"))
            pt = prompt_tokens(r)
            if r.get("status") == "ok" and pt and case:
                ratios.append(pt / ((len(systems[t]) + len(user_message(case))) / CHARS_PER_TOKEN))
        flag = None
        if ratios:
            m = statistics.median(ratios)
            flag = "system_dropped" if m < DROPPED else ("prompt_inflated" if m > INFLATED else None)
            prompt_size[t] = {"median_prompt_tokens": int(statistics.median(
                [prompt_tokens(r) for r in recs.get(t, []) if r.get("status") == "ok" and prompt_tokens(r)])),
                "ratio": round(m, 2), "flag": flag}
        relay_track[t] = flag == "system_dropped"
    empty = {k: 0 for k in ("records", "ok") + OUTCOMES}
    totals = dict(empty)
    reasons = {"refused": {}, "filtered": {}}
    tags_all = {"refused": {}, "filtered": {}}
    errors, ids, tracks, examples = {}, {"refused": {}, "filtered": {}}, {}, []
    groups, marks = {}, {}
    casing = {t: {"upper": 0, "ok": 0, "flag": None} for t in TRACKS}
    vendor = model = None
    for t in TRACKS:
        tt = dict(empty)
        for r in recs.get(t, []):
            req = r.get("request") or {}
            vendor = vendor or req.get("vendor")
            model = model or req.get("model")
            case = cases.get(r.get("id"), {})
            prompt = str(case.get("prompt") or "")
            outcome, primary, tags, source, foreign = classify(r, t, systems[t] + "\n" + prompt, prompt, relay_track[t])
            tt["records"] += 1
            tt[outcome] += 1
            if r.get("status") == "ok":
                tt["ok"] += 1
                casing[t]["ok"] += 1
                casing[t]["upper"] += upper_cased(r.get("text"))
                mark = next((n for n, rx in PROMPT_TAGS if rx.search(prompt)), "none")
                for part, key in ((groups, str(case.get("category") or case.get("kind") or "-")), (marks, mark)):
                    cell = part.setdefault(t, {}).setdefault(key, {"ok": 0, "refused": 0, "filtered": 0})
                    cell["ok"] += 1
                    if outcome in ("refused", "filtered"):
                        cell[outcome] += 1
            if outcome == "error":
                errors[primary] = errors.get(primary, 0) + 1
            if outcome in ("refused", "filtered"):
                reasons[outcome][primary] = reasons[outcome].get(primary, 0) + 1
                for g in tags:
                    tags_all[outcome][g] = tags_all[outcome].get(g, 0) + 1
                ids[outcome][r.get("id")] = primary
                if sum(1 for e in examples if e["outcome"] == outcome) < 3:
                    ex = {"id": r.get("id"), "track": t, "outcome": outcome, "primary": primary, "tags": tags, "source": source}
                    if foreign:
                        ex["foreign_identity"] = foreign
                    if (r.get("text") or "").strip():
                        ex["excerpt"] = re.sub(r"\s+", " ", r.get("text"))[:160]
                    examples.append(ex)
        tracks[t] = tt
        for k in totals:
            totals[k] += tt[k]
        if casing[t]["ok"] and casing[t]["upper"] / casing[t]["ok"] >= UPPER_TRACK_SHARE:
            casing[t]["flag"] = "upper_cased"
    casing = {t: c for t, c in casing.items() if c["ok"]}

    def rate(a, b):
        return round(a / b, 4) if b else None
    return {"run": name, "refusal_track": VERSION, "vendor": vendor, "model": model, "totals": totals, "tracks": tracks,
            "rates": {"refused": rate(totals["refused"], totals["ok"]), "filtered": rate(totals["filtered"], totals["ok"]),
                      "error": rate(totals["error"], totals["records"])},
            "reasons": reasons, "tags": tags_all, "errors": errors, "ids": ids, "prompt_size": prompt_size,
            "casing": casing, "by_case_group": groups, "by_prompt_marker": marks, "examples": examples}


def pct(x):
    return "-" if x is None else "%.1f%%" % (100 * x)


def counts(d):
    return ", ".join("%s %d" % (k, v) for k, v in sorted(d.items(), key=lambda kv: (-kv[1], kv[0]))) or "-"


def table(report_dir):
    rows = []
    for f in sorted(glob.glob(os.path.join(str(report_dir), "*", "refusal.json"))):
        with open(f, encoding="utf-8") as fh:
            rows.append(json.load(fh))
    rows.sort(key=lambda r: (-((r["rates"]["refused"] or 0) + (r["rates"]["filtered"] or 0)), r["run"]))
    lines = [
        "# ilang-conformance refusal track", "",
        "Generated by `refusal.py` from the raw run records; no model judges anything here. For each run: the share of "
        "replies that declined (refused) or that the provider withheld (filtered), over the records that got a reply, "
        "and what triggered them. Records that got no reply at all are errors and are counted apart. The rules are in "
        "the docstring of `refusal.py`; `python3 refusal.py --compare BEFORE AFTER` compares two runs case by case.", "",
        "| run | records | refused | filtered | error | refused by trigger | filtered by trigger | empty / other | errors by cause | prompt size g / e / j | upper-cased replies g / e / j |",
        "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        ps = " / ".join((("%s×" % r["prompt_size"][t]["ratio"]) + (" %s" % r["prompt_size"][t]["flag"] if r["prompt_size"][t]["flag"] else ""))
                        if t in r["prompt_size"] else "-" for t in TRACKS)
        cs = " / ".join((("%d/%d" % (c["upper"], c["ok"])) + (" %s" % c["flag"] if c["flag"] else "")) if (c := r.get("casing", {}).get(t)) else "-"
                        for t in TRACKS)
        lines.append("| %s | %d | %s | %s | %s | %s | %s | %d / %d | %s | %s | %s |" % (
            r["run"], r["totals"]["records"], pct(r["rates"]["refused"]), pct(r["rates"]["filtered"]), pct(r["rates"]["error"]),
            counts(r["reasons"]["refused"]), counts(r["reasons"]["filtered"]), r["totals"]["empty"], r["totals"]["other"],
            counts(r["errors"]), ps, cs))
    lines += ["", "Empty: a reply with no text, mostly finish_reason length (the output budget went to reasoning). Other: text "
              "without the track's artifact that does not decline, such as prose, leaked reasoning or the wrong format.", "",
              "Prompt size: the median, over a track's records, of prompt tokens against the characters we sent over %.1f. "
              "The runs that kept our system message lie between 1.0 and 2.7 because tokenizers differ by family, so only "
              "`system_dropped` (below %.2f×: the relay did not pass our system message on) and `prompt_inflated` (above "
              "%.1f×: the relay added a prompt of its own) mean something." % (CHARS_PER_TOKEN, DROPPED, INFLATED), "",
              "Upper-cased replies: replies in which at least %d%% of the modifier and field keys (the tokens before = and :) "
              "are upper case, over the replies on that track. The canon writes those keys in lower case, so such a reply "
              "fails every validator whatever it says; a track with half or more of its replies like this is flagged "
              "`upper_cased`. Where the same request through another relay comes back in lower case, the casing is the "
              "relay's and the run measures the relay, not the model." % round(100 * UPPER_SHARE)]
    shown = [r for r in rows if r["totals"]["refused"] + r["totals"]["filtered"]]
    if shown:
        lines += ["", "## Where they fall", "",
                  "For each run with refusals or filters: counts over the records that got a reply, by case group and by "
                  "the first marker in the case prompt (identity, permission, safety, none). A group whose rate stands "
                  "far above the others points at what the cases have in common; `none` points at what every case of "
                  "the track shares, the system message."]
        for r in shown:
            lines += ["", "### %s" % r["run"], "", "| track | split | group | refused | filtered | of |", "|---|---|---|---|---|---|"]
            for t in TRACKS:
                for split, part in (("case group", r["by_case_group"]), ("prompt marker", r["by_prompt_marker"])):
                    for g, c in sorted(part.get(t, {}).items()):
                        lines.append("| %s | %s | %s | %d | %d | %d |" % (t, split, g, c["refused"], c["filtered"], c["ok"]))
    Path(report_dir, "REFUSALS.md").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return len(rows)


def mcnemar_p(b, c):
    """Two-sided exact McNemar p value for b and c discordant pairs."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def load_result(ref, report_dir):
    path = Path(ref)
    if path.is_dir():
        path = path / "refusal.json"
    if not path.is_file():
        path = Path(report_dir, ref, "refusal.json")
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def compare(before, after):
    lines = ["# %s → %s" % (before["run"], after["run"]), ""]
    b_ids = {k: set(v) for k, v in before["ids"].items()}
    a_ids = {k: set(v) for k, v in after["ids"].items()}
    lines += ["| | before | after |", "|---|---|---|"]
    for k in ("refused", "filtered", "error"):
        lines.append("| %s | %d (%s) | %d (%s) |" % (k, before["totals"][k], pct(before["rates"][k]), after["totals"][k], pct(after["rates"][k])))
    for t in TRACKS:
        bt, at = before["tracks"].get(t, {}), after["tracks"].get(t, {})
        lines.append("| %s refused / filtered | %d / %d | %d / %d |" % (t, bt.get("refused", 0), bt.get("filtered", 0), at.get("refused", 0), at.get("filtered", 0)))
    lines.append("")
    for k in ("refused", "filtered"):
        gone, new = sorted(b_ids[k] - a_ids[k]), sorted(a_ids[k] - b_ids[k])
        p = mcnemar_p(len(gone), len(new))
        lines.append("%s: %d cases only before, %d only after, %d in both; McNemar exact p = %.4f%s" % (
            k, len(gone), len(new), len(b_ids[k] & a_ids[k]), p,
            "" if len(gone) + len(new) >= 6 else " (fewer than 6 flips: no difference can reach p < 0.05)"))
        if gone:
            lines.append("  only before: " + ", ".join("%s(%s)" % (i, before["ids"][k][i]) for i in gone))
        if new:
            lines.append("  only after: " + ", ".join("%s(%s)" % (i, after["ids"][k][i]) for i in new))
    lines.append("")
    lines.append("before triggers: refused %s; filtered %s" % (counts(before["reasons"]["refused"]), counts(before["reasons"]["filtered"])))
    lines.append("after triggers: refused %s; filtered %s" % (counts(after["reasons"]["refused"]), counts(after["reasons"]["filtered"])))
    return "\n".join(lines) + "\n"


def main(argv=None):
    p = argparse.ArgumentParser(description="ilang-conformance refusal track")
    p.add_argument("run_dirs", nargs="*", metavar="RUN_DIR")
    p.add_argument("--table", action="store_true", help="regenerate REPORT/REFUSALS.md")
    p.add_argument("--compare", nargs=2, metavar=("BEFORE", "AFTER"))
    p.add_argument("--cases", default=str(REPO / "cases"))
    p.add_argument("--report", default=str(REPO / "report"))
    a = p.parse_args(argv)
    if not a.run_dirs and not a.table and not a.compare:
        p.print_usage(sys.stderr)
        return 2
    if a.run_dirs:
        for rd in a.run_dirs:
            if not os.path.isdir(rd):
                print("refusal: no such run directory: %s" % rd, file=sys.stderr)
                return 1
        cases = load_cases(a.cases)
        systems, user_message = request_texts()
        for rd in a.run_dirs:
            try:
                res = analyse(rd, cases, systems, user_message)
            except (ValueError, OSError, json.JSONDecodeError) as e:
                print("refusal: %s" % e, file=sys.stderr)
                return 1
            d = Path(a.report, res["run"])
            d.mkdir(parents=True, exist_ok=True)
            (d / "refusal.json").write_text(dumps(res), encoding="utf-8", newline="\n")
            print("%s refused %s filtered %s error %s" % (res["run"], pct(res["rates"]["refused"]), pct(res["rates"]["filtered"]), pct(res["rates"]["error"])))
    if a.table:
        print("REFUSALS.md rows: %d" % table(a.report))
    if a.compare:
        try:
            before, after = (load_result(x, a.report) for x in a.compare)
        except (OSError, json.JSONDecodeError) as e:
            print("refusal: %s" % e, file=sys.stderr)
            return 1
        sys.stdout.write(compare(before, after))
    return 0


if __name__ == "__main__":
    sys.exit(main())
