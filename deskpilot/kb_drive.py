"""
Google Drive → KB ingest pipeline.

Pulls the curated ERP knowledge folder from Drive, extracts text, and feeds it
through kb.ingest_text() so retrieval, chunking and embedding stay in one place.

DESIGN NOTES
------------
* Google Docs are exported as **markdown** where the API allows it, falling back
  to plain text. Markdown keeps the heading structure, and kb._chunk() splits on
  headings — so a procedure stays whole and its section title is carried into the
  embedded text. Plain-text export throws that structure away.
* Sync is a DELTA: Drive's modifiedTime per file is remembered, and unchanged
  files are skipped. Re-embedding an unchanged 340 KB document on every run would
  be minutes of GPU time for nothing.
* Files that disappear from the folder have their chunks removed, so the KB can
  never answer from a document the team has deleted.
* Credentials: a Google OAuth refresh token held in Deskpilot Settings, obtained
  through Frappe's own Google integration (Google Settings supplies the client id
  and secret). Nothing is stored on disk and no service-account key is needed.
"""

import json
import os
import re
import time
from urllib.parse import quote

import frappe
import requests

from deskpilot import config, extract, kb

API = "https://www.googleapis.com/drive/v3"
# Frappe's Google integration owns the OAuth scopes and grants full "drive" for the
# drive domain. We cannot narrow it to drive.readonly without bypassing GoogleOAuth
# and its token handling, so the honest thing is to say so in the UI: Deskpilot only
# ever issues GETs, which is enforced by this module having no write call at all.
ACCESS_TOKEN_CACHE_KEY = "deskpilot:drive:access_token"
ACCESS_TOKEN_TTL = 50 * 60            # Google's tokens last 60 min; refresh early
STATE_FILE = "deskpilot_kb_drive_state.json"
MAX_BYTES = extract.MAX_BYTES

GDOC = "application/vnd.google-apps.document"
GSHEET = "application/vnd.google-apps.spreadsheet"
GSLIDE = "application/vnd.google-apps.presentation"
GFOLDER = "application/vnd.google-apps.folder"


# ------------------------------------------------------------------ config

def _folder_id():
    return (config.get("drive_folder_id", "") or "").strip()


def parse_folder_id(value):
    """The folder id out of whatever the user pasted.

    People paste the browser URL far more often than the bare id, and the API only
    accepts the id, so normalise here rather than making every reader guess.
    """
    v = (value or "").strip()
    if not v:
        return ""
    m = re.search(r"/folders/([A-Za-z0-9_-]{10,})", v)
    if m:
        return m.group(1)
    m = re.search(r"[?&]id=([A-Za-z0-9_-]{10,})", v)
    if m:
        return m.group(1)
    return v


class _OAuthSession(requests.Session):
    """A requests Session that carries a Google access token and renews it.

    The stored credential is a long-lived refresh token; access tokens last an hour.
    Rather than track expiry we cache the access token just under its lifetime and,
    if Google rejects it anyway (revoked, password change, clock skew), drop the
    cache and retry exactly once. Retrying more than once would turn an
    authorisation problem into a request storm.
    """

    def __init__(self, refresh_token):
        super().__init__()
        self._refresh_token = refresh_token

    def _access_token(self, force=False):
        cache = frappe.cache()
        if not force:
            tok = cache.get_value(ACCESS_TOKEN_CACHE_KEY)
            if tok:
                return tok
        from frappe.integrations.google_oauth import GoogleOAuth
        got = GoogleOAuth("drive").refresh_access_token(self._refresh_token)
        tok = (got or {}).get("access_token")
        if tok:
            cache.set_value(ACCESS_TOKEN_CACHE_KEY, tok, expires_in_sec=ACCESS_TOKEN_TTL)
        return tok

    def request(self, method, url, **kw):
        headers = dict(kw.pop("headers", None) or {})
        headers["Authorization"] = "Bearer %s" % (self._access_token() or "")
        r = super().request(method, url, headers=headers, **kw)
        if r.status_code == 401:
            frappe.cache().delete_value(ACCESS_TOKEN_CACHE_KEY)
            headers["Authorization"] = "Bearer %s" % (self._access_token(force=True) or "")
            r = super().request(method, url, headers=headers, **kw)
        return r


