"""ERP how-to knowledge, generated from THIS instance's schema.

Why generated and not written by hand: a document corpus assembled by a business tends
to be strategy and policy, not "which field do I fill in next". Step-by-step material
for the transactions users actually ask about is usually the thinnest part of it, so
"how do I create a sales order" cannot be answered from the corpus at all.

Generic ERPNext documentation does not fix it either: most instances have customised
forms, so mandatory fields and child-table columns differ from stock ERPNext. Every
field name, label, status value and description below is read from `frappe.get_meta`
at generation time, so the knowledge cannot drift from the forms users see. The only
hand-written parts are the one-line purposes and the aggregation warnings, both marked.

Regenerate after a customisation change:
    bench --site <site> execute deskpilot.erp_kb.sync
"""

import frappe

from deskpilot import kb

LAYOUT = ("Section Break", "Column Break", "Tab Break", "HTML", "Heading",
          "Fold", "Button", "Image")

# Hand-written, one line each. Kept deliberately short: the schema supplies the detail.
PURPOSE = {
    "Sales Order": "Confirms what a customer has agreed to buy, before delivery or invoicing.",
    "Sales Invoice": "Bills a customer and posts the receivable.",
    "Delivery Note": "Records goods leaving the warehouse against a Sales Order.",
    "Purchase Order": "Commits to buying from a supplier.",
    "Purchase Invoice": "Records a supplier's bill and posts the payable.",
    "Payment Entry": "Moves money in or out and allocates it against invoices or advances.",
    "Employee Advance": "Money advanced to an employee before expenses are claimed.",
    "Expense Claim": "An employee's expense submission, optionally settled against an advance.",
}

# Money fields whose meaning users conflate. Descriptions come from the schema; the
# closing guidance is hand-written because ERPNext does not state it anywhere.
AMBIGUOUS = {
    "Employee Advance": (
        "advance_amount", "paid_amount", "claimed_amount", "return_amount", "pending_amount",
    ),
}


def _fields(meta, only_required=False):
    out = []
    for df in meta.fields:
        if not df.fieldname or df.fieldtype in LAYOUT:
            continue
        if only_required and not df.reqd:
            continue
        out.append(df)
    return out


def build(doctype):
    """One how-to document for `doctype`, grounded entirely in its live meta."""
    meta = frappe.get_meta(doctype)
    L = []
    A = L.append
    A("# %s — how to use it in this ERP" % doctype)
    A("")
    A(PURPOSE.get(doctype, "").strip())
    A("")
    A("## Opening it")
    A("The list is at /app/%s and a new one at /app/%s/new."
      % (frappe.scrub(doctype).replace("_", "-"), frappe.scrub(doctype).replace("_", "-")))
    A("Ask the assistant to \"open the %s list\" and it will navigate there." % doctype.lower())
    A("")

    req = _fields(meta, only_required=True)
    if req:
        A("## Fields you must fill")
        for df in req:
            bit = "- **%s** (`%s`)" % (df.label or df.fieldname, df.fieldname)
            if df.fieldtype == "Link" and df.options:
                bit += " — a link to %s" % df.options
            if df.description:
                bit += " — %s" % str(df.description).strip()
            A(bit)
        A("")

    tables = [df for df in meta.fields if df.fieldtype == "Table" and df.options]
    if tables:
        A("## Line items")
        for df in tables[:2]:
            A("The **%s** table (`%s`) holds %s rows." % (df.label or df.fieldname,
                                                          df.fieldname, df.options))
            try:
                cm = frappe.get_meta(df.options)
                cols = [c for c in cm.fields if c.reqd and c.fieldtype not in LAYOUT]
                if cols:
                    A("Each row needs: %s." % ", ".join(
                        "%s (`%s`)" % (c.label or c.fieldname, c.fieldname) for c in cols))
            except Exception:
                pass
            A("Use the grid's **Add Row** button to add a line.")
        A("")

    if meta.is_submittable:
        A("## Draft, submitted, cancelled")
        A("This document is submittable, so it has three states:")
        A("- **Draft** (`docstatus` 0) — editable, no accounting or stock effect.")
        A("- **Submitted** (`docstatus` 1) — the state that counts. Ledger entries exist.")
        A("- **Cancelled** (`docstatus` 2) — reversed. It still exists as a row.")
        A("")
        A("**When totalling or counting, exclude cancelled documents** (`docstatus < 2`), "
          "or the figure silently includes reversed paperwork and is too high. This is the "
          "most common way a correct-looking total is wrong.")
        A("")
        A("The assistant can create a Draft but never submits, approves or cancels "
          "anything — submission stays with the person accountable for it.")
        A("")

    status = meta.get_field("status")
    if status and status.options:
        vals = [v.strip() for v in str(status.options).split("\n") if v.strip()]
        if vals:
            A("## Status values")
            A("`status` on this doctype is one of: %s." % ", ".join("**%s**" % v for v in vals))
            A("")

    amb = AMBIGUOUS.get(doctype)
    if amb:
        A("## Amount fields, and what \"balance\" means")
        A("These are separate fields and users often mean different ones by the same word:")
        for f in amb:
            df = meta.get_field(f)
            if df:
                A("- **%s** (`%s`)%s" % (df.label or f, f,
                                         " — " + str(df.description).strip() if df.description else ""))
        A("")
        A("There is no single field called \"balance\". If someone asks for a balance, say "
          "which measure you are giving, or ask which they want:")
        A("- **still to settle** = paid_amount − claimed_amount − return_amount")
        A("- **still to be paid out** = the `pending_amount` field")
        A("Report the figures that exist; never blend them into one unlabelled number.")
        A("")

    A("## Getting numbers out")
    A("Ask the assistant for a total rather than a list — it aggregates in the database "
      "and quotes the computed figure, e.g. \"total %s value this month\" or \"%s count "
      "by status\". Filter text with partial names; exact spelling is rarely needed."
      % (doctype.lower(), doctype.lower()))
    return "\n".join(L)


@frappe.whitelist()
def sync(doctypes=None):
    """Generate and ingest a how-to document per core doctype."""
    frappe.only_for(("System Manager", "Administrator"))
    names = ([d.strip() for d in doctypes.split(",")] if isinstance(doctypes, str) and doctypes
             else list(PURPOSE))
    out = []
    for dt in names:
        if not frappe.db.exists("DocType", dt):
            out.append({"doctype": dt, "error": "not on this site"})
            continue
        try:
            text = build(dt)
            src = "erp_howto_%s.md" % frappe.scrub(dt)
            res = kb.ingest_text(src, "How to: %s (this ERP)" % dt, text, replace=True)
            out.append({"doctype": dt, "chunks": res.get("chunks"), "chars": len(text)})
        except Exception as e:
            out.append({"doctype": dt, "error": "%s: %s" % (type(e).__name__, str(e)[:120])})
    return {"generated": out}


@frappe.whitelist()
def purge_out_of_scope():
    """Drop chunks for documents listed in Deskpilot Settings → Excluded documents."""
    frappe.only_for(("System Manager", "Administrator"))
    store = kb._load()
    chunks = store.get("chunks") or []
    doomed = sorted({c.get("source") for c in chunks
                     if kb._kb_doc_denied(c.get("title"), c.get("source"))})
    before = len(chunks)
    removed = []
    for src in doomed:
        n = sum(1 for c in chunks if c.get("source") == src)
        kb.ingest_text(src, "", "", replace=True)
        removed.append({"source": src, "chunks": n})
    after = len(kb._load().get("chunks") or [])
    return {"before": before, "after": after, "removed": removed}
