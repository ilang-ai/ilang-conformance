# -*- coding: utf-8 -*-
"""Shared helpers for the offline unittest suite of ilang-conformance.

Run from the repository root:

    PYTHONIOENCODING=utf-8 python3 -m unittest discover -s tests -v

Importing this module blocks network access in the test process (book §9
no_network_in_tests): socket.socket.connect, socket.socket.connect_ex,
socket.create_connection and socket.getaddrinfo raise NetworkBlocked. The
subprocesses the tests start are the vendored validators and score.py; none of
them opens a socket. Temporary files go to tempfile.TemporaryDirectory() and are
removed; nothing is written into the repository.
"""

import hashlib
import io
import json
import os
import re
import socket
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

FIXTURES = REPO / "tests" / "fixtures"
RUNNER_CASES = FIXTURES / "runner" / "cases"
REAL_CASES = REPO / "cases"
KEY_VARS = ("ORCA_API_KEY", "DEEPSEEK_API_KEY", "ANTHROPIC_API_KEY")
DIMS = ["int", "cap", "csq", "rel", "cer", "aut", "rev", "evd", "sov", "ine", "ext"]


class NetworkBlocked(AssertionError):
    """Raised when code under test tries to open a network connection."""


def _blocked(*args, **kwargs):
    raise NetworkBlocked("network access attempted in an offline test")


socket.socket.connect = _blocked
socket.socket.connect_ex = _blocked
socket.create_connection = _blocked
socket.getaddrinfo = _blocked

import run as runner  # noqa: E402  (after the socket guard)
import score  # noqa: E402


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def canon(obj):
    """book §5.4 / SCHEMA §0.5 canon(obj), written independently of score.py."""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"


def child_env():
    env = {k: v for k, v in os.environ.items() if k not in KEY_VARS}
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def no_transport(url, headers, body, timeout):
    raise NetworkBlocked("the HTTP transport was called in an offline test")


class ScriptedTransport:
    """In-process transport for run.py: replays (status, headers, body) tuples or exceptions."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def __call__(self, url, headers, body, timeout):
        self.calls.append({"url": url, "headers": dict(headers), "body": body, "timeout": timeout})
        if not self.script:
            raise AssertionError("scripted transport exhausted")
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def openai_body(content, finish="stop", model="stub-model-ga"):
    return json.dumps({"id": "x", "model": model, "usage": {"prompt_tokens": 1, "completion_tokens": 1},
                       "choices": [{"index": 0, "finish_reason": finish,
                                    "message": {"role": "assistant", "content": content}}]}).encode("utf-8")


def write_env_file(path, **pairs):
    """An env file of NAME=value lines with mode 600 on POSIX (run.py refuses a wider mode)."""
    path = Path(path)
    path.write_bytes("".join("%s=%s\n" % kv for kv in pairs.items()).encode("utf-8"))
    if os.name == "posix":
        os.chmod(path, 0o600)
    return path


def run_main(argv, vendors_path=None, env_file=None, transport=None):
    """run.py main() in-process with a no-op sleep; returns (exit code, log text). Keys come only
    from env_file, as in run.py."""
    buf = io.StringIO()
    code = runner.main([str(a) for a in argv], out=buf,
                       vendors_path=vendors_path or (REPO / "vendors.json"),
                       env_file=env_file or (REPO / "tests" / "no-such-file.env"),
                       transport=transport or no_transport,
                       sleep=lambda seconds: None)
    return code, buf.getvalue()


def score_cli(args, cwd=None):
    """score.py as a subprocess; returns (exit code, stdout, stderr)."""
    p = subprocess.run([sys.executable, "-B", str(REPO / "score.py")] + [str(a) for a in args],
                       cwd=str(cwd or REPO), env=child_env(), stdin=subprocess.DEVNULL, capture_output=True)
    return p.returncode, p.stdout.decode("utf-8", "replace"), p.stderr.decode("utf-8", "replace")


def tree(root):
    """{posix relative path: bytes} for every file under root."""
    root = Path(root)
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def load_cases(cases_dir, track):
    return runner.load_track(cases_dir, track)


def judge_block(v, mode, conf="0.90", reason="test_reason"):
    """The four lines of a ::JUDGE{v5.0} block for vector v (SCHEMA §2.2 CONTRACT_JUDGE)."""
    return ["::JUDGE{v5.0}",
            "V:[" + ",".join("%s=%.2f" % (d, v[d]) for d in DIMS) + "]",
            "M:%s|conf:%s" % (mode, conf),
            "R:" + reason]


def schema_blocks():
    """({text block name: value}, {regex block name: (pattern, flags line)}) from cases/SCHEMA.md (§0.3, §0.4)."""
    L = (REPO / "cases" / "SCHEMA.md").read_bytes().decode("utf-8").split("\n")
    texts, regexes = {}, {}
    for i, ln in enumerate(L):
        if ln.startswith("````text name="):
            j = L.index("````", i + 1)
            texts[ln[len("````text name="):]] = "\n".join(L[i + 1:j])
        elif ln.startswith("```regex name=") and i + 3 < len(L) and L[i + 2] == "```":
            regexes[ln[len("```regex name="):]] = (L[i + 1], L[i + 3])
    return texts, regexes


def expected_flags(flags_line):
    """Compiled flags implied by a SCHEMA `Flags:` line."""
    flags = 0
    if "re.IGNORECASE" in flags_line:
        flags |= re.IGNORECASE
    if "re.MULTILINE" in flags_line:
        flags |= re.MULTILINE
    flags |= re.ASCII if "re.ASCII" in flags_line else re.UNICODE
    return flags


def floats_in(obj):
    if isinstance(obj, float):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from floats_in(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from floats_in(v)
