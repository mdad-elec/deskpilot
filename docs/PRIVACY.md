# Privacy

**Deskpilot is self-hosted. It has no backend of its own, and the publisher receives
nothing.** There is no telemetry, no licence check, no phone-home. Every network call
this app makes goes to an endpoint *you* configured.

## What leaves your site, and where it goes

| Data | Sent to | When |
|---|---|---|
| The user's question, recent conversation turns, and the name/route of the screen they are on | Your configured chat model endpoint | Every time a user asks something |
| Results of permission-scoped ERP reads (record counts, field values the user can already see) | The same chat endpoint | When answering a data question |
| Text of documents in your configured knowledge folder | Your configured embedding endpoint | On sync, and once per search query |
| A file a user attaches in the chat | Your chat endpoint (and, for images, only if vision is enabled) | When they attach it |

If you point the model settings at a hosted API (OpenAI, NVIDIA, or any other), that
provider's terms and data handling apply to everything in the table above. If you point
them at a model running on your own hardware, nothing leaves your network.

**Google Drive**, if configured, is read using a token you grant through your own Google
Cloud OAuth client. Deskpilot only ever issues read requests. Frappe's Google integration
requests the full `drive` scope — that is Frappe's scope list, not ours, and we cannot
narrow it without bypassing its token handling.

## What is stored on your site

- **Conversation transcripts** — one file per conversation under the site's private
  files, deleted automatically after the retention period in Deskpilot Settings
  (7 days by default), along with any files uploaded into that conversation.
- **Telemetry** — a local JSONL log of questions, latencies and tool usage, used by the
  evaluation harness. It contains user identities and the text of questions. It stays on
  your server, is rotated at 5 MB, and is never transmitted anywhere.
- **The knowledge index** — chunks and embeddings of your documents, in the site's
  private files.

## Access

Every endpoint runs as the asking user and is permission-scoped by Frappe. A user cannot
learn anything through Deskpilot that they could not read directly in the Desk.

The one exception is the knowledge base, and it is deliberate: indexed documents are
shared across everyone who can use the assistant, regardless of the file's own
permissions. Choose the indexed folder accordingly — this is stated on the field itself.

## Deleting data

Uninstalling the app removes its DocTypes. Transcripts, telemetry and the knowledge index
live in the site's private files and can be deleted there, or left to the retention job.
