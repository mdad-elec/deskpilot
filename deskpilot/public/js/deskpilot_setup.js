/**
 * Deskpilot setup wizard.
 *
 * Four steps, each one dialog, each saving to Deskpilot Settings as it goes — so
 * abandoning the wizard half way leaves the work done rather than discarded.
 *
 * The model step will not let you past it on a saved key alone: you have to see a
 * real reply from your endpoint first. Configuration that reports success without
 * a live call is the failure mode this whole app argues against, and it is the
 * single most common way an install ends up quietly broken.
 */
(function () {
	if (window.__deskpilotSetupLoaded) return;
	window.__deskpilotSetupLoaded = true;

	const dp = (window.deskpilot = window.deskpilot || {});
	const OFFERED_KEY = "dp_setup_offered";

	function call(method, args) {
		return new Promise((resolve, reject) => {
			frappe.call({ method, args: args || {}, callback: (r) => resolve(r.message), error: reject });
		});
	}

	function saveStep(step, values) {
		return call("deskpilot.setup.save", { step, payload: JSON.stringify(values) });
	}

	// ------------------------------------------------------------ step 1: model
	function stepModel(st, next) {
		let tested = !!st.api_key_set; // a working install should not be re-tested

		const d = new frappe.ui.Dialog({
			title: __("Connect a model"),
			fields: [
				{
					fieldname: "provider", fieldtype: "Select", label: __("Provider"),
					options: ["OpenAI-compatible", "OpenAI", "NVIDIA", "Raven Settings"],
					default: st.provider || "OpenAI-compatible",
					onchange: () => { tested = false; refresh(); },
				},
				{
					fieldname: "api_base", fieldtype: "Data", label: __("API base URL"),
					default: st.api_base || "",
					description: __("Must end in /v1. Blank uses the provider default."),
					depends_on: "eval:doc.provider!='Raven Settings'",
					onchange: () => { tested = false; refresh(); },
				},
				{
					fieldname: "api_key", fieldtype: "Password", label: __("API key"),
					description: st.api_key_set
						? __("A key is already saved. Leave blank to keep it.")
						: __("Local servers that ignore auth still need any non-empty value."),
					depends_on: "eval:doc.provider!='Raven Settings'",
					onchange: () => { tested = false; refresh(); },
				},
				{
					fieldname: "model", fieldtype: "Data", label: __("Model"),
					default: st.model || "",
					depends_on: "eval:doc.provider!='Raven Settings'",
					onchange: () => { tested = false; refresh(); },
				},
				{ fieldname: "result", fieldtype: "HTML" },
			],
			primary_action_label: __("Save and continue"),
			primary_action: (v) => {
				saveStep("model", v).then(() => { d.hide(); next(); });
			},
			secondary_action_label: __("Test connection"),
			secondary_action: () => runTest(),
		});

		function setResult(html) {
			d.get_field("result").$wrapper.html(html);
		}

		function refresh() {
			// Disabling the primary action is the whole point: it makes "I have not
			// proven this works yet" a state you can see rather than a thing to remember.
			d.get_primary_btn().prop("disabled", !tested);
			if (!tested) {
				setResult(`<div class="text-muted small">${__("Test the connection to continue.")}</div>`);
			}
		}

		function runTest() {
			const v = d.get_values(true);
			setResult(`<div class="text-muted small">${__("Calling the endpoint…")}</div>`);
			call("deskpilot.setup.test_model", {
				provider: v.provider, api_base: v.api_base, api_key: v.api_key, model: v.model,
			}).then((r) => {
				if (r && r.ok) {
					tested = true;
					setResult(`<div class="indicator green">${__("Replied in {0} ms", [r.ms])}</div>
						<pre class="small" style="margin-top:6px;white-space:pre-wrap">${frappe.utils.escape_html(r.reply || "(empty reply)")}</pre>`);
				} else {
					tested = false;
					setResult(`<div class="indicator red">${__("No reply")}</div>
						<pre class="small" style="margin-top:6px;white-space:pre-wrap">${frappe.utils.escape_html((r && r.error) || __("Unknown error"))}</pre>`);
				}
				d.get_primary_btn().prop("disabled", !tested);
			});
		}

		d.show();
		refresh();
	}

	// ----------------------------------------------------------- step 2: access
	function stepAccess(st, next, back) {
		const d = new frappe.ui.Dialog({
			title: __("Who can use it"),
			fields: [
				{
					fieldname: "required_role", fieldtype: "Link", label: __("Required role"),
					options: "Role", default: st.required_role || "",
					description: __("Blank means every logged-in user. Enforced on the server for every endpoint, not just by hiding the widget."),
				},
				{
					fieldname: "issue_assignees", fieldtype: "Small Text",
					label: __("Send reported problems to"), default: st.issue_assignees || "",
					description: __("One user per line. Blank routes them to your System Managers."),
				},
			],
			primary_action_label: __("Save and continue"),
			primary_action: (v) => saveStep("access", v).then(() => { d.hide(); next(); }),
			secondary_action_label: __("Back"),
			secondary_action: () => { d.hide(); back(); },
		});
		d.show();
	}

	// ------------------------------------------------------------- step 3: SOPs
	function stepSops(st, next, back) {
		const d = new frappe.ui.Dialog({
			title: __("Where are your documents?"),
			fields: [
				{
					fieldname: "sop_source", fieldtype: "Select", label: __("Source"),
					options: ["None", "Frappe Files", "Google Drive"],
					default: st.sop_source || "Frappe Files",
					description: __("The assistant cites these when answering how-to and policy questions."),
				},
				{
					fieldname: "frappe_folder", fieldtype: "Link", label: __("Folder"),
					options: "File", default: st.frappe_folder || "",
					depends_on: "eval:doc.sop_source=='Frappe Files'",
					get_query: () => ({ filters: { is_folder: 1 } }),
					description: __("Everything under this folder is indexed and becomes answerable to every user of the assistant — including private files."),
				},
				{
					fieldname: "drive_folder_id", fieldtype: "Data", label: __("Drive folder"),
					default: st.drive_folder_id || "",
					depends_on: "eval:doc.sop_source=='Google Drive'",
					description: __("Paste the folder ID or its Drive URL."),
				},
				{
					fieldname: "drive_connect", fieldtype: "Button",
					label: st.drive_connected ? __("Reconnect Google Drive") : __("Connect Google Drive"),
					depends_on: "eval:doc.sop_source=='Google Drive'",
					click: () => {
						call("deskpilot.kb_drive.authorize_drive").then((r) => {
							if (r && r.url) window.open(r.url);
						});
					},
				},
				{ fieldname: "sync_sb", fieldtype: "Section Break" },
				{
					fieldname: "sync", fieldtype: "Button", label: __("Sync now"),
					depends_on: "eval:doc.sop_source!='None'",
					click: () => runSync(),
				},
				{ fieldname: "sync_result", fieldtype: "HTML" },
			],
			primary_action_label: __("Save and continue"),
			primary_action: (v) => saveStep("sops", v).then(() => { d.hide(); next(); }),
			secondary_action_label: __("Back"),
			secondary_action: () => { d.hide(); back(); },
		});

		function runSync() {
			const v = d.get_values(true);
			const out = d.get_field("sync_result").$wrapper;
			out.html(`<div class="text-muted small">${__("Saving and syncing…")}</div>`);
			// Save first: the sync reads the folder from Settings, not from the dialog.
			saveStep("sops", v)
				.then(() => call("deskpilot.tasks.sync_now"))
				.then((r) => {
					r = r || {};
					if (r.skipped) {
						out.html(`<div class="text-muted small">${__("No source configured.")}</div>`);
						return;
					}
					if (!r.ok) {
						out.html(`<div class="indicator red">${frappe.utils.escape_html(r.error || __("Sync failed"))}</div>`);
						return;
					}
					const n = (r.ingested || []).length;
					const failed = (r.failed || []).length;
					// A sync that indexes nothing is the common silent failure, so it
					// gets an amber indicator rather than a green "done".
					out.html(`<div class="indicator ${r.total_chunks ? "green" : "orange"}">
							${__("{0} document(s) indexed, {1} chunk(s) total", [n, r.total_chunks ?? 0])}
						</div>
						${failed ? `<div class="text-muted small">${__("{0} file(s) could not be read.", [failed])}</div>` : ""}`);
				});
		}

		d.show();
	}

	// -------------------------------------------------------- step 4: personalize
	function stepPersonalize(st, done, back) {
		const d = new frappe.ui.Dialog({
			title: __("Make it yours"),
			fields: [
				{
					fieldname: "helper_name", fieldtype: "Data", label: __("Name"),
					default: st.helper_name || "", description: __("Blank = Deskpilot."),
				},
				{
					fieldname: "greeting", fieldtype: "Small Text", label: __("Greeting"),
					default: st.greeting || "",
					description: __("First message of a new conversation."),
				},
				{
					fieldname: "avatar", fieldtype: "Attach Image", label: __("Avatar"),
					default: st.avatar || "",
					description: __("Use a dark image on a transparent background: it sits on a pale scrim in the light theme and is inverted in the dark theme, so a light avatar disappears in both."),
					onchange: () => preview(),
				},
				{ fieldname: "preview", fieldtype: "HTML" },
			],
			primary_action_label: __("Finish"),
			primary_action: (v) => {
				saveStep("personalize", v)
					.then(() => call("deskpilot.setup.finish"))
					.then(() => {
						d.hide();
						frappe.show_alert({ message: __("Deskpilot is set up"), indicator: "green" });
						done();
					});
			},
			secondary_action_label: __("Back"),
			secondary_action: () => { d.hide(); back(); },
		});

		function preview() {
			const v = d.get_values(true) || {};
			const src = v.avatar || "/assets/deskpilot/img/deskpilot_mark.svg";
			d.get_field("preview").$wrapper.html(
				`<div style="display:flex;align-items:center;gap:10px;margin-top:4px">
					<img src="${frappe.utils.escape_html(src)}" style="width:44px;height:44px;border-radius:50%;background:rgba(0,0,0,.06);padding:4px">
					<span class="text-muted small">${__("Shown on every Desk page.")}</span>
				</div>`);
		}

		d.show();
		preview();
	}

	// ------------------------------------------------------------------ driver
	dp.setup = {
		open() {
			call("deskpilot.setup.state").then((st) => {
				st = st || {};
				const finish = () => {
					if (cur_frm && cur_frm.doctype === "Deskpilot Settings") cur_frm.reload_doc();
				};
				const s4 = () => stepPersonalize(st, finish, s3);
				const s3 = () => stepSops(st, s4, s2);
				const s2 = () => stepAccess(st, s3, s1);
				const s1 = () => stepModel(st, s2);
				s1();
			});
		},

		// Offered once per tab, and only to somebody who can actually act on it.
		maybeAutoOpen(brain) {
			if (!brain || !brain.can_setup || brain.setup_complete) return;
			if (sessionStorage.getItem(OFFERED_KEY)) return;
			sessionStorage.setItem(OFFERED_KEY, "1");
			setTimeout(() => dp.setup.open(), 1500);
		},
	};
})();
