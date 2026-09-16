"""Server side of the setup wizard.

Every method here is System Manager only. The wizard writes the same Deskpilot
Settings document the form does — it is a guided path through those fields, not a
second source of truth, so nothing here stores configuration anywhere else.

The one rule worth defending: test_model() makes a real call to the configured
endpoint and returns what came back. An install wizard that reports "saved!" and
leaves the administrator to discover at first use that the endpoint is wrong is
the exact failure this app exists to argue against.
"""

import json
import time

import frappe

from deskpilot import config

# What each step is allowed to write. A step cannot set a field belonging to
# another step, and nothing outside this map is writable through the wizard.
STEP_FIELDS = {
    "model": ("provider", "api_base", "api_key", "model", "max_answer_tokens",
              "max_job_seconds", "disable_reasoning", "streaming_disabled",
              "vision_disabled"),
    "embeddings": ("embed_base", "embed_key", "embed_model"),
    "access": ("required_role", "issue_assignees", "session_retention_sec"),
    "sops": ("sop_source", "frappe_folder", "drive_folder_id", "kb_mcp_url",
             "kb_mcp_token", "blocked_topics", "excluded_documents"),
    "personalize": ("helper_name", "greeting", "avatar"),
}

# Blank means "leave it alone" for secrets, so the wizard can show a filled-in
# form without ever sending the stored secret to the browser.
_SECRET_FIELDS = frozenset({"api_key", "embed_key", "kb_mcp_token"})


@frappe.whitelist()
def state():
    """Non-secret current configuration, for pre-filling the wizard."""
    frappe.only_for("System Manager")
    out = {f: config.get(f, "") for step in STEP_FIELDS.values() for f in step
           if f not in _SECRET_FIELDS}
    # Secrets are reported as "is one set?", never as a value.
    out["api_key_set"] = bool(config.get_password("api_key"))
    out["embed_key_set"] = bool(config.get_password("embed_key"))
    out["kb_mcp_token_set"] = bool(config.get_password("kb_mcp_token"))
    out["drive_connected"] = bool(config.get_password("drive_refresh_token"))
    out["drive_connected_email"] = config.get("drive_connected_email", "") or ""
    out["setup_complete"] = bool(config.get_bool("setup_complete"))
    try:
        from deskpilot import kb
        out["total_chunks"] = len(((kb._index() or {}).get("chunks")) or [])
    except Exception:
        out["total_chunks"] = 0
    return out


@frappe.whitelist()
def test_model(provider=None, api_base=None, api_key=None, model=None):
    """Make one real, tiny call to the endpoint and report what came back."""
    frappe.only_for("System Manager")
    from deskpilot import api

    provider = provider or config.get("provider")
    if provider == "Raven Settings":
        resolved = api._raven_llm()
        if not resolved:
            return {"ok": False, "error": "Raven has no usable LLM integration configured."}
        key, base, model, _tag = resolved
    else:
        key = api_key or config.get_password("api_key")
        base_default, model_default = config.PROVIDER_DEFAULTS.get(provider, (None, None))
        base = (api_base or config.get("api_base", "") or base_default or "").rstrip("/")
        model = model or config.get("model", "") or model_default
        if not key:
            return {"ok": False, "error": "No API key. Enter one above."}
        if not base:
            return {"ok": False, "error": "No API base URL. Enter one ending in /v1."}
        if not model:
            return {"ok": False, "error": "No model name."}

    t0 = time.time()
    try:
        resp = api._post_chat(
            base, key, model,
            [{"role": "user", "content": "Reply with exactly: OK"}],
            use_tools=False, max_tokens=8, no_reasoning=True, timeout=25,
            tool_choice="none",
        )
        text = (resp["choices"][0]["message"].get("content") or "").strip()
        return {"ok": True, "reply": text[:200], "model": model,
                "ms": int((time.time() - t0) * 1000)}
    except Exception as e:
        return {"ok": False, "error": _explain(e)}


def _explain(e):
    """A message an administrator can act on, not a stack trace."""
    import urllib.error

    if isinstance(e, urllib.error.HTTPError):
        try:
            body = e.read().decode("utf-8", errors="replace")[:200]
        except Exception:
            body = ""
        hint = {401: " — check the API key.", 403: " — the key was rejected.",
                404: " — check the base URL ends in /v1 and the model name exists."}
        return "HTTP %s%s %s" % (e.code, hint.get(e.code, ""), body)
    if isinstance(e, urllib.error.URLError):
        return "Could not reach the endpoint: %s" % str(getattr(e, "reason", e))[:160]
    return "%s: %s" % (type(e).__name__, str(e)[:200])


@frappe.whitelist()
def save(step=None, payload=None):
    """Write one wizard step into Deskpilot Settings."""
    frappe.only_for("System Manager")
    allowed = STEP_FIELDS.get(step)
    if not allowed:
        frappe.throw(frappe._("Unknown setup step: {0}").format(step))

    if isinstance(payload, str):
        payload = json.loads(payload or "{}")
    payload = payload or {}

    doc = frappe.get_single("Deskpilot Settings")
    for field in allowed:
        if field not in payload:
            continue
        value = payload[field]
        # An untouched secret arrives blank; writing it would wipe a working key.
        if field in _SECRET_FIELDS and not value:
            continue
        doc.set(field, value)
    doc.save(ignore_permissions=True)
    config.invalidate()
    return {"ok": True}


@frappe.whitelist()
def finish():
    """Mark setup done so the wizard stops offering itself."""
    frappe.only_for("System Manager")
    doc = frappe.get_single("Deskpilot Settings")
    doc.setup_complete = 1
    doc.save(ignore_permissions=True)
    config.invalidate()
    return {"ok": True}
