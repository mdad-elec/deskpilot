# Screenshots

Taken on a live instance, then redacted. Two different treatments, for two
different problems:

- **The product name was repainted**, not blurred. It is branding rather than
  data, and a smear sitting where a reader looks to learn what the product is
  called is worse than useless.
- **Real data and site-specific customisations were blurred**: a naming series,
  a localised custom field, a conversation preview quoting a live record count.
  A blur reads honestly as "something was removed here".
- **`ghost-fab.png` was rebuilt**, not redacted. It was entirely the previous
  logo, so there was nothing to redact — it is regenerated from the current mark
  by `scripts/render_mark.py --ghost`.

Deliberately left alone: currency codes, stock ERPNext field names and the
assistant's own prose. They identify nothing, and a screenshot blurred into
abstraction is no good as listing artwork.

| File | Shows |
|---|---|
| `walkthrough.png` | A seven-step guided walkthrough on a Sales Order |
| `grid-column.png` | A highlight landing on a column heading inside a child table |
| `add-row.png` | "Add Row" resolved to the grid's own control, not a field |
| `sessions.png` | Per-user conversation history |
| `ghost-fab.png` | The dismissed launcher |

## Retaking them

Worth doing eventually on a clean site with stock demo data — a screenshot with
nothing to hide beats a redacted one, especially for the marketplace listing.
Name the assistant Deskpilot in Settings first.
