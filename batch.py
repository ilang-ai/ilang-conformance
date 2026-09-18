#!/usr/bin/env python3
"""ilang-conformance batch driver: every chat model behind one endpoint, unattended.

For an OpenAI-compatible endpoint that serves many models (a relay or an aggregator), this
lists the models, writes one vendors.json entry per model, screens each model with one case
per track while it tries the parameter variants the runner allows, runs the full corpus for
every model that passed, K models at a time, resumes interrupted runs, scores each finished
run, and packs the results for hand-back.

  python3 batch.py models  --base-url URL --auth-env NAME
  python3 batch.py vendors --prefix NAME --base-url URL --auth-env NAME [--models FILE]
  python3 batch.py screen  [--workers N] [--redo | --retry-skips]
  python3 batch.py estimate
  python3 batch.py run     [--parallel K] [--concurrency C] [--max-resumes N] [--poll S]
  python3 batch.py status
  python3 batch.py pack    [--part-mb N]

State lives in batch/ (git-ignored) and in the run directories, and every command reads it
back from disk, so any command can be stopped and started again and continues where it was.
Keys are read only from ~/.ilang-conformance.env, the way run.py reads them, and are never
printed. The driver starts run.sh, run.py and score.py and changes none of them, nor any case;
the only repository file it writes is vendors.json (one local entry per model, not for commit).
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tarfile
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import run as runner

REPO = Path(__file__).resolve().parent
BATCH = REPO / "batch"
VENDORS = REPO / "vendors.json"
PY = sys.executable
TRACK_CASES = {"grammar": 120, "exec": 100, "judge": 100}

# model ids that name no chat model: embeddings, speech, images, video, music, moderation, rerank
NON_CHAT = re.compile(r"embed|tts|whisper|transcri|audio|speech|dall-?e|image|imagen|flux|"
                      r"stable-diffusion|sdxl|midjourney|moderation|rerank|video|veo|sora|kling|"
                      r"suno|music", re.I)
LADDER = ("temperature", "seed", "field", "max_tokens")      # the order the variants are tried in
SCREEN_ATTEMPTS = 6
RATE_WAITS = (60, 120, 240)

_vendors_lock = threading.Lock()


def stamp():
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def say(msg):
    print(msg, flush=True)


# ------------------------------------------------------------------ files
def write_atomic(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(tmp, path)


def read_lines(path):
    if not path.exists():
        return []
    return [l.strip() for l in path.read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")]


def read_tsv(path, cols):
    out = {}
    for line in read_lines(path):
        cells = line.split("\t")
        cells += [""] * (len(cols) - len(cells))
        row = dict(zip(cols, cells))
        out[row[cols[0]]] = row
    return out


def write_tsv(path, cols, rows):
    text = "#" + "\t".join(cols) + "\n" + "".join(
        "\t".join(str(r.get(c, "")).replace("\t", " ").replace("\n", " ") for c in cols) + "\n"
        for r in rows)
    write_atomic(path, text)


def load_vendors():
    return json.loads(VENDORS.read_text(encoding="utf-8"))


def save_vendors(data):
    write_atomic(VENDORS, json.dumps(data, ensure_ascii=False, indent=1) + "\n")


def entry_of(name):
    for v in load_vendors():
        if v.get("name") == name:
            return v
    raise SystemExit("batch: vendor %s is not in vendors.json" % name)


def update_entry(name, params):
    with _vendors_lock:
        data = load_vendors()
        for v in data:
            if v.get("name") == name:
                v.update(params)
        save_vendors(data)


def records(run_dir):
    out = []
    for t in TRACK_CASES:
        d = run_dir / t
        if d.is_dir():
            for p in sorted(d.glob("*.json")):
                try:
                    out.append(json.loads(p.read_text(encoding="utf-8")))
                except (OSError, ValueError):
                    out.append({"status": "error", "error": "unreadable record %s" % p.name})
    return out


# ------------------------------------------------------------------ models
def slug(model):
    s = re.sub(r"[^A-Za-z0-9._-]+", "-", model).strip("-._")
    return s or "model"


def is_chat_candidate(model_id):
    return NON_CHAT.search(model_id) is None


def cmd_models(a):
    key = runner.load_key(a.auth_env, runner.ENV_FILE)
    if not key:
        raise SystemExit("batch: no %s in %s (chmod 600)" % (a.auth_env, runner.ENV_FILE))
    url = a.base_url.rstrip("/") + "/models"
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + key,
                                               "User-Agent": "ilang-conformance-batch"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            body = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise SystemExit("batch: GET %s answered HTTP %d" % (url, e.code))
    except (urllib.error.URLError, ValueError) as e:
        raise SystemExit("batch: GET %s failed: %s" % (url, type(e).__name__))
    items = body.get("data", body) if isinstance(body, dict) else body
    ids = sorted({(m.get("id") if isinstance(m, dict) else str(m)) for m in items} - {None, ""})
    keep = [m for m in ids if is_chat_candidate(m)]
    drop = [m for m in ids if not is_chat_candidate(m)]
    write_atomic(BATCH / "models-all.txt", "".join(m + "\n" for m in ids))
    write_atomic(BATCH / "models.txt", "".join(m + "\n" for m in keep))
    say("models: %d listed, %d kept in batch/models.txt, %d dropped as not chat:" % (len(ids), len(keep), len(drop)))
    for m in drop:
        say("  dropped " + m)
    return 0


# ------------------------------------------------------------------ vendors
def cmd_vendors(a):
    models = read_lines(Path(a.models) if a.models else BATCH / "models.txt")
    if not models:
        raise SystemExit("batch: no models listed (run `batch.py models` or pass --models FILE)")
    data = load_vendors()
    by_name = {v.get("name"): v for v in data}
    names = []
    for m in models:
        base = "%s-%s" % (a.prefix, slug(m))
        name, n = base, 1
        while name in by_name and not (by_name[name].get("model") == m and by_name[name].get("base_url") == a.base_url):
            n += 1
            name = "%s-%d" % (base, n)
        if not runner.VENDOR_NAME.fullmatch(name):
            raise SystemExit("batch: vendor name %r is not usable" % name)
        if name not in by_name:
            if a.api == "mock":
                e = {"name": name, "api": "mock", "base_url": "", "model": m, "auth_env": "",
                     "max_tokens": 4096, "seed": False}
            else:
                e = {"name": name, "api": "openai_compatible", "base_url": a.base_url, "model": m,
                     "auth_env": a.auth_env, "max_tokens": 8192, "max_tokens_field": "max_tokens",
                     "temperature": 0, "seed": True}
            runner.check_vendor(dict(e))
            data.append(e)
            by_name[name] = e
        names.append(name)
    save_vendors(data)
    write_atomic(BATCH / "vendors.txt", "".join(n + "\n" for n in names))
    say("vendors: %d entries for batch/vendors.txt (vendors.json now holds %d)" % (len(names), len(data)))
    return 0


def batch_vendors():
    names = read_lines(BATCH / "vendors.txt")
    if not names:
        raise SystemExit("batch: batch/vendors.txt is empty (run `batch.py vendors` first)")
    return names


# ------------------------------------------------------------------ screen
SCREEN_COLS = ["vendor", "result", "attempts", "params", "run_dir", "reason"]


def params_of(entry):
    return {"temperature": entry.get("temperature", 0), "seed": entry.get("seed", entry.get("api") == "openai_compatible"),
            "max_tokens_field": entry.get("max_tokens_field", "max_tokens"), "max_tokens": entry.get("max_tokens", 4096)}


TOO_BIG = re.compile(r"context.{0,20}(?:length|window)|too (?:large|long)|exceed|must be (?:less|at most|<=)|"
                     r"at most \d+|maximum (?:value|allowed)")
CUT_SHORT = re.compile(r"finish_reason\W{0,3}length")


def next_params(params, error_text, lowered=False):
    """(variant, step) after a failed screen: the change the error text names first, else the
    next untried change in LADDER order; (None, None) when no change is left. A limit the
    provider calls too large lowers max_tokens to 4096, and once lowered it is never raised."""
    low = error_text.lower()
    wants = []
    too_big = TOO_BIG.search(low) is not None
    if too_big:
        wants.append("lower")
    if "temperature" in low:
        wants.append("temperature")
    if "seed" in low:
        wants.append("seed")
    if "max_completion_tokens" in low or ("max_tokens" in low and not too_big):
        wants.append("field")
    if CUT_SHORT.search(low) and not too_big:
        wants.append("max_tokens")
    for step in wants + list(LADDER):
        new = dict(params)
        if step == "lower" and params["max_tokens"] > 4096:
            new["max_tokens"] = 4096
        elif step == "temperature" and params["temperature"] is not None:
            new["temperature"] = None
        elif step == "seed" and params["seed"]:
            new["seed"] = False
        elif step == "field" and params["max_tokens_field"] == "max_tokens":
            new["max_tokens_field"] = "max_completion_tokens"
        elif step == "max_tokens" and not lowered and params["max_tokens"] < 32000:
            new["max_tokens"] = 16000 if params["max_tokens"] < 16000 else 32000
        else:
            continue
        return new, step
    return None, None


def failure_text(recs):
    """Why a screen did not pass: runner errors, and replies that came back empty."""
    parts = []
    for r in recs:
        if r.get("status") != "ok":
            parts.append(r.get("error") or "no record")
        elif not (r.get("text") or "").strip():
            parts.append("empty reply (finish_reason %s)" % r.get("finish_reason"))
    return " | ".join(parts)


def screen_one(name):
    entry = entry_of(name)
    params = params_of(entry)
    rate_waits = list(RATE_WAITS)
    lowered = False
    for attempt in range(1, SCREEN_ATTEMPTS + 1):
        if entry.get("api") != "mock":
            update_entry(name, params)
        rd = BATCH / "screen" / ("a%d" % attempt) / ("%s-%s" % (name, stamp()))
        cp = subprocess.run([PY, "run.py", "--vendor", name, "--track", "all", "--limit", "1",
                             "--concurrency", "3", "--run-dir", str(rd)],
                            cwd=REPO, capture_output=True, text=True, encoding="utf-8", errors="replace")
        recs = records(rd)
        rel = rd.relative_to(REPO).as_posix()
        err = failure_text(recs)
        if len(recs) < 3 and not err:
            # the runner stopped or could not write a record: not a parameter problem
            tail = (cp.stderr or cp.stdout).strip().splitlines()[-1:] or ["exit %d" % cp.returncode]
            return {"vendor": name, "result": "skip", "attempts": attempt, "params": json.dumps(params),
                    "run_dir": rel, "reason": "runner: %d of 3 records; %s" % (len(recs), tail[0][:200])}
        if not err:
            return {"vendor": name, "result": "pass", "attempts": attempt, "params": json.dumps(params),
                    "run_dir": rel, "reason": ""}
        low = err.lower()
        if "http 401" in low or "http 403" in low:
            return {"vendor": name, "result": "skip", "attempts": attempt, "params": json.dumps(params),
                    "run_dir": rel, "reason": "auth: " + err[:200]}
        if "http 404" in low:
            return {"vendor": name, "result": "skip", "attempts": attempt, "params": json.dumps(params),
                    "run_dir": rel, "reason": "not served: " + err[:200]}
        if "http " not in low and "empty reply" not in low and "network:" in low:
            return {"vendor": name, "result": "skip", "attempts": attempt, "params": json.dumps(params),
                    "run_dir": rel, "reason": "network: " + err[:200]}
        if "http 429" in low and rate_waits:
            time.sleep(rate_waits.pop(0))
            continue
        new, step = next_params(params, err, lowered)
        if new is None:
            return {"vendor": name, "result": "skip", "attempts": attempt, "params": json.dumps(params),
                    "run_dir": rel, "reason": "no variant passes: " + err[:200]}
        lowered = lowered or step == "lower"
        params = new
    return {"vendor": name, "result": "skip", "attempts": SCREEN_ATTEMPTS, "params": json.dumps(params),
            "run_dir": "", "reason": "screen attempts used up"}


def cmd_screen(a):
    names = batch_vendors()
    done = read_tsv(BATCH / "screen.tsv", SCREEN_COLS)
    todo = [n for n in names if a.redo or n not in done
            or (a.retry_skips and done[n].get("result") == "skip")]
    say("screen: %d to screen, %d already screened" % (len(todo), len(names) - len(todo)))
    lock = threading.Lock()

    def work(n):
        row = screen_one(n)
        with lock:
            done[n] = row
            write_tsv(BATCH / "screen.tsv", SCREEN_COLS, [done[k] for k in names if k in done])
            say("  %-40s %s %s" % (n, row["result"], row["reason"][:100]))

    with ThreadPoolExecutor(max_workers=max(1, a.workers)) as ex:
        list(ex.map(work, todo))
    passed = sum(1 for n in names if done.get(n, {}).get("result") == "pass")
    say("screen: %d pass, %d skip" % (passed, len(names) - passed))
    return 0


def screened_pass():
    done = read_tsv(BATCH / "screen.tsv", SCREEN_COLS)
    return [n for n in batch_vendors() if done.get(n, {}).get("result") == "pass"], done


# ------------------------------------------------------------------ estimate
def usage_of(rec):
    u = rec.get("usage") or {}
    return (u.get("prompt_tokens", u.get("input_tokens", 0)) or 0,
            u.get("completion_tokens", u.get("output_tokens", 0)) or 0)


def cmd_estimate(a):
    names, done = screened_pass()
    tot_in = tot_out = 0
    say("%-40s %14s %14s" % ("vendor", "input (est.)", "output (est.)"))
    for n in names:
        rd = REPO / done[n]["run_dir"]
        est_in = est_out = 0
        for t, count in TRACK_CASES.items():
            recs = records_of_track(rd, t)
            if recs:
                p, c = usage_of(recs[0])
                est_in += p * count
                est_out += c * count
        tot_in += est_in
        tot_out += est_out
        say("%-40s %14d %14d" % (n, est_in, est_out))
    say("%-40s %14d %14d" % ("total (%d models)" % len(names), tot_in, tot_out))
    say("Scaled from one screened case per track; the output of reasoning models varies widely.")
    return 0


def records_of_track(run_dir, track):
    d = run_dir / track
    if not d.is_dir():
        return []
    out = []
    for p in sorted(d.glob("*.json")):
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            pass
    return out


# ------------------------------------------------------------------ run
FULL_COLS = ["vendor", "state", "run_dir", "resumes", "note"]


def alive(run_dir):
    try:
        pid = int((run_dir / "pid").read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        return False
    probe = ('kill -0 %d 2>/dev/null && { [ ! -r /proc/%d/cmdline ] || '
             'tr "\\0" " " </proc/%d/cmdline | grep -q "run\\.py"; }') % (pid, pid, pid)
    return subprocess.run(["bash", "-c", probe]).returncode == 0


def launch(args):
    env = dict(os.environ, PYTHON=PY)
    cp = subprocess.run(["bash", "run.sh"] + args, cwd=REPO, capture_output=True, text=True,
                        encoding="utf-8", errors="replace", env=env)
    m = re.search(r"^run dir\s+(\S+)", cp.stdout, re.M)
    return cp.returncode, (m.group(1) if m else ""), (cp.stderr or cp.stdout).strip()


def error_count(run_dir):
    return sum(1 for r in records(run_dir) if r.get("status") != "ok")


def cmd_run(a):
    names, _ = screened_pass()
    if not names:
        raise SystemExit("batch: no screened model passed (run `batch.py screen` first)")
    state = read_tsv(BATCH / "full.tsv", FULL_COLS)
    say("run: %d models, %d at a time, concurrency %d each" % (len(names), a.parallel, a.concurrency))
    while True:
        active = 0
        for n in names:
            s = state.get(n)
            if not s or s["state"] in ("scored", "failed"):
                continue
            rd = REPO / s["run_dir"]
            if alive(rd):
                active += 1
                continue
            resumes = int(s["resumes"] or 0)
            if (rd / "DONE").exists():
                errs = error_count(rd)
                if errs and resumes < a.max_resumes:
                    rc, _, out = launch(["--vendor", n, "--track", "all", "--concurrency", str(a.concurrency),
                                         "--run-dir", s["run_dir"]])
                    s.update(resumes=resumes + 1, note="resumed for %d error records" % errs)
                    active += rc == 0
                    continue
                cp = subprocess.run([PY, "score.py", s["run_dir"], "--vendor", n], cwd=REPO,
                                    capture_output=True, text=True, encoding="utf-8", errors="replace")
                line = next((l for l in cp.stdout.splitlines() if l.startswith("grammar=")), "")
                s.update(state="scored" if cp.returncode == 0 else "failed",
                         note=line if cp.returncode == 0 else "score.py: " + (cp.stderr or cp.stdout).strip()[-200:])
                say("  %-40s %s %s" % (n, s["state"], s["note"][:150]))
                continue
            if resumes < a.max_resumes:
                rc, _, out = launch(["--vendor", n, "--track", "all", "--concurrency", str(a.concurrency),
                                     "--run-dir", s["run_dir"]])
                s.update(resumes=resumes + 1, note="resumed after the runner stopped without DONE")
                active += rc == 0
            else:
                s.update(state="failed", note="no DONE after %d resumes" % resumes)
                say("  %-40s failed %s" % (n, s["note"]))
        for n in names:
            if active >= a.parallel:
                break
            if n in state:
                continue
            rc, rd, out = launch(["--vendor", n, "--track", "all", "--concurrency", str(a.concurrency)])
            if rc == 0 and rd:
                state[n] = {"vendor": n, "state": "running", "run_dir": rd, "resumes": 0, "note": ""}
                active += 1
                say("  %-40s started %s" % (n, rd))
            else:
                state[n] = {"vendor": n, "state": "failed", "run_dir": rd, "resumes": 0,
                            "note": "run.sh: " + out[-200:]}
                say("  %-40s failed to start: %s" % (n, out[-200:]))
        write_tsv(BATCH / "full.tsv", FULL_COLS, [state[n] for n in names if n in state])
        if all(state.get(n, {}).get("state") in ("scored", "failed") for n in names):
            break
        time.sleep(a.poll)
    scored = sum(1 for n in names if state[n]["state"] == "scored")
    say("run: %d scored, %d failed; details in batch/full.tsv and report/SCOREBOARD.md" % (scored, len(names) - scored))
    return 0


# ------------------------------------------------------------------ status
def cmd_status(a):
    names = batch_vendors()
    screen = read_tsv(BATCH / "screen.tsv", SCREEN_COLS)
    full = read_tsv(BATCH / "full.tsv", FULL_COLS)
    say("%-40s %-6s %-8s %s" % ("vendor", "screen", "full", "note"))
    for n in names:
        sc = screen.get(n, {}).get("result", "-")
        f = full.get(n, {})
        st = f.get("state", "-")
        if st == "running" and not alive(REPO / f["run_dir"]):
            st = "stopped"
        say("%-40s %-6s %-8s %s" % (n, sc, st, (f.get("note") or screen.get(n, {}).get("reason", ""))[:120]))
    return 0


# ------------------------------------------------------------------ pack
def cmd_pack(a):
    names = batch_vendors()
    full = read_tsv(BATCH / "full.tsv", FULL_COLS)
    entries = {v["name"]: v for v in load_vendors()}
    used = [entries[n] for n in names if n in entries]
    write_atomic(BATCH / "vendors-used.json", json.dumps(used, ensure_ascii=False, indent=1) + "\n")
    files = [BATCH / f for f in ("models-all.txt", "models.txt", "vendors.txt", "screen.tsv", "full.tsv",
                                 "vendors-used.json")] + [REPO / "report" / "SCOREBOARD.md"]
    for n in names:
        f = full.get(n)
        if not f or not f.get("run_dir"):
            continue
        rd = REPO / f["run_dir"]
        files += [p for p in sorted(rd.rglob("*")) if p.is_file() and p.name != "pid"]
        rep = REPO / "report" / rd.name
        if rep.is_dir():
            files += sorted(p for p in rep.rglob("*") if p.is_file())
    files = [p for p in files if p.is_file()]
    needles = set()
    for env in sorted({e.get("auth_env") for e in used if e.get("auth_env")}):
        key = runner.load_key(env, runner.ENV_FILE)
        if key:
            needles.add(key[:12].encode("utf-8"))
    for p in files:
        data = p.read_bytes()
        for nd in needles:
            if nd in data:
                raise SystemExit("batch: a key prefix appears in %s; nothing packed" % p.relative_to(REPO))
    out = BATCH / ("pack-%s.tar.gz" % stamp())
    with tarfile.open(out, "w:gz") as tar:
        for p in files:
            tar.add(p, arcname=p.relative_to(REPO).as_posix(), recursive=False)
    digest = hashlib.sha256(out.read_bytes()).hexdigest()
    say("pack: %s, %d files, %d bytes, sha256 %s, key scan clean" % (out.relative_to(REPO).as_posix(), len(files),
                                                                   out.stat().st_size, digest))
    parts = split_file(out, a.part_mb * 1024 * 1024)
    for part in parts:
        say("  part %s %d bytes sha256 %s" % (part.name, part.stat().st_size,
                                              hashlib.sha256(part.read_bytes()).hexdigest()))
    if parts:
        say("  join with: cat %s.part* > %s" % (out.name, out.name))
    return 0


def split_file(path, limit):
    """Parts of at most limit bytes named <file>.partNN when the file is larger; [] otherwise."""
    if path.stat().st_size <= limit:
        return []
    data = path.read_bytes()
    parts = []
    for i in range(0, len(data), limit):
        part = path.with_name(path.name + ".part%02d" % (i // limit + 1))
        part.write_bytes(data[i:i + limit])
        parts.append(part)
    return parts


# ------------------------------------------------------------------ main
def main(argv=None):
    ap = argparse.ArgumentParser(description="ilang-conformance batch driver")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("models")
    p.add_argument("--base-url", required=True)
    p.add_argument("--auth-env", required=True)
    p = sub.add_parser("vendors")
    p.add_argument("--prefix", required=True)
    p.add_argument("--base-url", required=True)
    p.add_argument("--auth-env", required=True)
    p.add_argument("--models")
    p.add_argument("--api", choices=("openai_compatible", "mock"), default="openai_compatible")
    p = sub.add_parser("screen")
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--redo", action="store_true", help="screen every model again")
    p.add_argument("--retry-skips", action="store_true", help="screen again only the models that were skipped")
    sub.add_parser("estimate")
    p = sub.add_parser("run")
    p.add_argument("--parallel", type=int, default=4)
    p.add_argument("--concurrency", type=int, default=2)
    p.add_argument("--max-resumes", type=int, default=2)
    p.add_argument("--poll", type=float, default=30)
    sub.add_parser("status")
    p = sub.add_parser("pack")
    p.add_argument("--part-mb", type=int, default=45)
    a = ap.parse_args(argv)
    if a.cmd == "vendors" and a.api == "openai_compatible" and not a.base_url.startswith(("https://", "http://")):
        ap.error("--base-url must start with https:// or http://")
    try:
        return {"models": cmd_models, "vendors": cmd_vendors, "screen": cmd_screen, "estimate": cmd_estimate,
                "run": cmd_run, "status": cmd_status, "pack": cmd_pack}[a.cmd](a)
    except runner.ConfigError as e:
        raise SystemExit("batch: %s" % e)


if __name__ == "__main__":
    sys.exit(main())
