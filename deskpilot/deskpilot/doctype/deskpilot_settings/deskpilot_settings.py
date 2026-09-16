import frappe
from frappe.model.document import Document

from deskpilot import config


class DeskpilotSettings(Document):
	def validate(self):
		# Users paste the whole Drive URL far more often than the bare id, and the
		# API only accepts the id. Normalising here means every reader sees an id.
		if self.drive_folder_id:
			from deskpilot import kb_drive
			self.drive_folder_id = kb_drive.parse_folder_id(self.drive_folder_id)

		if self.api_base:
			self.api_base = self.api_base.strip().rstrip("/")
		if self.embed_base:
			self.embed_base = self.embed_base.strip().rstrip("/")

		# Sharing one endpoint between chat and embeddings makes every embedding
		# request 404 against a chat-only server, and the failure is swallowed by
		# design (retrieval degrades rather than erroring), so it presents as "the
		# knowledge base just stopped working" with nothing in the logs.
		if self.api_base and self.embed_base and self.api_base == self.embed_base:
			frappe.msgprint(
				frappe._("The embedding endpoint is the same as the chat endpoint. "
				         "Unless that server hosts both a chat and an embedding model, "
				         "every embedding will fail and knowledge search will return nothing."),
				title=frappe._("Check the embedding endpoint"), indicator="orange",
			)

	def on_update(self):
		config.invalidate()
		frappe.clear_cache(doctype=self.doctype)
