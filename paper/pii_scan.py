#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Scan the run records for e-mail addresses and telephone numbers. Standard library only.

  python paper/pii_scan.py --runs DIR

Reads every record under --runs (request parameters, response body and reply text) and prints each distinct
address-like string with its count in three groups: placeholders (reserved example domains), tokens of the
protocol (an upper-case entity after the at sign, such as @REPO) and the rest, marked CHECK; then each distinct
telephone-like number. Digits inside a longer identifier, such as a request id, are not counted as a number.
"""
import argparse
import collections
import glob
import json
import os
import re

EMAIL = re.compile(r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}(?![A-Za-z0-9-])")
PHONE = re.compile(r"(?<![\w.+-])(?:\+\d{1,3}[ -]?)?(?:\(\d{2,4}\)[ -]?|\d{2,4}[ -])\d{3,4}[ -]\d{4}(?![\w-])")
CN_MOBILE = re.compile(r"(?<![0-9A-Za-z-])1[3-9]\d{9}(?![0-9A-Za-z-])")
RESERVED = ("example.com", "example.org", "example.net", "example.edu", "domain.tld", "domain.com", "email.com",
            "company.com", "test.com", "yourdomain.com", "your-domain.com", "localhost")


def placeholder(addr):
    local, _, domain = addr.lower().partition("@")
    if domain in RESERVED or domain.endswith(".example") or domain.endswith(".test") or domain.endswith(".invalid"):
        return True
    if domain.split(".")[0] in ("example", "domain", "yourcompany", "company", "acme", "corp", "mail", "email"):
        return True
    return False


def protocol_token(addr):
    domain = addr.partition("@")[2]
    return re.match(r"^[A-Z][A-Z0-9_]*[.]", domain) is not None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", required=True)
    a = ap.parse_args()
    emails = collections.Counter()
    where = collections.defaultdict(set)
    phones = collections.Counter()
    files = 0
    for path in glob.glob(os.path.join(a.runs, "*", "*", "*.json")):
        files += 1
        with open(path, encoding="utf-8") as f:
            raw = f.read()
        try:
            text = json.dumps(json.loads(raw), ensure_ascii=False)
        except ValueError:
            text = raw
        text = text.replace("\\n", " ").replace("\\t", " ")
        rel = os.path.relpath(path, a.runs).replace(os.sep, "/")
        for m in EMAIL.finditer(text):
            emails[m.group(0)] += 1
            where[m.group(0)].add(rel)
        for rx in (PHONE, CN_MOBILE):
            for m in rx.finditer(text):
                phones[m.group(0)] += 1
                where[m.group(0)].add(rel)
    def group(k):
        if protocol_token(k):
            return "protocol token"
        return "placeholder" if placeholder(k) else "CHECK"

    groups = collections.Counter(group(k) for k in emails)
    print("records scanned: %d" % files)
    print("distinct address-like strings: %d (placeholders %d, protocol tokens %d, to check %d)" % (
        len(emails), groups["placeholder"], groups["protocol token"], groups["CHECK"]))
    for k, v in sorted(emails.items(), key=lambda kv: -kv[1]):
        print("  %-14s %5d  %s  e.g. %s" % (group(k), v, k, sorted(where[k])[0]))
    print("distinct telephone-like strings: %d" % len(phones))
    for k, v in sorted(phones.items(), key=lambda kv: -kv[1])[:40]:
        print("  %5d  %s  e.g. %s" % (v, k, sorted(where[k])[0]))


if __name__ == "__main__":
    main()
