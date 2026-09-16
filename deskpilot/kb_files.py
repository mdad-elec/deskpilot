"""Frappe File folder -> knowledge base. The default document source.

Why this is the default rather than Google Drive: it needs no external account, no
OAuth round trip and no credentials at all, and it works unchanged on Frappe Cloud
where the administrator has no filesystem access. Uploading SOPs into a Desk folder
is something every Frappe user already knows how to do.

SCOPE, STATED PLAINLY
The knowledge base is shared. Every file indexed from this folder becomes
answerable to every user who can reach the assistant, regardless of who uploaded
it or whether the File is marked private — retrieval does not re-check per-user
permissions on chunks. That is why the folder is chosen by a System Manager and
why the field description in Deskpilot Settings says so. Point it at a folder of
approved process documents, not at Home.

State, chunking and embedding are shared with the Drive path: this module only
decides *which bytes*, then hands them to extract.extract_bytes() and
kb.ingest_text().
"""

import json
import mimetypes
import os
import time

import frappe

from deskpilot import config, extract, kb

STATE_FILE = "deskpilot_kb_files_state.json"
SOURCE_PREFIX = "file:"
MAX_DEPTH = 6


def _folder():
    return (config.get("frappe_folder", "") or "").strip()


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


def _walk(folder, depth=0, seen=None):
    """Every extractable File under `folder`, recursing into subfolders.

    Frappe folders are File rows with is_folder=1, and a folder can in principle
    be reached twice, so the visited set is not paranoia.
    """
    seen = seen if seen is not None else set()
    if depth > MAX_DEPTH or not folder or folder in seen:
        return []
    seen.add(folder)

    rows = frappe.get_all(
        "File",
        filters={"folder": folder},
        fields=["name", "file_name", "file_url", "is_folder", "is_private",
                "modified", "file_size"],
        limit_page_length=0,
    )
    out = []
    for row in rows:
        if row.is_folder:
            out.extend(_walk(row.name, depth + 1, seen))
            continue
        name = row.file_name or row.file_url or ""
        if name.lower().endswith(extract.EXTRACTABLE_EXT):
            out.append(row)
    return out


def _read(row):
    """File bytes, or (None, reason).

    Runs as whoever triggered the sync — the scheduler user for the hourly job, a
    System Manager for a manual one — and deliberately ignores per-user file
    permissions, because the resulting chunks are shared anyway (see module
    docstring). Restricting here would produce a knowledge base whose contents
    depend on who happened to run the sync, which is worse.
    """
    try:
        doc = frappe.get_doc("File", row.name)
        return doc.get_content(), None
    except Exception as e:
        return None, "unreadable: %s" % str(e)[:140]


def sync(force=False, dry_run=False):
    """Pull the folder into the KB. Delta by `modified` unless `force`."""
    folder = _folder()
    if not folder:
        return {"ok": False, "error": "No Frappe folder configured."}

    t0 = time.time()
    try:
        files = _walk(folder)
    except Exception as e:
        return {"ok": False, "error": str(e)[:300], "folder": folder}

    state = _load_state()
    known = state.get("files") or {}
    report = {"ok": True, "folder": folder, "seen": len(files),
              "ingested": [], "skipped": [], "failed": [], "removed": []}

    for row in files:
        fid = row.name
        name = row.file_name or fid
        # Excluded documents are checked FIRST, before the unchanged/force
        # branches, so neither an edit nor force=True can quietly reinstate a
        # document the administrator excluded.
        if kb._kb_doc_denied(name, name):
            report["skipped"].append({"name": name, "reason": "out_of_scope"})
            continue
        prev = known.get(fid) or {}
        if not force and prev.get("modified") == str(row.modified) and prev.get("chunks"):
            report["skipped"].append({"name": name, "reason": "unchanged"})
            continue

        blob, why = _read(row)
        if blob is None:
            report["failed"].append({"name": name, "reason": why})
            continue
        text, why = extract.extract_bytes(name, mimetypes.guess_type(name)[0], blob)
        if not text or not text.strip():
            report["failed"].append({"name": name, "reason": why or "empty"})
            continue
        if dry_run:
            report["ingested"].append({"name": name, "chars": len(text), "dry_run": True})
            continue
        try:
            res = kb.ingest_text(SOURCE_PREFIX + fid, name.strip(), text, replace=True)
        except Exception as e:
            frappe.log_error(frappe.get_traceback(), "deskpilot kb_files ingest")
            report["failed"].append({"name": name, "reason": str(e)[:140]})
            continue
        known[fid] = {"name": name, "modified": str(row.modified),
                      "chunks": res.get("chunks", 0), "ingested_at": frappe.utils.now()}
        report["ingested"].append({"name": name, "chunks": res.get("chunks", 0),
                                   "chars": len(text)})

    # A file deleted or moved out of the folder must leave the KB too, or the
    # assistant keeps answering from a document the team has retired.
    live = {row.name for row in files}
    for fid in [k for k in known if k not in live]:
        if not dry_run:
            try:
                kb.ingest_text(SOURCE_PREFIX + fid, known[fid].get("name") or fid, "",
                               replace=True)
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
def sync_files(force=0, dry_run=0):
    """Whitelisted manual trigger (System Manager only — this rebuilds the KB)."""
    frappe.only_for("System Manager")
    return sync(force=bool(int(force or 0)), dry_run=bool(int(dry_run or 0)))


@frappe.whitelist()
def files_status():
    """Config/state probe for the Settings form and the setup wizard."""
    from deskpilot.api import _guard_access
    _guard_access()
    folder = _folder()
    state = _load_state()
    out = {"folder": folder, "last_sync": state.get("last_sync"),
           "tracked_files": len(state.get("files") or {})}
    if not folder:
        out["error"] = "No Frappe folder is set."
        return out
    out["folder_exists"] = bool(frappe.db.exists("File", {"name": folder, "is_folder": 1}))
    if out["folder_exists"]:
        try:
            out["files_visible"] = len(_walk(folder))
        except Exception as e:
            out["error"] = str(e)[:160]
    else:
        out["error"] = "That folder no longer exists."
    return out
