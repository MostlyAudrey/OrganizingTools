# California Ballot Guide (GitHub Pages)

Static site UI for the ballot report generator. Visitors pick counties/cities and an election date, then download an HTML guide in the same structure used for Google Docs / Word import.

## Enable GitHub Pages

1. Push this repo to GitHub.
2. **Settings → Pages**
3. Source: **GitHub Actions** (recommended; uses `.github/workflows/ballot-site.yml`)
   - Or: Deploy from branch → `/docs`
4. Run the **Update ballot site data** workflow once (Actions tab) to publish/refresh `docs/data`.

## Local preview

```bash
# Export snapshot data into docs/data
python -m pip install -r tools/ballot_report/requirements.txt
python tools/export_ballot_web_data.py --date 2026-11-03 --out docs/data --local-counties Yolo

# Serve the site (required so fetch() can load JSON)
python -m http.server 8080 --directory docs
```

Open http://localhost:8080

## How it works

- `docs/` is the static site (`index.html`, `app.js`, `styles.css`).
- `docs/data/` holds geography + election snapshots produced by `tools/export_ballot_web_data.py`.
- The browser filters statewide/district contests for the selected places and renders the HTML report client-side (no server runtime required).
- Local races/measures appear only for counties included when the snapshot was exported.

## Refresh data

```bash
python tools/export_ballot_web_data.py --date 2026-11-03 --out docs/data --local-counties Yolo Sacramento
```

Or use the GitHub Action **Update ballot site data**.

## Related CLI

```bash
python tools/generate_ballot_report.py Yolo --date 2026-11-03
```
