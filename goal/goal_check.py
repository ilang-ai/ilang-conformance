#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""goal_check.py: checks the acceptance items of an engineering book written in iLang.

It reads the ::RUBRIC declarations of the book, runs every item that carries an executable check, and
exits with 0 only when every item passes. A loop that works towards the book can run it after each round
and stop on the exit code.

An item without an executable check is a judgment that code cannot make. It stays `unknown` until a
person confirms it, and `unknown` never counts as done (SPEC-v4.0 section 5). An item whose premise is
wrong can be disputed: the loop then stops and the item goes to the owner of the book, instead of
failing for ever.

Exit codes
  0  every item passes
  1  at least one item fails
  2  nothing fails, and at least one item waits for a person
  3  the book cannot be checked: no rubric, an item named twice, a check that is not well formed

Usage
  python goal/goal_check.py BOOK [--records FILE] [--root DIR] [--allow-cmd] [--allow-private]
                                 [--timeout S] [--cmd-timeout S] [--log FILE | --no-log] [--json]
  python goal/goal_check.py BOOK --list

Standard library only. Python 3.12 or later.
"""

import argparse
import hashlib
import ipaddress
import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

VERSION = "0.1.0"
USER_AGENT = "ilang-goal-check/%s (+https://github.com/ilang-ai/ilang-conformance)" % VERSION
MAX_BYTES = 5 * 1024 * 1024
MAX_LINKS = 200
SPAN_LINES = 20
KINDS = ("status", "count", "json", "links", "file", "cmd", "human")
PASS, FAIL, UNKNOWN = "pass", "fail", "unknown"
EXIT_PASS, EXIT_FAIL, EXIT_WAIT, EXIT_BOOK = 0, 1, 2, 3
NOT_A_PERSON = ("@AGENT", "@SELF", "@TOOL")
READ = ("RUBRIC", "EVIDENCE", "STATUS")

RE_DECL_OPEN = re.compile(r"^\s*::([A-Z][A-Z0-9_]*)\{(.*)$", re.S)
RE_ROW = re.compile(r"^\s+R:(.+)$")
RE_KEY = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*:(.*)$", re.S)
RE_EXPECT = re.compile(r"^(>=|<=|==|=|>|<)?\s*(-?[0-9]+)$")
RE_BOOK_ID = re.compile(r"^\[ID:([^\[\]]+)\]\s*$")
RE_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class CheckError(Exception):
    """The check was made and could not reach what it has to look at. The item fails."""


class Blocked(Exception):
    """The check was not allowed to run. The item stays unknown."""


class BookError(Exception):
    """The book cannot be checked."""


# ------------------------------------------------------------------------------------------- reading

def mask_quoted(s):
    """The rule of the grammar validator (v3.0 section 2.4): a quote opens a value only right after
    `:`, `=` or `,`, and nothing inside a quoted value is syntax. Positions are kept. A line with a
    quote that never closes is returned as it is."""
    out, quoted, escaped = [], False, False
    for k, ch in enumerate(s):
        if quoted:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                quoted = False
                out.append(ch)
                continue
            out.append("_")
            continue
        if ch == '"' and k > 0 and s[k - 1] in "=:,":
            quoted = True
        out.append(ch)
    return s if quoted else "".join(out)


def unquote(value):
    """A value without its quotes; the three escapes of section 2.4 are read, any other backslash
    stays, so a regular expression can be written as it is."""
    v = value.strip()
    if len(v) < 2 or v[0] != '"' or v[-1] != '"':
        return v
    body, out, i = v[1:-1], [], 0
    while i < len(body):
        ch = body[i]
        if ch == "\\" and i + 1 < len(body) and body[i + 1] in '"\\n':
            out.append({'"': '"', "\\": "\\", "n": "\n"}[body[i + 1]])
            i += 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def split_fields(inner):
    """The fields of one declaration as (key, value) pairs, cut on `|` outside quoted values. A piece
    that does not begin with `key:` continues the value before it; a first piece without a key has
    the key ''."""
    masked = mask_quoted(inner)
    pieces, start = [], 0
    for k, ch in enumerate(masked):
        if ch == "|":
            pieces.append(inner[start:k])
            start = k + 1
    pieces.append(inner[start:])
    fields = []
    for piece in pieces:
        m = RE_KEY.match(piece)
        if m:
            fields.append([m.group(1), m.group(2)])
        elif fields:
            fields[-1][1] += "|" + piece
        else:
            fields.append(["", piece])
    return [(k, unquote(v)) for k, v in fields]


def closes(text):
    """True when the brace opened by a declaration closes at the end of text."""
    masked = mask_quoted(text).rstrip()
    return masked.endswith("}")


def declarations(text):
    """Yields (name, inner, rows, line) for every ::RUBRIC, ::EVIDENCE and ::STATUS of the text.
    rows are the `R:` lines under a ::RUBRIC header. What stands between ::UNTRUSTED and
    ::END_UNTRUSTED is not read: content from outside cannot set the acceptance of the book. An
    ::UNTRUSTED that points to an external payload opens no block (SPEC-v4.0 section 1). A block that
    never closes stops the reading, so that the items after it are not dropped without a word."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    i, n, untrusted = 0, len(lines), 0
    while i < n:
        line = lines[i]
        stripped = line.strip()
        if stripped.startswith("::END_UNTRUSTED"):
            untrusted = 0
            i += 1
            continue
        if untrusted:
            i += 1
            continue
        if stripped.startswith("::UNTRUSTED"):
            head = RE_DECL_OPEN.match(stripped)
            fields = dict(split_fields(head.group(2).rstrip().rstrip("}"))) if head else {}
            if fields.get("payload", "").strip() != "external":
                untrusted = i + 1
            i += 1
            continue
        m = RE_DECL_OPEN.match(line)
        if not m or m.group(1) not in READ:
            i += 1
            continue
        name, first, span = m.group(1), i + 1, line
        while not closes(span) and i + 1 < n and i + 1 - first < SPAN_LINES and lines[i + 1].strip():
            i += 1
            span += " " + lines[i].strip()
        if not closes(span):
            raise BookError("line %d: ::%s never closes" % (first, name))
        inner = RE_DECL_OPEN.match(span).group(2).rstrip()[:-1]
        rows = []
        while name == "RUBRIC" and i + 1 < n and RE_ROW.match(lines[i + 1]):
            i += 1
            rows.append((RE_ROW.match(lines[i]).group(1).strip(), i + 1))
        yield name, inner, rows, first
        i += 1
    if untrusted:
        raise BookError("line %d: ::UNTRUSTED never closes with ::END_UNTRUSTED" % untrusted)


