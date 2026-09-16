# Frappe Marketplace listing copy

Paste-ready text for the Marketplace app form. Requirements referenced from Frappe's
publishing guidelines (short description 40–80 chars; long description must not repeat
the short one, and must not contain install instructions or screenshots; logo at least
200×200 and square, without words in it).

---

## App name

    deskpilot

## Title

    Deskpilot

## Short description (68 chars — within the 40–80 limit)

    Guided in-Desk AI assistant that answers from your live ERP data

## Category

    Utilities   (alternative: Productivity — pick whichever the form offers)

## Long description

Deskpilot puts an assistant inside the ERPNext Desk that does more than talk. It opens
the record you asked for, spotlights the exact field you need to fill in, and walks users
through a form one step at a time — so people who are stuck on *which field comes next*
get an answer that points at the screen instead of a paragraph describing it.

It answers questions about live data, and every figure it gives you comes from a tool
call made in that same turn. If the model states a number without looking it up, the
runtime catches it, forces a correction, and refuses rather than passing on a guess. The
same check applies to actions: claiming to have highlighted a field without actually
emitting the action is caught and corrected, not shipped.

Every call runs as the asking user, so answers are permission-scoped by Frappe itself.
Someone who cannot read Salary Slip cannot learn how many exist. The assistant has no
tool that writes to your database — no save, submit, amend or cancel. Asked to create
something, it opens the new form and fills in what you gave it, and you press Save.

Point it at your own process documents — a folder of files in the Desk, or a Google Drive
folder — and it answers how-to and policy questions by citing the document it read, so an
answer can be traced back to something you approved.

It runs against any OpenAI-compatible endpoint. Use a model on your own hardware with
vLLM, Ollama or llama.cpp and nothing leaves your network, or point it at a hosted API if
you prefer. A setup wizard walks you through connecting a model, choosing who can use it,
and indexing your documents — and it will not let you finish the first step until it has
made a real call to your endpoint and shown you the reply.

## Required URLs

| Field | Value |
|---|---|
| Support URL | https://github.com/mdad-elec/deskpilot/blob/main/docs/SUPPORT.md |
| Privacy Policy URL | https://github.com/mdad-elec/deskpilot/blob/main/docs/PRIVACY.md |
| Website / Source | https://github.com/mdad-elec/deskpilot |
| Publisher contact | mdad.alwathig@gmail.com |

## Logo

`docs/marketplace/logo.png` — 512×512, square, no text, already generated and committed.
Meets the stated requirements (at least 200×200, square, no words in the image).

It is drawn by `scripts/render_mark.py` rather than converted from the SVG:

```bash
python3 scripts/render_mark.py docs/marketplace/logo.png --size 512 --white
```

Do **not** use `magick convert` on the SVG. ImageMagick falls back to its built-in
renderer when librsvg is absent, and that renderer silently drops `stroke` on an
unfilled shape — the mark's outer ring disappears and you get a logo missing a third
of its design, with no error to tell you. `tests/test_mark.py` checks the renderer
against the SVG so the two cannot drift.

The committed logo is flattened onto white, since listings often render on a light
card and the mark is dark ink. For a transparent version, drop `--white`.

## Screenshots

In `docs/img/` — five, redacted rather than withheld. The product name is repainted
with the current one; a naming series, a localised field label and a live record count
are blurred; the dismissed-launcher image is regenerated from the current mark. See
`docs/img/README.md` for the reasoning.

Suggested order for the listing: `walkthrough.png` first (it is the whole pitch),
then `grid-column.png`, `add-row.png`, `sessions.png`.

Retaking them on a clean site with stock demo data would be better still — a
screenshot with nothing to hide beats a redacted one — but these are publishable.

## Compatibility

Version 15 (current stable). Version 16 is exercised in CI as an allowed-to-fail matrix
entry; promote it once it is the stable line.
