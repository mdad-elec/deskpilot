#!/usr/bin/env python3
"""Every dotted reference in hooks.py and patches.txt must resolve inside this repo.

WHY THIS EXISTS
A dotted string in hooks.py or patches.txt is resolved by Frappe at install and
migrate time. If the module it names is not in the repo, `bench install-app`
dies — but only on a clean machine. On a box that already has the old files
sitting outside git, everything keeps working, so the breakage is invisible
exactly where it is being developed and total for everyone else.

Both files have shipped that bug in this repo's history: hooks.py once declared
handlers for modules that had been moved to another app, and patches.txt listed
eleven patch modules that were never in the tree at all.

WHAT IT CHECKS
* hooks.py — parsed with ast (no import, so no frappe and no site needed); every
  string constant that looks like a dotted path into this app must resolve to a
  module in the repo, and the trailing attribute must be defined there at module
  level (def / class / assignment / re-exported import).
* patches.txt — every non-comment, non-section line, same resolution.

Reports every failure, not just the first.

RUN
    python3 scripts/check_refs.py            # from the repo root
    python3 scripts/check_refs.py --verbose  # also list what resolved

Zero dependencies beyond the stdlib, and it neither imports the app nor needs a
site, on purpose: a gate that needs a built environment is a gate that gets
skipped. The app package is discovered, not hardcoded.
"""

import ast
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def find_app():
	"""The app package = the one directory holding hooks.py. Not hardcoded, so this
	app package is discovered rather than hardcoded, so this file is portable."""
	hits = sorted(d for d in os.listdir(REPO)
	              if os.path.exists(os.path.join(REPO, d, "hooks.py")))
	if len(hits) != 1:
		print("FAIL: expected exactly one */hooks.py under %s, found %s" % (REPO, hits))
		sys.exit(1)
	return hits[0]


APP = find_app()
HOOKS = os.path.join(REPO, APP, "hooks.py")
PATCHES = os.path.join(REPO, APP, "patches.txt")

# "<app>.tasks.warm" -> module "<app>/tasks.py", attribute "warm".
# Also matches deeper paths: "<app>.api.chat.ask" -> <app>/api/chat.py.
DOTTED = re.compile(r"^%s\.[A-Za-z_][A-Za-z0-9_.]*$" % re.escape(APP))


def dotted_strings(tree):
	"""Every string constant in the file that looks like a path into this app."""
	found = []
	for node in ast.walk(tree):
		if isinstance(node, ast.Constant) and isinstance(node.value, str):
			if DOTTED.match(node.value):
				found.append((node.value, node.lineno))
	return sorted(set(found))


def module_candidates(dotted):
	"""(module_path, attribute) pairs to try, longest module first.

	`a.b.c` is ambiguous: it can be attribute c of module a/b.py, or module
	a/b/c.py (a hook value may legitimately be a module, e.g. a jinja filters
	module). Try the longest module path first so a real package wins.
	"""
	parts = dotted.split(".")
	out = []
	for cut in range(len(parts), 0, -1):
		rel = os.path.join(*parts[:cut])
		attr = ".".join(parts[cut:]) or None
		for path in (os.path.join(REPO, rel + ".py"), os.path.join(REPO, rel, "__init__.py")):
			if os.path.exists(path):
				out.append((path, attr))
	return out


def defines(path, attr):
	"""Is `attr` defined at module level in `path`? Nested attrs are not checked."""
	if attr is None:
		return True
	if "." in attr:                      # e.g. Class.method — resolve the head only
		attr = attr.split(".")[0]
	try:
		tree = ast.parse(open(path, encoding="utf-8").read(), filename=path)
	except SyntaxError as e:
		print("SYNTAX ERROR in %s: %s" % (os.path.relpath(path, REPO), e))
		return False
	for node in tree.body:
		if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
			if node.name == attr:
				return True
		elif isinstance(node, ast.Assign):
			for t in node.targets:
				if isinstance(t, ast.Name) and t.id == attr:
					return True
		elif isinstance(node, ast.AnnAssign):
			if isinstance(node.target, ast.Name) and node.target.id == attr:
				return True
		elif isinstance(node, (ast.Import, ast.ImportFrom)):
			for a in node.names:
				if (a.asname or a.name.split(".")[0]) == attr:
					return True     # re-exported import
	return False


def patch_refs():
	"""Every real entry in patches.txt, as (dotted, lineno).

	Lines are bare dotted paths. Blank lines, `#` comments and `[section]` headers
	are structure, not references. An `execute:` line is arbitrary python rather
	than a module path, so it is out of scope here.
	"""
	if not os.path.exists(PATCHES):
		return []
	out = []
	for i, line in enumerate(open(PATCHES, encoding="utf-8"), 1):
		ref = line.strip()
		if not ref or ref.startswith("#") or ref.startswith("[") or ref.startswith("execute:"):
			continue
		out.append((ref, i))
	return out


def main():
	verbose = "--verbose" in sys.argv
	if not os.path.exists(HOOKS):
		print("FAIL: no %s" % HOOKS)
		return 1
	tree = ast.parse(open(HOOKS, encoding="utf-8").read(), filename=HOOKS)
	refs = [(r, "hooks.py:%d" % n) for r, n in dotted_strings(tree)]
	refs += [(r, "patches.txt:%d" % n) for r, n in patch_refs()]
	if not refs:
		print("check_refs: no %s.* references to resolve" % APP)
		return 0

	bad = []
	for ref, where in refs:
		hit = None
		for path, attr in module_candidates(ref):
			if defines(path, attr):
				hit = (path, attr)
				break
		if hit:
			if verbose:
				print("  OK   %-58s %-16s -> %s" % (ref, where, os.path.relpath(hit[0], REPO)))
		else:
			cands = module_candidates(ref)
			why = ("no module for it in the repo" if not cands
			       else "module %s has no %s" % (os.path.relpath(cands[0][0], REPO), cands[0][1]))
			print("  FAIL %-58s %-16s — %s" % (ref, where, why))
			bad.append(ref)

	print("check_refs: %d/%d references resolve in %s" % (len(refs) - len(bad), len(refs), APP))
	if bad:
		print("REFUSING: %d unresolvable reference(s). `bench install-app %s` would "
		      "fail on a box without leftover files." % (len(bad), APP))
		return 1
	print("CHECK_REFS OK")
	return 0


if __name__ == "__main__":
	sys.exit(main())