def make_item(ident, text, fields, line, rubric):
    given = {}
    for k, v in fields:
        if k:
            given[k] = v
    check = given.pop("check", "")
    weight = given.pop("weight", None)
    given.pop("text", None)
    return {"id": ident, "text": text, "rubric": rubric, "line": line, "weight": weight,
            "check": check, "kind": check if check in KINDS else None, "fields": given}


def read_book(text, records=()):
    """The items of the book and the records that bear on them. records are further texts, of which
    only ::EVIDENCE and ::STATUS are read."""
    book = {"id": None, "items": [], "confirmations": {}, "disputes": {}, "problems": []}
    for line in text.replace("\r\n", "\n").split("\n")[:40]:
        m = RE_BOOK_ID.match(line.strip())
        if m:
            book["id"] = m.group(1).strip()
            break
    sources = [(text, True)] + [(r, False) for r in records]
    for source, is_book in sources:
        for name, inner, rows, line in declarations(source):
            fields = split_fields(inner)
            if name == "RUBRIC" and is_book:
                head_key, head_value = fields[0]
                if head_key == "id" or rows:
                    rubric = dict(fields).get("id", "")
                    for row, row_line in rows:
                        row_fields = split_fields(row)
                        ident = row_fields[0][1].strip() if row_fields[0][0] == "" else ""
                        text_of = dict(row_fields).get("text", ident)
                        book["items"].append(make_item(ident, text_of, row_fields[1:], row_line, rubric))
                    if not rows:
                        book["problems"].append("line %d: this ::RUBRIC has no R: row under it" % line)
                else:
                    if head_key == "" and ":" in head_value:
                        head_key, head_value = (part.strip() for part in head_value.split(":", 1))
                    book["items"].append(make_item(head_key, head_value.strip(), fields[1:], line, ""))
            elif name == "EVIDENCE":
                f = dict(fields)
                who = f.get("verified_by", "").strip()
                if (f.get("kind") == "manual_check" and f.get("deliverable") and who
                        and who not in NOT_A_PERSON and f.get("result") in (PASS, FAIL)):
                    book["confirmations"][f["deliverable"].strip()] = {
                        "verified_by": who, "result": f["result"], "ref": f.get("ref", ""), "line": line}
            elif name == "STATUS":
                f = dict(fields)
                if f.get("state") == "blocked" and f.get("item"):
                    book["disputes"][f["item"].strip()] = {
                        "by": f.get("by", ""), "need": f.get("need", ""), "detail": f.get("detail", ""),
                        "line": line}
    seen = {}
    for item in book["items"]:
        if not item["id"]:
            book["problems"].append("line %d: the item has no name; an item is written `NAME: sentence` or as an "
                                    "`R:NAME` row under a ::RUBRIC header" % item["line"])
            continue
        if item["id"] in seen:
            book["problems"].append("line %d: item %s is already named on line %d"
                                    % (item["line"], item["id"], seen[item["id"]]))
        seen.setdefault(item["id"], item["line"])
        for problem in problems_of(item):
            book["problems"].append("line %d: item %s: %s" % (item["line"], item["id"], problem))
    if not book["items"]:
        book["problems"].append("the book has no ::RUBRIC item")
    return book


