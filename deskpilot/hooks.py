app_name = "deskpilot"
app_title = "Deskpilot"
app_publisher = "mdad-elec"
app_description = "In-Desk guided assistant for ERPNext — answers from live data, drives the screen, cites your SOPs."
app_email = "mdad.alwathig@gmail.com"
app_license = "mit"

# Apps
# ------------------

# required_apps = []

add_to_apps_screen = [
	{
		"name": "deskpilot",
		"logo": "/assets/deskpilot/img/deskpilot_mark.svg",
		"title": "Deskpilot",
		"route": "/app/deskpilot",
		"has_permission": "deskpilot.api.has_app_permission",
	}
]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/deskpilot/css/deskpilot.css"
# app_include_js = "/assets/deskpilot/js/deskpilot.js"

# include js, css files in header of web template
# web_include_css = "/assets/deskpilot/css/deskpilot.css"
# web_include_js = "/assets/deskpilot/js/deskpilot.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "deskpilot/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "deskpilot/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# automatically load and sync documents of this doctype from downstream apps
# importable_doctypes = [doctype_1]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "deskpilot.utils.jinja_methods",
# 	"filters": "deskpilot.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "deskpilot.install.before_install"
after_install = "deskpilot.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "deskpilot.uninstall.before_uninstall"
# after_uninstall = "deskpilot.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "deskpilot.utils.before_app_install"
# after_app_install = "deskpilot.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "deskpilot.utils.before_app_uninstall"
# after_app_uninstall = "deskpilot.utils.after_app_uninstall"

# Build
# ------------------
# To hook into the build process

# after_build = "deskpilot.build.after_build"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "deskpilot.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# Document Events / Jinja
# -----------------------
# DELIBERATELY EMPTY, and worth keeping that way. This app is the assistant: the
# widget, its endpoints and its scheduler tasks. It does not customise your ERP.
#
# Site-specific document rules belong in your own app, not here. Putting them in
# this file couples your customisations to an app you upgrade from a marketplace
# release, and a dotted path that stops resolving takes the whole install down —
# hook resolution fails on the first missing module, so `bench install-app` dies
# before it reaches anything else.
#
# scripts/check_refs.py fails the build if any dotted reference in this file (or
# in patches.txt) does not resolve inside this repo.

# Scheduled Tasks
# ---------------

# These only become live Scheduled Job Type rows after `bench --site <site> migrate`.
scheduler_events = {
	"cron": {
		# Keep the LLM hot without relying on a browser tab being open. The
		# handler is redis-debounced, so this is at most one real ping/2min.
		"*/5 * * * *": [
			"deskpilot.tasks.warm"
		],
	},
	"daily": [
		"deskpilot.tasks.daily"
	],
	# Delta pull of the configured document source. Unchanged documents are
	# skipped, so a quiet day costs one listing call.
	"hourly_long": [
		"deskpilot.tasks.sync_knowledge_base"
	],
}

# Testing
# -------

# before_tests = "deskpilot.install.before_tests"

# Extend DocType Class
# ------------------------------
#
# Specify custom mixins to extend the standard doctype controller.
# extend_doctype_class = {
# 	"Task": "deskpilot.custom.task.CustomTaskMixin"
# }

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "deskpilot.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "deskpilot.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["deskpilot.utils.before_request"]
# after_request = ["deskpilot.utils.after_request"]

# Job Events
# ----------
# before_job = ["deskpilot.utils.before_job"]
# after_job = ["deskpilot.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"deskpilot.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }

# Translation
# ------------
# List of apps whose translatable strings should be excluded from this app's translations.
# ignore_translatable_strings_from = []



# NOTE: bump ?v= on every copilot.js deploy. The asset is served with no
# Cache-Control header, so browsers heuristically cache it and users keep running
# an old widget after a deploy (this silently wasted a debugging cycle).
# Order matters: copilot.js hands off to the wizard right after api.status()
# answers, so the wizard must already be defined.
app_include_js = [
	"/assets/deskpilot/js/deskpilot_setup.js?v=20260916a",
	"/assets/deskpilot/js/copilot.js?v=20260916a",
]
