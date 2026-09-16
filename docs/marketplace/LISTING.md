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

## Logo

`deskpilot/public/img/deskpilot_mark.svg`, exported to PNG at 512×512 (square, no text —
both are stated requirements).

```bash
# any one of these
rsvg-convert -w 512 -h 512 deskpilot/public/img/deskpilot_mark.svg -o docs/marketplace/logo.png
magick -background none -density 512 deskpilot/public/img/deskpilot_mark.svg -resize 512x512 docs/marketplace/logo.png
```

Note the mark is dark ink on transparency. If the listing renders logos on a dark
background, export onto a white square instead so it stays visible.

## Screenshots

**Not yet taken.** The previous ones showed a live instance and could not be published;
see `docs/img/README.md` for the shot list. Take them on a clean site with stock demo
data before submitting.

## Compatibility

Version 15 (current stable). Version 16 is exercised in CI as an allowed-to-fail matrix
entry; promote it once it is the stable line.