def _session():
    """Authorised Drive session, or (None, reason)."""
    token = config.get_password("drive_refresh_token")
    if not token:
        return None, ("Google Drive is not connected. Open Deskpilot Settings -> "
                      "Knowledge and use Connect Google Drive.")
    try:
        return _OAuthSession(token), None
    except Exception as e:
        return None, "Drive credentials rejected: %s" % str(e)[:160]


def _state_path():
    return os.path.join(frappe.get_site_path("private", "files"), STATE_FILE)


def _load_state():
    p = _state_path()
    if os.path.exists(p):
        try:
            with open(p) as f:
                return json.load(f)
        except Exception:
            pass
    return {"files": {}, "last_sync": None}


def _save_state(state):
    with open(_state_path(), "w") as f:
        json.dump(state, f, indent=1)


# ------------------------------------------------------------------ listing

def _walk(sess, folder_id, depth=0, seen=None):
    """Every supported file under the folder, recursing into subfolders."""
    seen = seen if seen is not None else set()
    if depth > 6 or folder_id in seen:
        return []
    seen.add(folder_id)
    out, page = [], None
    while True:
        params = {
            "q": "'%s' in parents and trashed = false" % folder_id,
            "fields": "nextPageToken,files(id,name,mimeType,modifiedTime,md5Checksum,size)",
            "pageSize": 200, "supportsAllDrives": "true",
            "includeItemsFromAllDrives": "true",
        }
        if page:
            params["pageToken"] = page
        r = sess.get("%s/files" % API, params=params)
        if r.status_code != 200:
            raise RuntimeError("Drive list failed (%s): %s" % (r.status_code, r.text[:200]))
        data = r.json()
        for f in data.get("files", []):
            if f["mimeType"] == GFOLDER:
                out.extend(_walk(sess, f["id"], depth + 1, seen))
            else:
                out.append(f)
        page = data.get("nextPageToken")
        if not page:
            break
    return out


# --------------------------------------------------------------- extraction

def _export(sess, file_id, mime):
    r = sess.get("%s/files/%s/export" % (API, file_id),
                 params={"mimeType": mime}, stream=False)
    # Drive returns no charset, so requests guesses latin-1 and "→" arrives as
    # "â\x86\x92". That mojibake would go straight into the embeddings and the
    # citations shown to users.
    if r.status_code == 200:
        r.encoding = "utf-8"
    return r


IMG_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)|!\[\]\[[^\]]*\]")
MD_ESCAPE_RE = re.compile(r"\\([\\`*_{}\[\]()#+\-.!>~|])")


