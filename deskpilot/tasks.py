"""
Deskpilot — scheduled housekeeping.

Registered in hooks.scheduler_events. NOTE: editing hooks alone does nothing —
`bench --site <site> migrate` must run to materialize these as Scheduled Job Type
rows. That step was missed originally, which is why keep_warm's docstring claimed
a scheduler was calling it while zero jobs existed.
"""

import json
import os

import frappe

from deskpilot import config

TELEMETRY_MAX_BYTES = 5 * 1024 * 1024
TELEMETRY_KEEP = 2


def rotate_telemetry():
    """Roll copilot_telemetry.jsonl at 5MB, keeping .1 and .2.

    Held under a cluster lock: _log() appends from 2 gunicorn workers x 4 threads
    plus every queue worker. An unlocked rename drops concurrent writes into the
    orphaned inode.
    """
    from deskpilot.api import _telemetry_path

    p = _telemetry_path()
    if not os.path.exists(p) or os.path.getsize(p) < TELEMETRY_MAX_BYTES:
        return {"rotated": False}
    try:
        with frappe.cache().lock("copilot:telemetry:rotate", timeout=60,
                                 blocking_timeout=5):
            if os.path.getsize(p) < TELEMETRY_MAX_BYTES:
                return {"rotated": False}          # another worker beat us to it
            oldest = "%s.%d" % (p, TELEMETRY_KEEP)
            if os.path.exists(oldest):
                os.remove(oldest)
            for i in range(TELEMETRY_KEEP - 1, 0, -1):
                src, dst = "%s.%d" % (p, i), "%s.%d" % (p, i + 1)
                if os.path.exists(src):
                    os.rename(src, dst)
            os.rename(p, p + ".1")
            open(p, "a").close()
        return {"rotated": True}
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "deskpilot rotate_telemetry")
        return {"rotated": False, "error": str(e)[:200]}


def purge_sessions():
    """Drop expired session transcripts and the attachments they owned."""
    from deskpilot import attachments, sessions

    try:
        removed, kept, urls = sessions.purge()
        freed = attachments.delete_by_urls(urls)
        frappe.db.commit()
        return {"sessions_removed": removed, "sessions_kept": kept, "files_deleted": freed}
    except Exception:
        frappe.log_error(frappe.get_traceback(), "deskpilot purge_sessions")
        return {"error": True}


def warm():
    """Keep the model hot without depending on someone having a Desk tab open."""
    from deskpilot.api import keep_warm
    try:
        return keep_warm(force=True)
    except Exception:
        return {"warm": False}


def daily():
    out = {}
    out.update(purge_sessions())
    out.update(rotate_telemetry())
    frappe.logger("deskpilot").info("daily housekeeping: %s" % json.dumps(out, default=str))
    return out


def _source_sync():
    """(callable, source_name) for the configured document source, or (None, name)."""
    from deskpilot import kb_drive, kb_files
    src = config.get("sop_source") or "None"
    return {"Frappe Files": kb_files.sync, "Google Drive": kb_drive.sync}.get(src), src


def sync_knowledge_base():
    """Hourly delta pull of the configured document source."""
    fn, src = _source_sync()
    if fn is None:
        # Not configured is a valid state, not a failure. Logging an error here
        # would fill the error log hourly on every site that does not use the KB.
        return {"ok": True, "skipped": "sop_source=%s" % src}
    try:
        rep = fn()
    except Exception:
        frappe.log_error(frappe.get_traceback(), "deskpilot kb sync")
        return {"ok": False}
    if not rep.get("ok"):
        # A misconfigured folder or a revoked grant is silent otherwise.
        frappe.log_error("KB sync failed (%s): %s" % (src, rep.get("error")),
                         "deskpilot kb sync")
    elif rep.get("ingested") or rep.get("removed") or rep.get("failed"):
        frappe.logger("deskpilot").info("KB sync: %s" % json.dumps(rep, default=str)[:900])
    return rep


@frappe.whitelist()
def sync_now(force=0):
    """Run the configured source synchronously and report the resulting size.

    Used by the Settings form and the setup wizard, where the point is to show the
    administrator that their folder actually produced chunks — a sync that reports
    success while indexing nothing is the failure this makes visible.
    """
    frappe.only_for("System Manager")
    fn, src = _source_sync()
    if fn is None:
        return {"ok": True, "skipped": "sop_source=%s" % src, "total_chunks": 0}
    rep = fn(force=bool(int(force or 0)))
    try:
        from deskpilot import kb
        rep["total_chunks"] = len(((kb._index() or {}).get("chunks")) or [])
    except Exception:
        pass
    return rep
