#!/usr/bin/env python3
"""No company branding may re-enter the tree. Exit 1 if it does.

This repo was extracted from an internal app. The scrub was a one-time piece of
work; this gate is what stops it quietly coming back through a copied comment, a
pasted config block or a merge from an internal branch.

Matching is deliberately literal and case-insensitive. Word boundaries matter:
"dsi" must not match "dsimilar", and "estate" must not match "restate" — both of
which produced false positives while writing this.

    python3 scripts/check_branding.py
"""

import os
import re
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Each entry is (regex, why it must not appear).
BANNED = [
    (r"\bdsi\b", "old app prefix"),
    (r"\bdsi[_-]", "old app prefix"),
    (r"\bdss\b", "company abbreviation"),
    (r"dss-erp-help", "internal product code"),
    (r"designershaik", "company domain"),
    (r"\bshaik\b", "company name"),
    (r"shaikh\.world", "internal endpoint"),
    (r"11chsrzwkfxxkc", "internal Drive folder id"),
    (r"\bmarayai\b", "internal project name"),
    (r"\bmajid\b", "internal project name"),
    (r"\bmgos\b", "internal project name"),
    (r"operating model booklet", "internal document"),
    (r"global repository blueprint", "internal document"),
    (r"\berp2\b", "internal hostname"),
]

SKIP_DIRS = {".git", "node_modules", "__pycache__", ".ruff_cache"}
SKIP_EXT = (".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".npy")
# This gate is itself a list of the banned words.
SKIP_FILES = {"scripts/check_branding.py"}


def tracked_files():
    out = subprocess.run(["git", "ls-files"], cwd=REPO, capture_output=True, text=True)
    if out.returncode == 0 and out.stdout.strip():
        return [f for f in out.stdout.split("\n") if f]
    # Not a git checkout (a release tarball): walk instead.
    found = []
    for root, dirs, files in os.walk(REPO):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            found.append(os.path.relpath(os.path.join(root, f), REPO))
    return found


def main():
    patterns = [(re.compile(p, re.IGNORECASE), why) for p, why in BANNED]
    hits = []
    for rel in tracked_files():
        if rel in SKIP_FILES or rel.lower().endswith(SKIP_EXT):
            continue
        path = os.path.join(REPO, rel)
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8") as fh:
                lines = fh.readlines()
        except (UnicodeDecodeError, OSError):
            continue
        for n, line in enumerate(lines, 1):
            for rx, why in patterns:
                if rx.search(line):
                    hits.append((rel, n, why, line.strip()[:110]))

    for rel, n, why, text in hits:
        print("  FAIL %s:%d — %s\n        %s" % (rel, n, why, text))
    if hits:
        print("\nREFUSING: %d branding leak(s). This repo is published; "
              "these must not ship." % len(hits))
        return 1
    print("CHECK_BRANDING OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