def parse_expect(value, default):
    s = (value if value not in (None, "") else default).strip()
    m = RE_EXPECT.match(s)
    if not m:
        raise ValueError("expect is neither a number nor a comparison: %s" % s)
    op = m.group(1) or "="
    return ("=" if op == "==" else op), int(m.group(2))


def holds(value, expect):
    op, n = expect
    return {"=": value == n, ">=": value >= n, "<=": value <= n, ">": value > n, "<": value < n}[op]


def show(expect):
    op, n = expect
    return str(n) if op == "=" else "%s%d" % (op, n)


def problems_of(item):
    """What is wrong with the way the check of an item is written. An item without a check, or with a
    check that names no kind of this program, has nothing wrong: it waits for a person."""
    kind, f, out = item["kind"], item["fields"], []
    if kind in (None, "human"):
        return out
    if kind in ("status", "count", "json", "links"):
        has_url, has_path = "url" in f, "path" in f
        if kind == "status":
            if not has_url:
                out.append("status needs url")
        elif has_url == has_path:
            out.append("%s needs url or path, one of the two" % kind)
        if has_url and urllib.parse.urlsplit(f["url"]).scheme not in ("http", "https"):
            out.append("url is not an http or https address")
    if kind in ("file",) and "path" not in f:
        out.append("file needs path")
    if "path" in f and kind != "cmd":
        p = f["path"].replace("\\", "/")
        if p.startswith("/") or re.match(r"^[A-Za-z]:", p) or ".." in p.split("/"):
            out.append("path has to be relative and stay under the root")
    try:
        if kind == "status":
            parse_expect(f.get("expect"), "200")
        elif kind == "count":
            parse_expect(f.get("expect"), ">=1")
        elif kind == "cmd":
            parse_expect(f.get("expect"), "0")
        elif kind == "json" and f.get("expect"):
            parse_expect(f.get("expect"), "")
    except ValueError as e:
        out.append(str(e))
    if kind == "count":
        if ("pattern" in f) == ("regex" in f):
            out.append("count needs pattern or regex, one of the two")
        if "regex" in f:
            try:
                re.compile(f["regex"])
            except re.error as e:
                out.append("regex does not compile: %s" % e)
        if f.get("in", "source") not in ("source", "text"):
            out.append("in is source or text")
    if kind == "json":
        if f.get("in", "document") not in ("document", "jsonld"):
            out.append("in is document or jsonld")
        if f.get("expect") and f.get("in") != "jsonld":
            out.append("expect counts the blocks and needs in:jsonld")
    if kind == "links":
        if not all(re.match(r"^[0-9]{3}$", a.strip()) for a in f.get("allow", "").split(",") if a.strip()):
            out.append("allow is a list of status codes")
        if f.get("scope", "external") not in ("external", "all"):
            out.append("scope is external or all")
    if kind == "file" and f.get("sha256") and not RE_SHA256.match(f["sha256"].strip().lower()):
        out.append("sha256 is 64 hexadecimal digits")
    if kind == "cmd" and not f.get("run", "").strip():
        out.append("cmd needs run")
    return out


