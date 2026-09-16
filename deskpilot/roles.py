"""
Deskpilot — role-awareness.

Tier-1 (automatic): derive what the logged-in user can do, and which roles are
needed, straight from ERPNext's live permission model. No workbook required.

Also generates a DRAFT of the org RACI workbook (Department from the DocType's
module + Create/Submit/Cancel-By from live role permissions) so department leads
review + add Approve-By routing instead of filling a blank sheet (Tier-2).
"""

import os

import frappe

ACTIONS = ["read", "write", "create", "submit", "cancel", "delete"]


def _roles_with(meta):
    out = {"create": set(), "submit": set(), "cancel": set(), "write": set()}
    for p in meta.permissions:
        if p.create:
            out["create"].add(p.role)
        if p.submit:
            out["submit"].add(p.role)
        if p.cancel:
            out["cancel"].add(p.role)
        if p.write:
            out["write"].add(p.role)
    return {k: sorted(v) for k, v in out.items()}


@frappe.whitelist()
def role_permissions(doctype):
    """What CAN the current user do with `doctype`, and which roles grant each action."""
    from deskpilot.api import _guard_access
    _guard_access()
    if not doctype or not frappe.db.exists("DocType", doctype):
        return {"error": f"Unknown DocType: {doctype}"}
    meta = frappe.get_meta(doctype)
    you_can = {a: bool(frappe.has_permission(doctype, a)) for a in ACTIONS}
    return {
        "doctype": doctype,
        "your_roles": [r for r in frappe.get_roles() if r not in ("All", "Guest")],
        "you_can": you_can,
        "roles_with": _roles_with(meta),
        "is_submittable": bool(meta.is_submittable),
    }


def _doctypes_from_template(template_path):
    dts = []
    with open(template_path, encoding="utf-8", errors="ignore") as f:
        for line in f:
            if not line.strip().startswith("|"):
                continue
            cols = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cols) < 2:
                continue
            dt = cols[1]
            if dt in ("ERPNext DocType", "---", ""):
                continue
            dts.append(dt)
    return dts


def generate_role_workbook(template_path):
    """Pre-fill the RACI workbook from live permissions. Returns output path + stats."""
    doctypes = _doctypes_from_template(template_path)
    rows = ["| Department | ERPNext DocType | Create By | Submit By | Approve By | Cancel By | Notes |",
            "| --- | --- | --- | --- | --- | --- | --- |"]
    filled = missing = 0
    for dt in doctypes:
        if not frappe.db.exists("DocType", dt):
            rows.append(f"|  | {dt} |  |  |  |  | (not installed on this site) |")
            missing += 1
            continue
        meta = frappe.get_meta(dt)
        rw = _roles_with(meta)
        dept = meta.module or ""
        note = "" if meta.is_submittable else "not submittable"
        rows.append("| {dept} | {dt} | {cr} | {su} |  | {ca} | {note} |".format(
            dept=dept, dt=dt, cr=", ".join(rw["create"]), su=", ".join(rw["submit"]),
            ca=", ".join(rw["cancel"]), note=note))
        filled += 1
    out = "\n".join(rows) + "\n"
    path = os.path.join(frappe.get_site_path("private", "files"), "role_assignment_draft.md")
    with open(path, "w") as f:
        f.write(out)
    return {"path": path, "doctypes": len(doctypes), "filled": filled, "missing": missing}
