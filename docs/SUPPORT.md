# Support

## Before opening an issue

Most problems are one of the traps in the [README](../README.md#traps). Two are worth
checking first, because they account for most "it stopped working" reports:

1. **Knowledge search returns nothing.** The embedding endpoint is almost certainly the
   same as the chat endpoint. They must be different services. Deskpilot Settings warns
   about this if you set them the same.
2. **The assistant does nothing when asked to act.** Check `max_answer_tokens`. A
   truncated tool call is discarded whole, so a budget that is too small looks like
   silence rather than a short answer.

## Useful diagnostics

```bash
bench --site your-site execute deskpilot.api.status          # provider, model, access
bench --site your-site execute deskpilot.kb.kb_stats         # index size, embed config
bench --site your-site execute deskpilot.tasks.sync_now      # re-sync, with a count
bench --site your-site execute deskpilot.kb_drive.drive_status   # Google Drive state
```

`kb_stats` is the fastest way to tell a configuration problem from an empty folder: if
`total_chunks` is 0, nothing was ever indexed; if `stored_embed_model` differs from
`configured_embed_model`, the index was built with a different model and needs a re-sync.

## Reporting a bug

Open an issue at <https://github.com/mdad-elec/deskpilot/issues> with:

- Frappe and ERPNext versions (`bench version`)
- The output of `deskpilot.api.status` (it contains **no** secrets — safe to paste)
- What you asked, and what happened instead

Please do not paste API keys, or the contents of `site_config.json`.

## Security

For a suspected security issue, please do not open a public issue. Report it through
GitHub's private vulnerability reporting on the repository.
