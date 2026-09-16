frappe.ui.form.on("Deskpilot Settings", {
	refresh(frm) {
		frm.add_custom_button(__("Run setup wizard"), () => {
			if (window.deskpilot && window.deskpilot.setup) window.deskpilot.setup.open();
			else frappe.msgprint(__("Reload the page to load the setup wizard."));
		});
		frm.add_custom_button(__("Sync documents now"), () => sync_now(frm));

		// Only folders are valid here; the File link would otherwise offer every
		// uploaded file on the site.
		frm.set_query("frappe_folder", () => ({ filters: { is_folder: 1 } }));

		render_drive(frm);
		handle_return_params(frm);
	},

	sop_source(frm) {
		render_drive(frm);
	},
});

// The Drive connection is a state, not a field: what an administrator needs to see
// is whether it is connected and as whom, with the action that changes it.
function render_drive(frm) {
	const wrapper = frm.get_field("drive_html");
	if (!wrapper || !wrapper.$wrapper) return;
	if (frm.doc.sop_source !== "Google Drive") {
		wrapper.$wrapper.empty();
		return;
	}

	frappe.call({ method: "deskpilot.kb_drive.drive_status" }).then((r) => {
		const s = (r && r.message) || {};
		const connected = !!s.connected;
		const who = frappe.utils.escape_html(s.connected_email || "");
		const state = connected
			? `<div class="indicator green">${__("Connected")}${who ? " &mdash; " + who : ""}</div>`
			: `<div class="indicator red">${__("Not connected")}</div>`;

		wrapper.$wrapper.html(`
			<div style="margin-bottom:8px">${state}</div>
			<button class="btn btn-sm btn-primary" data-dp="connect">
				${connected ? __("Reconnect") : __("Connect Google Drive")}
			</button>
			${connected ? `<button class="btn btn-sm" data-dp="disconnect">${__("Disconnect")}</button>` : ""}
			${connected ? `<button class="btn btn-sm" data-dp="test">${__("Test folder")}</button>` : ""}
			<div class="text-muted small" style="margin-top:8px">
				${__("Requires Google Settings (client ID and secret) to be configured on this site.")}
				${__("Google's integration grants full Drive scope; Deskpilot only ever reads.")}
			</div>`);

		wrapper.$wrapper.find('[data-dp="connect"]').on("click", () => {
			frappe.call({ method: "deskpilot.kb_drive.authorize_drive" }).then((res) => {
				if (res && res.message && res.message.url) window.open(res.message.url);
			});
		});
		wrapper.$wrapper.find('[data-dp="disconnect"]').on("click", () => {
			frappe.confirm(__("Disconnect Google Drive? Indexed documents stay in the knowledge base."), () => {
				frappe.call({ method: "deskpilot.kb_drive.disconnect_drive" }).then(() => {
					frappe.show_alert({ message: __("Disconnected"), indicator: "orange" });
					frm.reload_doc();
				});
			});
		});
		wrapper.$wrapper.find('[data-dp="test"]').on("click", () => {
			frappe.call({ method: "deskpilot.kb_drive.drive_status" }).then((res) => {
				const t = (res && res.message) || {};
				frappe.msgprint({
					title: __("Drive folder"),
					indicator: t.folder_readable ? "green" : "red",
					message: t.folder_readable
						? __("Folder is readable: {0} file(s) visible.", [t.files_visible ?? "?"])
						: __("Could not read the folder. {0}", [frappe.utils.escape_html(t.error || "")]),
				});
			});
		});
	});
}

function sync_now(frm) {
	frappe.show_alert(__("Syncing…"));
	frappe.call({ method: "deskpilot.tasks.sync_now" }).then((r) => {
		const m = (r && r.message) || {};
		if (m.skipped) {
			frappe.msgprint(__("No document source is configured."));
			return;
		}
		frappe.msgprint({
			title: __("Sync complete"),
			indicator: m.ok ? "green" : "red",
			message: m.ok
				? __("{0} document(s) indexed, {1} chunk(s) in the knowledge base.",
					[(m.ingested || []).length, m.total_chunks ?? "?"])
				: frappe.utils.escape_html(m.error || __("Sync failed.")),
		});
	});
}

// The OAuth round trip returns the browser here with a query parameter, which is
// the only signal the user gets that it worked.
function handle_return_params(frm) {
	const drive = frappe.utils.get_url_arg("drive");
	if (drive === "connected") {
		frappe.show_alert({ message: __("Google Drive connected"), indicator: "green" });
	} else if (drive === "failed") {
		frappe.msgprint({
			title: __("Google Drive not connected"),
			indicator: "red",
			message: __("Authorization did not complete. Check Google Settings and try again."),
		});
	}
	if (frappe.utils.get_url_arg("setup") && window.deskpilot && window.deskpilot.setup) {
		window.deskpilot.setup.open();
	}
}
