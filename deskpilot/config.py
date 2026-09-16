"""Settings resolution — the one place that answers "what is this configured to?".

RESOLUTION ORDER
    Deskpilot Settings (the DocType)  ->  site_config.json  ->  built-in default

The site_config tier exists so a site can pin a value that an administrator must
not be able to change from the Desk, and so an automated deployment can seed a
site before anyone logs in. It is NOT the normal path: the normal path is the
Settings form, which is what makes this app installable from the marketplace at
all (a site on Frappe Cloud has no filesystem access to edit site_config.json).

WHY VALUES ARE NOT DEFAULTED IN THE DOCTYPE JSON
A Single with no saved row still returns meta defaults from frappe.get_doc. If a
field carried its default in the JSON, an unconfigured Settings doc would read as
"deliberately set to the default" and would shadow a site_config value that an
administrator had deliberately pinned. So defaults live here, in DEFAULTS, and a
field is only "set" when it holds a non-empty value.

CHECK FIELDS ARE THE ONE EXCEPTION
For checkboxes the Settings value always wins, including when unticked. The
alternative — treating 0 as "unset" and falling through — means a flag switched on
in site_config.json can never be switched off from the UI, which is a trap for
every future user. get_bool() therefore ignores site_config whenever a Settings
row exists.
"""

import frappe

DOCTYPE = "Deskpilot Settings"
CONF_PREFIX = "deskpilot_"

# Encrypted fields. These are read through get_password() and must never be
# returned by a whitelisted method.
PASSWORD_FIELDS = frozenset({
    "api_key", "embed_key", "kb_mcp_token", "drive_refresh_token",
})

# Checkbox fields — see the module docstring for why these resolve differently.
CHECK_FIELDS = frozenset({
    "disable_reasoning", "streaming_disabled", "vision_disabled", "setup_complete",
})

DEFAULTS = {
    "provider": "OpenAI-compatible",
    # Chat model. No default key or base: unconfigured must mean provider "none",
    # not a hopeful request to somebody else's endpoint.
    "max_answer_tokens": 1100,
    "max_job_seconds": 150,
    # Embeddings are a SEPARATE endpoint from chat (see kb.py). A stock local Ollama.
    "embed_base": "http://127.0.0.1:11434/v1",
    "embed_model": "nomic-embed-text",
    "sop_source": "Frappe Files",
    "session_retention_sec": 7 * 24 * 3600,
    "helper_name": "Deskpilot",
    "greeting": "",
    "avatar": "/assets/deskpilot/img/deskpilot_mark.svg",
}

# Provider presets, applied only when the corresponding field is left blank.
PROVIDER_DEFAULTS = {
    "OpenAI": ("https://api.openai.com/v1", "gpt-4o-mini"),
    "NVIDIA": ("https://integrate.api.nvidia.com/v1", "moonshotai/kimi-k2.6"),
    "OpenAI-compatible": (None, None),
}

_MISSING = object()


def _settings():
    """The Settings doc, or None if it cannot be read yet.

    Must never raise. This is called from request handlers, from background jobs
    and from the scheduler, including on a site where the app's code is deployed
    but `bench migrate` has not run yet — at that moment the table does not exist
    and every caller would otherwise break.
    """
    cached = getattr(frappe.local, "deskpilot_settings", _MISSING)
    if cached is not _MISSING:
        return cached
    doc = None
    try:
        if getattr(frappe.local, "db", None) is not None and frappe.db.exists("DocType", DOCTYPE):
            doc = frappe.get_cached_doc(DOCTYPE)
    except Exception:  # missing table, partial install, no db: all mean "no settings"
        doc = None
    try:
        frappe.local.deskpilot_settings = doc
    except Exception:  # no frappe.local (bare interpreter): skip the cache
        pass
    return doc


def invalidate():
    """Drop the request-scoped cache. Called whenever Settings is saved."""
    try:
        frappe.local.deskpilot_settings = _MISSING
    except Exception:
        pass


def _conf(key):
    return frappe.conf.get(CONF_PREFIX + key)


def get(key, default=_MISSING):
    """Settings -> site_config -> DEFAULTS. Empty string and None both mean unset."""
    doc = _settings()
    if doc is not None:
        v = doc.get(key)
        if v not in (None, ""):
            return v
    v = _conf(key)
    if v not in (None, ""):
        return v
    if default is not _MISSING:
        return default
    return DEFAULTS.get(key)


def get_password(key):
    """Decrypted secret, or None. NEVER return the result to a client."""
    doc = _settings()
    if doc is not None:
        try:
            v = doc.get_password(key, raise_exception=False)
            if v:
                return v
        except Exception:  # an undecryptable value must not break the request
            pass
    return _conf(key) or None


def get_int(key, default=None):
    v = get(key, default)
    try:
        v = int(v)
    except (TypeError, ValueError):
        return default
    # 0 in an Int field is indistinguishable from "never filled in", so it means
    # "use the default" rather than "no budget at all" — a zero token or second
    # budget would disable the assistant with no way to tell why from the form.
    return v or default


def get_bool(key):
    """Checkbox. Settings wins outright when a Settings row exists (see docstring)."""
    doc = _settings()
    if doc is not None:
        return bool(doc.get(key))
    return bool(_conf(key))


def get_lines(key):
    """A Small Text field of one entry per line -> a list of non-empty lines."""
    raw = get(key, "") or ""
    if isinstance(raw, (list, tuple)):
        return [str(x).strip() for x in raw if str(x).strip()]
    return [ln.strip() for ln in str(raw).replace(",", "\n").splitlines() if ln.strip()]


def get_llm():
    """(key, base, model, provider_tag) for the chat model, or (None,)*3 + "none".

    Order: Settings -> deskpilot_* in site_config -> a bare openai_api_key or
    nvidia_api_key -> Raven's configured integration -> nothing. The legacy tiers
    are kept because a site that already works must keep working after upgrading.
    """
    provider = get("provider")

    if provider == "Raven Settings":
        from deskpilot.api import _raven_llm
        return _raven_llm() or (None, None, None, "none")

    base_default, model_default = PROVIDER_DEFAULTS.get(provider, (None, None))
    key = get_password("api_key")
    if key:
        base = get("api_base", None) or base_default
        model = get("model", None) or model_default
        if base and model:
            return (key, base, model, "configured")
        # A key with no endpoint is not a working configuration, and pretending
        # otherwise sends the request somewhere arbitrary. Fall through.

    conf = frappe.conf
    if conf.get("openai_api_key"):
        return (conf.get("openai_api_key"), "https://api.openai.com/v1",
                get("model", None) or "gpt-4o-mini", "openai")
    if conf.get("nvidia_api_key"):
        return (conf.get("nvidia_api_key"), "https://integrate.api.nvidia.com/v1",
                get("model", None) or "moonshotai/kimi-k2.6", "nvidia-kimi")

    from deskpilot.api import _raven_llm
    return _raven_llm() or (None, None, None, "none")


def public_appearance():
    """Non-secret display config. Safe to hand to any Desk user."""
    return {
        "helper_name": (get("helper_name") or "").strip() or DEFAULTS["helper_name"],
        "greeting": (get("greeting") or "").strip(),
        "avatar_url": (get("avatar") or "").strip() or DEFAULTS["avatar"],
    }
