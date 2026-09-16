# Submitting Deskpilot to the Frappe Marketplace

The final submission needs an authenticated Frappe Cloud session and a signed publisher
agreement, so it has to be done by the repository owner. Everything up to that point is
prepared; this is the click-path.

## Before you start

- [ ] The public repo exists and CI is green on `main` (**mandatory** — Frappe's authoring
      guidelines state a passing GitHub Actions run is required for approval).
- [ ] `bench install-app deskpilot` has been run on a real site and the wizard completed.
- [ ] Screenshots retaken on a clean site (see `docs/img/README.md`). The listing needs them.
- [ ] Logo exported to 512×512 PNG (see `LISTING.md`).

## Steps

1. **Become a publisher.** Frappe Cloud dashboard → **Settings → Profile → Become a
   Publisher**.
2. **Add the app.** The new **Marketplace** tab → **+ Add App** → **Add from GitHub**,
   authorise the GitHub connection, and pick `mdad-elec/deskpilot`.
3. **Choose compatibility.** Select the Frappe versions the app supports — version 15
   today. The app enters **Draft**.
4. **Fill the Overview tab** with the text from `LISTING.md`: title, short description,
   long description, category, logo, screenshots, support URL, privacy policy URL.
5. **Create a release** of the app and **submit it for review**.
6. **Wait.** Frappe's stated SLA is that apps are reviewed or published within 10 days.

## Before you submit

Publisher contact is set: mdad.alwathig@gmail.com (in hooks.py and SUPPORT.md).

**A demo video.** Frappe's guidelines ask for a short video showing the app in use. It is
not listed as strictly mandatory, but this app demonstrates far better in motion than in
stills — the guided walkthrough and the spotlight are the whole pitch and neither reads
well as a screenshot.

## If it comes back for changes

The likely review notes, in rough order of probability:

- **Naming.** "Deskpilot" avoids the ERPNext and Frappe trademarks deliberately. If the
  reviewer asks for a change anyway, the app name is a one-line change in `hooks.py` plus
  the module rename — but the config key prefix and asset paths move with it, so treat it
  as a real change, not a cosmetic one.
- **Screenshots or logo dimensions.** Re-export; requirements are in `LISTING.md`.
- **Dependencies.** The document parsers (PyMuPDF, python-docx, openpyxl, chardet) are
  imported lazily inside the branches that use them and are not declared as hard
  requirements, so a reviewer installing on a bare bench will not hit a missing package —
  the affected file is skipped with a reason instead.
