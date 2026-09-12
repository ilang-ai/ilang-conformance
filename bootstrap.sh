#!/usr/bin/env bash
# ilang-conformance bootstrap. Idempotent and offline: asserts python3 >= 3.12,
# verifies every vendor/ file against vendor/PIN, runs both upstream selftests.
# No venv, no pip, no git pull. Writes nothing.
set -euo pipefail
cd "$(dirname "$0")"
PY="${PYTHON:-python3}"
export PYTHONIOENCODING=utf-8

"$PY" - <<'PYEOF'
import sys
if sys.version_info < (3, 12):
    sys.exit("python >= 3.12 required, found " + sys.version.split()[0])
print("python " + sys.version.split()[0] + " ok")
PYEOF

"$PY" - <<'PYEOF'
import hashlib, pathlib, sys
rows = [l.split() for l in pathlib.Path("vendor/PIN").read_text(encoding="utf-8").splitlines()]
files = [r for r in rows if len(r) == 2 and len(r[0]) == 64]
bad = 0
for digest, name in files:
    ok = hashlib.sha256(pathlib.Path("vendor", name).read_bytes()).hexdigest() == digest
    bad += not ok
    print(("pin ok   " if ok else "MISMATCH ") + name)
if len(files) != 5 or bad:
    sys.exit("vendor/PIN check failed: %d files listed, %d mismatched" % (len(files), bad))
PYEOF

for v in ilang_grammar_validator ilang_judge_validator; do
  out="$("$PY" "vendor/$v.py" --selftest 2>&1)" || { echo "$out"; echo "$v selftest failed"; exit 1; }
  last="$(grep -E '^[0-9]+/[0-9]+ passed$' <<<"$out" | tail -1 || true)"
  a="${last%%/*}"; b="${last#*/}"; b="${b%% *}"
  if [ -z "$last" ] || [ "$a" != "$b" ]; then echo "$out"; echo "$v selftest not all passed"; exit 1; fi
  echo "$v selftest $last"
done
echo "bootstrap ok"
