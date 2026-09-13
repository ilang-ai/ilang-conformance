#!/usr/bin/env bash
# ilang-conformance background launcher (book §3 run.sh, §8 FACT background and RULE
# u24_is_shared; cases/SCHEMA.md §8.5). Validates the run synchronously with
# `run.py --dry-run`, then starts run.py under nohup with stdout and stderr appended to
# runs/<run>/run.log, records the pid in runs/<run>/pid and returns at once. DONE and
# MANIFEST.sha256 are written by run.py when every case has a record.
#
# Writes only inside runs/<run>/. No system packages, no global config, no crontab or
# systemd, no listening port, and it never stops a process.
#
#   bash run.sh --vendor NAME [--track grammar|exec|judge|all] [--concurrency N] [--limit N] [--cases-dir DIR]
#   bash run.sh --vendor NAME --run-dir runs/NAME-yyyymmdd-HHMMSS [...]    # resume that run
#
# API keys: run.py reads them only from ~/.ilang-conformance.env (chmod 600), never from the
# environment of this shell. A resume re-requests every case whose stored request differs from
# the current corpus, spec or vendors.json entry.
# --limit N is for smoke tests: run.py writes DONE for the selected cases, but score.py refuses
# the run because the rest of the corpus has no record.
#
# Stop a run: kill "$(cat runs/<run>/pid)"    (only the recorded pid, never by process name)
set -euo pipefail
cd "$(dirname "$0")"
PY="${PYTHON:-python3}"
export PYTHONIOENCODING=utf-8

vendor=""
run_dir=""
limited=0
pass=()
while [ $# -gt 0 ]; do
  case "$1" in
    --limit)
      [ $# -ge 2 ] || { echo "run.sh: --limit needs a value" >&2; exit 2; }
      limited=1; pass+=("$1" "$2"); shift 2 ;;
    --limit=*)
      limited=1; pass+=("$1"); shift ;;
    --run-dir)
      [ $# -ge 2 ] || { echo "run.sh: --run-dir needs a value" >&2; exit 2; }
      run_dir="$2"; shift 2 ;;
    --run-dir=*)
      run_dir="${1#--run-dir=}"; shift ;;
    --vendor)
      [ $# -ge 2 ] || { echo "run.sh: --vendor needs a value" >&2; exit 2; }
      vendor="$2"; pass+=("$1" "$2"); shift 2 ;;
    --vendor=*)
      vendor="${1#--vendor=}"; pass+=("$1"); shift ;;
    --dry-run|--selftest)
      echo "run.sh: $1 runs in the foreground: $PY run.py $1 ..." >&2; exit 2 ;;
    *)
      pass+=("$1"); shift ;;
  esac
done
if [ -z "$vendor" ]; then
  echo "usage: bash run.sh --vendor NAME [--track grammar|exec|judge|all] [--concurrency N] [--limit N] [--cases-dir DIR] [--run-dir DIR]" >&2
  exit 2
fi

fresh=0
if [ -z "$run_dir" ]; then
  fresh=1
  run_dir="runs/${vendor}-$(date -u +%Y%m%d-%H%M%S)"
  if [ -e "$run_dir" ]; then
    echo "run.sh: $run_dir already exists; not overwriting" >&2
    exit 2
  fi
fi

if [ -f "$run_dir/pid" ]; then
  old="$(cat "$run_dir/pid" 2>/dev/null || true)"
  if [[ "$old" =~ ^[0-9]+$ ]] && kill -0 "$old" 2>/dev/null; then
    if [ ! -r "/proc/$old/cmdline" ] || tr '\0' ' ' <"/proc/$old/cmdline" | grep -q 'run\.py'; then
      echo "run.sh: pid $old recorded in $run_dir/pid is still running; not starting a second runner" >&2
      exit 2
    fi
  fi
  rm -f "$run_dir/pid"          # stale pid of this run's earlier runner
fi

if ! "$PY" run.py "${pass[@]}" --run-dir "$run_dir" --dry-run; then
  echo "run.sh: preflight failed; nothing started" >&2
  exit 2
fi

if [ "$fresh" = 1 ]; then
  mkdir -p "$(dirname "$run_dir")"
  mkdir "$run_dir"
else
  mkdir -p "$run_dir"
fi
log="$run_dir/run.log"
nohup "$PY" run.py "${pass[@]}" --run-dir "$run_dir" >>"$log" 2>&1 </dev/null &
pid=$!
echo "$pid" >"$run_dir/pid"
echo "started  pid $pid"
echo "run dir  $run_dir"
echo "log      $log"
echo "stop     kill $pid"
if [ "$limited" = 1 ]; then
  echo "note     --limit run: DONE covers the selected cases only and score.py refuses this run"
else
  case "$run_dir" in
    runs/*) score_cmd="$PY score.py --latest --vendor $vendor" ;;
    *)      score_cmd="$PY score.py $run_dir" ;;       # --latest only looks under runs/
  esac
  echo "score    $score_cmd   (once $run_dir/DONE exists)"
fi