def _clean_markdown(text):
    r"""Drop inline image placeholders and undo markdown escaping.

    The Docs markdown export emits "![][image7]" for every screenshot and escapes
    punctuation as "\-", both of which are noise in a retrieval corpus.
    """
    text = IMG_RE.sub("", text or "")
    text = MD_ESCAPE_RE.sub(r"\1", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _download(sess, file_id):
    r = sess.get("%s/files/%s" % (API, file_id),
                 params={"alt": "media", "supportsAllDrives": "true"})
    return r


def extract_text(sess, f):
    """Plain/markdown text for one Drive file, or (None, reason)."""
    # NB: `fid` must not appear on the right of its own assignment — the whole tuple
    # is evaluated before any name is bound, so the fallback raised NameError for any
    # file Drive returned without a name, instead of falling back to the id.
    fid = f["id"]
    mime, name = f["mimeType"], f.get("name") or fid
    size = int(f.get("size") or 0)
    if size > MAX_BYTES:
        return None, "skipped: %.1f MB exceeds the %d MB limit" % (
            size / 1048576.0, MAX_BYTES // 1048576)

    if mime == GDOC:
        # Markdown first: it preserves the heading structure the chunker splits on.
        # The plain-text export of these documents came back TRUNCATED (1,029 chars
        # against 86,348 for markdown), so falling back silently would ingest ~1%
        # of a document and look like success.
        best, best_mime = "", None
        for want in ("text/markdown", "text/plain"):
            r = _export(sess, fid, want)
            if r.status_code == 200 and (r.text or "").strip():
                if len(r.text) > len(best):
                    best, best_mime = r.text, want
                if want == "text/markdown":
                    break               # good enough, don't spend a second call
        if not best:
            return None, "Google Doc export failed"
        text = _clean_markdown(best) if best_mime == "text/markdown" else best
        if size and len(text) < size * 0.02:
            frappe.log_error(
                "Drive export of %s looks truncated: %d chars from a %d byte doc "
                "(via %s)" % (name, len(text), size, best_mime), "deskpilot kb_drive")
        return text, None
    if mime == GSHEET:
        r = _export(sess, fid, "text/csv")
        return (r.text, None) if r.status_code == 200 else (None, "Sheet export failed")
    if mime == GSLIDE:
        r = _export(sess, fid, "text/plain")
        return (r.text, None) if r.status_code == 200 else (None, "Slides export failed")


    r = _download(sess, fid)
    if r.status_code != 200:
        return None, "download failed (%s)" % r.status_code
    return extract.extract_bytes(name, mime, r.content)


# ------------------------------------------------------------------- sync

def sync(force=False, dry_run=False):
    """Pull the folder into the KB. Delta by modifiedTime unless `force`."""
    sess, err = _session()
    if not sess:
        return {"ok": False, "error": err}

    folder = _folder_id()
    if not folder:
        return {"ok": False, "error": "No Drive folder configured."}
    t0 = time.time()
    try:
        files = _walk(sess, folder)
    except Exception as e:
        return {"ok": False, "error": str(e)[:300], "folder": folder}

    state = _load_state()
    known = state.get("files") or {}
    report = {"ok": True, "folder": folder, "seen": len(files),
              "ingested": [], "skipped": [], "failed": [], "removed": []}

    for f in files:
        fid, name = f["id"], f.get("name") or f["id"]
        # Excluded document (see kb.KB_DOC_DENY) — checked FIRST, before the
        # unchanged/force branches, so neither a modified file nor force=True can
        # quietly restore a document the administrator excluded.
        if kb._kb_doc_denied(name, name):
            report["skipped"].append({"name": name, "reason": "out_of_scope"})
            continue
        prev = known.get(fid) or {}
        if not force and prev.get("modifiedTime") == f.get("modifiedTime") and prev.get("chunks"):
            report["skipped"].append({"name": name, "reason": "unchanged"})
            continue
        text, why = extract_text(sess, f)
        if not text or not text.strip():
            report["failed"].append({"name": name, "reason": why or "empty"})
            continue
        if dry_run:
            report["ingested"].append({"name": name, "chars": len(text), "dry_run": True})
            continue
        try:
            res = kb.ingest_text(fid, name.strip(), text, replace=True)
        except Exception as e:
            frappe.log_error(frappe.get_traceback(), "deskpilot kb_drive ingest")
            report["failed"].append({"name": name, "reason": str(e)[:140]})
            continue
        known[fid] = {"name": name, "modifiedTime": f.get("modifiedTime"),
                      "md5": f.get("md5Checksum"), "chunks": res.get("chunks", 0),
                      "ingested_at": frappe.utils.now()}
        report["ingested"].append({"name": name, "chunks": res.get("chunks", 0),
                                   "chars": len(text)})

    # Anything we ingested before but Drive no longer shows must leave the KB.
    live = {f["id"] for f in files}
    for fid in [k for k in known if k not in live]:
        if not dry_run:
            try:
                kb.ingest_text(fid, known[fid].get("name") or fid, "", replace=True)
            except Exception:
                pass
        report["removed"].append(known[fid].get("name") or fid)
        if not dry_run:
            known.pop(fid, None)

    if not dry_run:
        state["files"] = known
        state["last_sync"] = frappe.utils.now()
        state["folder"] = folder
        _save_state(state)
    report["seconds"] = round(time.time() - t0, 1)
    return report


@frappe.whitelist()
def sync_drive(force=0, dry_run=0):
    """Whitelisted manual trigger (System Manager only — this rebuilds the KB)."""
    from deskpilot.api import _guard_access
    _guard_access()
    if "System Manager" not in frappe.get_roles():
        frappe.throw("Only a System Manager can re-sync the knowledge base.",
                     frappe.PermissionError)
    return sync(force=bool(int(force or 0)), dry_run=bool(int(dry_run or 0)))


@frappe.whitelist()
def drive_status():
    """Config/credential/state probe — the first thing to check when it is quiet."""
    from deskpilot.api import _guard_access
    _guard_access()
    folder = _folder_id()
    state = _load_state()
    out = {
        "folder": folder,
        "connected": bool(config.get_password("drive_refresh_token")),
        "connected_email": config.get("drive_connected_email", "") or "",
        "last_sync": state.get("last_sync"),
        "tracked_files": len(state.get("files") or {}),
    }
    sess, err = _session()
    if err:
        out["error"] = err
        return out
    if not folder:
        out["error"] = "No Drive folder is set."
        return out
    try:
        r = sess.get("%s/files/%s" % (API, folder),
                     params={"fields": "id,name", "supportsAllDrives": "true"})
        out["folder_readable"] = r.status_code == 200
        if r.status_code == 200:
            out["folder_name"] = r.json().get("name")
            try:
                out["files_visible"] = len(_walk(sess, folder))
            except Exception:
                pass
        else:
            out["error"] = ("HTTP %s — is the folder shared with the connected "
                            "Google account?" % r.status_code)
    except Exception as e:
        out["folder_readable"] = False
        out["error"] = str(e)[:160]
    return out


# --------------------------------------------------------------- OAuth wiring
#
# We deliberately do NOT call GoogleOAuth.get_authentication_url(): it overwrites
# state["callback_method"] with Frappe's own Google Drive *backup* doctype, so the
# consent round trip would hand our authorisation code to the wrong app. Building
# the URL here is the supported way for a third-party app to use the shared
# callback — frappe.integrations.google_oauth.callback reads callback_method back
# out of the server-side state and dispatches to whatever we put there.

def _google_oauth():
    from frappe.integrations import google_oauth as go
    if not getattr(go, "create_google_oauth_state", None):
        frappe.throw(frappe._(
            "This Frappe version does not support app-level Google OAuth state "
            "(create_google_oauth_state). Update Frappe to connect Google Drive."))
    return go


@frappe.whitelist()
def authorize_drive():
    """Return the Google consent URL to open. System Manager only."""
    frappe.only_for("System Manager")
    go = _google_oauth()
    # Raises a linked "configure Google Settings" error if the site has no client id.
    oauth = go.GoogleOAuth("drive")
    state = go.create_google_oauth_state({
        "domain": "drive",
        "callback_method": "deskpilot.kb_drive.google_callback",
        "redirect": "/app/deskpilot-settings",
        "success_query_param": "drive=connected",
        "failure_query_param": "drive=failed",
    })
    redirect_uri = frappe.utils.get_request_site_address(True) + go.CALLBACK_METHOD
    url = (
        "https://accounts.google.com/o/oauth2/v2/auth?"
        "access_type=offline&response_type=code&prompt=consent&include_granted_scopes=true&"
        "client_id={client_id}&scope={scope}&redirect_uri={redirect_uri}&state={state}"
    ).format(
        client_id=oauth.google_settings.client_id,
        scope=quote(oauth.scopes, safe=""),
        redirect_uri=quote(redirect_uri, safe=""),
        state=state,
    )
    return {"url": url}


def google_callback(code=None, **kwargs):
    """Invoked by Frappe's shared Google callback. NOT whitelisted on purpose."""
    if not code:
        frappe.throw(frappe._("Google did not return an authorization code."))
    tokens = _google_oauth().GoogleOAuth("drive").authorize(code)
    refresh_token = (tokens or {}).get("refresh_token")
    if not refresh_token:
        # Google only returns a refresh token on a consent grant. Ours always asks
        # for one (prompt=consent), so this means the exchange itself failed.
        frappe.throw(frappe._("Google did not return a refresh token. Try again."))

    doc = frappe.get_single("Deskpilot Settings")
    doc.drive_refresh_token = refresh_token
    # Saved through the document, NOT frappe.db.set_single_value: the latter writes
    # tabSingles directly and would store this secret in clear text instead of
    # routing it through the encrypted password store.
    doc.drive_connected_email = _whoami(refresh_token) or ""
    doc.save(ignore_permissions=True)
    config.invalidate()
    frappe.cache().delete_value(ACCESS_TOKEN_CACHE_KEY)


def _whoami(refresh_token):
    """The connected Google account, for display. Best-effort."""
    try:
        r = _OAuthSession(refresh_token).get(
            "%s/about" % API, params={"fields": "user(emailAddress)"})
        if r.status_code == 200:
            return (r.json().get("user") or {}).get("emailAddress")
    except Exception:
        pass
    return None


@frappe.whitelist()
def disconnect_drive():
    """Forget the Drive credential. Indexed documents are left alone."""
    frappe.only_for("System Manager")
    doc = frappe.get_single("Deskpilot Settings")
    doc.drive_refresh_token = ""
    doc.drive_connected_email = ""
    doc.save(ignore_permissions=True)
    config.invalidate()
    frappe.cache().delete_value(ACCESS_TOKEN_CACHE_KEY)
    return {"ok": True}