def rubric_hash(items):
    """A hash of the items alone, so that a change of the acceptance between two runs shows in the log
    whatever else changed in the book."""
    rows = [{"id": i["id"], "text": i["text"], "check": i["check"], "fields": i["fields"]} for i in items]
    data = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


# ------------------------------------------------------------------------------------------ fetching

def resolve_host(host):
    return sorted({info[4][0] for info in socket.getaddrinfo(host, None)})


def address_is_public(host, resolve=resolve_host):
    """False when the host is, or resolves to, an address that is not a public one: a private network,
    this machine, a link-local address such as the metadata service of a cloud."""
    try:
        addresses = [str(ipaddress.ip_address(host))]
    except ValueError:
        addresses = list(resolve(host))
    if not addresses:
        return False
    for a in addresses:
        ip = ipaddress.ip_address(a.split("%")[0])
        if not ip.is_global or ip.is_multicast:
            return False
    return True


class GuardedRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self, guard):
        self.guard = guard

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        self.guard(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def make_fetch(allow_private=False, resolve=resolve_host, max_bytes=MAX_BYTES):
    """fetch(url, timeout) -> {status, body, url, charset}. One GET, redirects followed, each address
    on the way held against the rule on private addresses."""

    def guard(url):
        parts = urllib.parse.urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise CheckError("not an http or https address: %s" % url)
        if allow_private:
            return
        try:
            public = address_is_public(parts.hostname, resolve)
        except OSError as e:
            raise CheckError("the name %s does not resolve: %s" % (parts.hostname, e))
        if not public:
            raise Blocked("%s is a private or local address; --allow-private lets the check run"
                          % parts.hostname)

    opener = urllib.request.build_opener(GuardedRedirect(guard))

    def fetch(url, timeout):
        guard(url)
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
        try:
            with opener.open(request, timeout=timeout) as r:
                body, status, final = r.read(max_bytes + 1), r.status, r.geturl()
                charset = r.headers.get_content_charset()
        except urllib.error.HTTPError as e:
            try:
                body = e.read(max_bytes + 1)
            except (OSError, AttributeError):
                body = b""
            status, final = e.code, e.geturl() or url
            charset = e.headers.get_content_charset() if e.headers else None
        except (urllib.error.URLError, OSError, ValueError) as e:
            raise CheckError("no answer from %s: %s" % (url, getattr(e, "reason", e)))
        if len(body) > max_bytes:
            raise CheckError("the answer of %s is larger than %d bytes" % (url, max_bytes))
        return {"status": status, "body": body, "url": final, "charset": charset}

    return fetch


def run_command(command, cwd, timeout):
    """(exit code, output). The command line is given to the shell of the machine as it is written."""
    try:
        p = subprocess.run(command, shell=True, cwd=str(cwd), capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise CheckError("the command did not end within %d seconds" % timeout)
    return p.returncode, (p.stdout + p.stderr).decode("utf-8", "replace")


class Page(HTMLParser):
    """The text a reader sees, the links and the JSON-LD blocks of an HTML page."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.text, self.links, self.jsonld = [], [], []
        self.skip, self.block = 0, None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "script":
            if (a.get("type") or "").strip().lower() == "application/ld+json":
                self.block = []
            self.skip += 1
        elif tag == "style":
            self.skip += 1
        elif tag == "a" and a.get("href"):
            self.links.append(a["href"].strip())

    def handle_endtag(self, tag):
        if tag == "script":
            if self.block is not None:
                self.jsonld.append("".join(self.block))
                self.block = None
            self.skip = max(0, self.skip - 1)
        elif tag == "style":
            self.skip = max(0, self.skip - 1)

    def handle_data(self, data):
        if self.block is not None:
            self.block.append(data)
        elif not self.skip:
            self.text.append(data)


def page_of(text):
    page = Page()
    page.feed(text)
    page.close()
    return page


# ------------------------------------------------------------------------------------------ checking

class Context:
    def __init__(self, root=".", fetch=None, run=run_command, allow_cmd=False, allow_private=False,
                 timeout=30, cmd_timeout=600):
        self.root = Path(root)
        self.fetch = fetch or make_fetch(allow_private=allow_private)
        self.run = run
        self.allow_cmd, self.allow_private = allow_cmd, allow_private
        self.timeout, self.cmd_timeout = timeout, cmd_timeout


def under_root(root, relative):
    base = root.resolve()
    p = (base / relative).resolve()
    if p != base and base not in p.parents:
        raise CheckError("the path %s leaves the root" % relative)
    return p


def source_of(item, ctx):
    """(text, address) of what a count, json or links check looks at. A page that does not answer 200
    is not read: an error page holds none of the words a check looks for, and a count of zero on it
    would pass for the wrong reason."""
    f = item["fields"]
    if "url" in f:
        r = ctx.fetch(f["url"], ctx.timeout)
        if r["status"] != 200:
            raise CheckError("%s answered %d" % (f["url"], r["status"]))
        return r["body"].decode(r.get("charset") or "utf-8", "replace"), r["url"]
    p = under_root(ctx.root, f["path"])
    if not p.is_file():
        raise CheckError("no file %s under the root" % f["path"])
    if p.stat().st_size > MAX_BYTES:
        raise CheckError("the file %s is larger than %d bytes" % (f["path"], MAX_BYTES))
    return p.read_bytes().decode("utf-8", "replace"), None


def check_status(item, ctx):
    f = item["fields"]
    expect = parse_expect(f.get("expect"), "200")
    r = ctx.fetch(f["url"], ctx.timeout)
    observed = {"status": r["status"]}
    if r["url"] != f["url"]:
        observed["final_url"] = r["url"]
    return holds(r["status"], expect), observed, "status " + show(expect), ""


def check_count(item, ctx):
    f = item["fields"]
    expect = parse_expect(f.get("expect"), ">=1")
    text, _ = source_of(item, ctx)
    if f.get("in") == "text":
        text = "".join(page_of(text).text)
    if "regex" in f:
        n = sum(1 for _ in re.finditer(f["regex"], text))
    else:
        n = text.count(f["pattern"])
    return holds(n, expect), {"count": n}, "count " + show(expect), ""


def check_json(item, ctx):
    f = item["fields"]
    text, _ = source_of(item, ctx)
    if f.get("in") != "jsonld":
        try:
            json.loads(text)
        except ValueError as e:
            return False, {"valid": False}, "the document parses", str(e)
        return True, {"valid": True}, "the document parses", ""
    blocks = page_of(text).jsonld
    valid, first = 0, ""
    for block in blocks:
        try:
            json.loads(block)
            valid += 1
        except ValueError as e:
            first = first or str(e)
    expect = parse_expect(f.get("expect"), ">=1")
    ok = valid == len(blocks) and holds(len(blocks), expect)
    return ok, {"blocks": len(blocks), "valid": valid}, "every block parses, blocks " + show(expect), first


def check_links(item, ctx):
    f = item["fields"]
    text, address = source_of(item, ctx)
    allow = {int(a) for a in f.get("allow", "").split(",") if a.strip()}
    host = urllib.parse.urlsplit(address).hostname if address else None
    links = []
    for href in page_of(text).links:
        url = urllib.parse.urldefrag(urllib.parse.urljoin(address, href) if address else href)[0]
        parts = urllib.parse.urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            continue
        if f.get("scope", "external") == "external" and host and parts.hostname == host:
            continue
        if url not in links:
            links.append(url)
    if len(links) > MAX_LINKS:
        raise CheckError("the page has %d links, more than %d" % (len(links), MAX_LINKS))
    failing, let_through = [], []
    for url in links:
        try:
            status = ctx.fetch(url, ctx.timeout)["status"]
        except (CheckError, Blocked) as e:
            failing.append({"url": url, "error": str(e)})
            continue
        if status >= 400:
            (let_through if status in allow else failing).append({"url": url, "status": status})
    expected = "every link answers below 400" + (" or %s" % ",".join(map(str, sorted(allow))) if allow else "")
    observed = {"links": len(links), "failing": failing}
    if let_through:
        observed["let_through"] = let_through
    return not failing, observed, expected, ""


def check_file(item, ctx):
    f = item["fields"]
    p = under_root(ctx.root, f["path"])
    if not p.is_file():
        return False, {"exists": False}, "the file exists", ""
    if not f.get("sha256"):
        return True, {"exists": True}, "the file exists", ""
    digest = hashlib.sha256(p.read_bytes()).hexdigest()
    return digest == f["sha256"].strip().lower(), {"exists": True, "sha256": digest}, "sha256 " + f["sha256"][:12], ""


def check_cmd(item, ctx):
    f = item["fields"]
    if not ctx.allow_cmd:
        raise Blocked("commands are off; --allow-cmd lets the check run")
    expect = parse_expect(f.get("expect"), "0")
    code, output = ctx.run(f["run"], ctx.root, ctx.cmd_timeout)
    observed, ok, expected = {"exit": code}, holds(code, expect), "exit " + show(expect)
    if "stdout" in f:
        observed["found"] = f["stdout"] in output
        ok = ok and observed["found"]
        expected += ", output holds the text"
    return ok, observed, expected, "" if ok else output.strip()[-300:]


RUNNERS = {"status": check_status, "count": check_count, "json": check_json, "links": check_links,
           "file": check_file, "cmd": check_cmd}


def check_item(item, book, ctx):
    started = time.monotonic()
    result = {"id": item["id"], "kind": item["kind"] or "none", "text": item["text"], "verdict": UNKNOWN,
              "reason": "", "expect": "", "observed": {}, "tail": ""}
    if item["kind"] in (None, "human"):
        confirmed = book["confirmations"].get(item["id"])
        if confirmed:
            result["verdict"] = confirmed["result"]
            result["reason"] = "stated by %s" % confirmed["verified_by"]
            result["observed"] = {"ref": confirmed["ref"]}
        else:
            result["reason"] = "no executable check; waits for a person"
    else:
        try:
            ok, result["observed"], result["expect"], result["tail"] = RUNNERS[item["kind"]](item, ctx)
            result["verdict"] = PASS if ok else FAIL
        except Blocked as e:
            result["reason"] = "not run: %s" % e
        except CheckError as e:
            result["verdict"], result["reason"] = FAIL, str(e)
    dispute = book["disputes"].get(item["id"])
    if dispute and result["verdict"] != PASS:
        result["under_dispute"] = result["verdict"]
        result["verdict"] = UNKNOWN
        result["reason"] = "disputed by %s: %s" % (dispute["by"] or "?", dispute["detail"] or dispute["need"])
    result["seconds"] = round(time.monotonic() - started, 3)
    return result


def check_book(book, ctx):
    results = [check_item(item, book, ctx) for item in book["items"]]
    counts = {v: sum(1 for r in results if r["verdict"] == v) for v in (PASS, FAIL, UNKNOWN)}
    code = EXIT_FAIL if counts[FAIL] else EXIT_WAIT if counts[UNKNOWN] else EXIT_PASS
    return results, counts, code


# ----------------------------------------------------------------------------------------- reporting

def last_run(log, book_key):
    if not log or not Path(log).is_file():
        return None
    found = None
    for line in Path(log).read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if row.get("book_key") == book_key:
            found = row
    return found


def observed_text(result):
    o = result["observed"]
    if result["kind"] == "links" and o:
        bad = ", ".join("%s (%s)" % (x["url"], x.get("status", x.get("error"))) for x in o["failing"])
        let = ", ".join("%s (%s)" % (x["url"], x["status"]) for x in o.get("let_through", []))
        return "%d links" % o["links"] + (", let through: " + let if let else "") + (", not answering: " + bad if bad else "")
    return ", ".join("%s %s" % (k, v) for k, v in o.items())


def table(record):
    out = ["goal-check %s | %s | %d items | rubric %s" % (record["version"], record["book"],
                                                        len(record["items"]), record["rubric_sha256"][:12])]
    if record.get("rubric_changed"):
        out.append("note: the items changed since the run of %s" % record["previous_time"])
    width = max(len(r["id"]) for r in record["items"])
    for r in record["items"]:
        said = observed_text(r)
        parts = [p for p in (said and "saw %s" % said, r["expect"] and "wants %s" % r["expect"], r["reason"]) if p]
        out.append("  %-*s  %-7s  %-6s  %s" % (width, r["id"], r["verdict"], r["kind"], "; ".join(parts)))
        if r["tail"] and r["verdict"] != PASS:
            out.append("  %-*s           %s" % (width, "", r["tail"].replace("\n", " | ")))
    c = record["counts"]
    out.append("%d pass, %d fail, %d wait for a person" % (c[PASS], c[FAIL], c[UNKNOWN]))
    return "\n".join(out)


def listing(book, path):
    out = ["%s | %d items" % (path, len(book["items"]))]
    for item in book["items"]:
        fields = " ".join("%s=%s" % (k, json.dumps(v, ensure_ascii=False)) for k, v in item["fields"].items())
        kind = item["kind"] or ("none (check:%s names no kind)" % item["check"] if item["check"] else "none")
        out.append("  %s  %s  %s" % (item["id"], kind, fields))
    for ident, d in book["disputes"].items():
        out.append("  disputed: %s by %s: %s" % (ident, d["by"] or "?", d["detail"] or d["need"]))
    for ident, c in book["confirmations"].items():
        out.append("  stated by %s: %s %s" % (c["verified_by"], ident, c["result"]))
    return "\n".join(out)


def main(argv=None, fetch=None, run=run_command, now=None):
    ap = argparse.ArgumentParser(prog="goal_check.py", description="Checks the ::RUBRIC of an engineering book.")
    ap.add_argument("book")
    ap.add_argument("--records", action="append", default=[], metavar="FILE",
                    help="a file of ::EVIDENCE and ::STATUS lines kept apart from the book")
    ap.add_argument("--root", default=".", help="directory that path and run are relative to")
    ap.add_argument("--allow-cmd", action="store_true", help="run the commands the book names")
    ap.add_argument("--allow-private", action="store_true", help="let checks reach private and local addresses")
    ap.add_argument("--timeout", type=int, default=30)
    ap.add_argument("--cmd-timeout", type=int, default=600)
    ap.add_argument("--log", default=None, help="where each run is recorded; BOOK.goal-log.jsonl when absent")
    ap.add_argument("--no-log", action="store_true")
    ap.add_argument("--json", action="store_true", help="print the record of the run instead of the table")
    ap.add_argument("--list", action="store_true", help="show the items and what would run, and run nothing")
    args = ap.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    try:
        raw = Path(args.book).read_bytes()
        text = raw.decode("utf-8")
        records = [Path(p).read_text(encoding="utf-8") for p in args.records]
        book = read_book(text, records)
    except (OSError, UnicodeDecodeError, BookError) as e:
        print("goal-check: %s" % e, file=sys.stderr)
        return EXIT_BOOK
    if book["problems"]:
        for problem in book["problems"]:
            print("goal-check: %s" % problem, file=sys.stderr)
        return EXIT_BOOK
    if args.list:
        print(listing(book, args.book))
        return EXIT_PASS

    ctx = Context(root=args.root, fetch=fetch or make_fetch(allow_private=args.allow_private), run=run,
                  allow_cmd=args.allow_cmd, allow_private=args.allow_private,
                  timeout=args.timeout, cmd_timeout=args.cmd_timeout)
    results, counts, code = check_book(book, ctx)
    log = None if args.no_log else (args.log or args.book + ".goal-log.jsonl")
    book_key = book["id"] or Path(args.book).name
    record = {"tool": "goal-check", "version": VERSION,
              "time": now or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
              "book": Path(args.book).name, "book_key": book_key,
              "book_sha256": hashlib.sha256(raw).hexdigest(), "rubric_sha256": rubric_hash(book["items"]),
              "allow_cmd": args.allow_cmd, "allow_private": args.allow_private,
              "items": results, "counts": counts, "exit": code}
    weights = [i["weight"] for i in book["items"]]
    if all(w is not None for w in weights):
        try:
            total = sum(float(w) for w in weights)
            passed = sum(float(i["weight"]) for i, r in zip(book["items"], results) if r["verdict"] == PASS)
            record["score"] = round(passed / total, 4) if total else 0.0
        except ValueError:
            pass
    before = last_run(log, book_key)
    if before and before.get("rubric_sha256") != record["rubric_sha256"]:
        record["rubric_changed"], record["previous_time"] = True, before.get("time")
    print(json.dumps(record, ensure_ascii=False, indent=1, sort_keys=True) if args.json else table(record))
    if log:
        logged = dict(record, items=[{k: v for k, v in r.items() if k != "tail"} for r in results])
        with open(log, "a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(logged, ensure_ascii=False, sort_keys=True) + "\n")
    return code


if __name__ == "__main__":
    sys.exit(main())
