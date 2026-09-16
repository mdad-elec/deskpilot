"""A `frappe` stand-in, just big enough to import deskpilot modules off-bench.

This is not a simulation of Frappe. It exists so the pure logic in this app —
settings resolution, text extraction, id parsing, denylist matching — can be
tested by anything that can run python, with no bench, site or database. Import
this before any `deskpilot` import.

Every test module calls install(); the first one wins and the rest get the same
object, so test ordering does not matter.
"""

import sys
import types


def reset(frappe=None):
    """Return the stub to its default state.

    Every test setUp must call this. The stub is a module-level singleton shared
    by every test file, so a test that leaves frappe.local.db set to None (a
    legitimate thing to test) would otherwise silently break unrelated tests in
    another file, depending on discovery order.
    """
    frappe = frappe or sys.modules["frappe"]
    frappe.conf = {}
    frappe.local = types.SimpleNamespace(db=object(), site="test")
    frappe._doc = None
    frappe._doctype_exists = True
    frappe._roles = ["System Manager"]
    frappe.get_cached_doc = lambda dt: frappe._doc
    frappe.get_single = lambda dt: frappe._doc
    return frappe


def install():
    """Install (or return the already-installed) frappe stub."""
    existing = sys.modules.get("frappe")
    if isinstance(existing, types.ModuleType) and getattr(existing, "_deskpilot_stub", False):
        return existing

    frappe = types.ModuleType("frappe")
    frappe._deskpilot_stub = True

    # --- state the tests drive
    frappe.conf = {}
    frappe.local = types.SimpleNamespace(db=object(), site="test")
    frappe._doc = None
    frappe._doctype_exists = True
    frappe._roles = ["System Manager"]

    # --- db
    class _DB:
        @staticmethod
        def exists(doctype, name=None):
            return frappe._doctype_exists

        @staticmethod
        def get_value(*a, **k):
            return None

    frappe.db = _DB()
    frappe.get_cached_doc = lambda dt: frappe._doc
    frappe.get_single = lambda dt: frappe._doc
    frappe.get_doc = lambda *a, **k: frappe._doc
    frappe.get_all = lambda *a, **k: []
    frappe.get_roles = lambda *a, **k: frappe._roles

    # --- no-ops: the tests never assert on these
    frappe.whitelist = lambda *a, **k: (lambda fn: fn)
    frappe.only_for = lambda *a, **k: None
    frappe.log_error = lambda *a, **k: None
    frappe.logger = lambda *a, **k: types.SimpleNamespace(
        info=lambda *a, **k: None, warning=lambda *a, **k: None)
    frappe.get_traceback = lambda *a, **k: ""
    frappe.clear_cache = lambda *a, **k: None
    frappe.msgprint = lambda *a, **k: None
    frappe.publish_realtime = lambda *a, **k: None
    frappe._ = lambda s, *a, **k: s
    frappe.get_site_path = lambda *parts: "/tmp/deskpilot-test/" + "/".join(parts)
    frappe.cache = lambda: types.SimpleNamespace(
        get_value=lambda *a, **k: None,
        set_value=lambda *a, **k: None,
        delete_value=lambda *a, **k: None,
    )
    frappe.utils = types.SimpleNamespace(
        now=lambda: "2026-01-01 00:00:00",
        escape_html=lambda s: s,
        get_request_site_address=lambda full=False: "https://test.local",
    )

    class PermissionError_(Exception):
        pass

    class ValidationError(Exception):
        pass

    class DoesNotExistError(Exception):
        pass

    frappe.PermissionError = PermissionError_
    frappe.ValidationError = ValidationError
    frappe.DoesNotExistError = DoesNotExistError

    def _throw(msg, exc=ValidationError, *a, **k):
        raise exc(msg)

    frappe.throw = _throw

    sys.modules["frappe"] = frappe
    # kb_drive imports these lazily, but module-level imports need them present.
    for name in ("frappe.model", "frappe.model.document"):
        if name not in sys.modules:
            mod = types.ModuleType(name)
            if name.endswith("document"):
                mod.Document = object
            sys.modules[name] = mod
    return frappe


class Doc(dict):
    """Stands in for a Frappe Single doc: .get() plus .get_password()."""

    def __init__(self, values=None, passwords=None):
        super().__init__(values or {})
        self._passwords = passwords or {}

    def get(self, key, default=None):
        return super().get(key, default)

    def get_password(self, key, raise_exception=True):
        return self._passwords.get(key)
