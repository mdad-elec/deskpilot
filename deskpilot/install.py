"""Install-time setup.

Deliberately almost empty. Frappe's installer runs sync_for() — which creates the
DocType tables and the Workspace — before after_install, so by the time this runs
the Single's table exists and all that is left is to make sure a row is there for
the Settings form to open onto.

Nothing here writes configuration. A fresh install must be inert: no roles
created, no scheduled jobs beyond those declared in hooks, nothing pointed at a
model. The setup wizard offers itself once to a System Manager and everything is
their explicit choice from there.
"""

import frappe


def after_install():
	try:
		if not frappe.db.exists("Deskpilot Settings", "Deskpilot Settings"):
			frappe.get_single("Deskpilot Settings").save(ignore_permissions=True)
	except Exception:
		# An install must not fail over a settings row that the form will create
		# on first open anyway.
		frappe.log_error(frappe.get_traceback(), "deskpilot after_install")
