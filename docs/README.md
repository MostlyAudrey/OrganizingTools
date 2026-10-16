# California Ballot Guide (GitHub Pages)

Static site UI for the ballot report generator. Visitors pick counties/cities and an election date, then download an HTML guide in the same structure used for Google Docs / Word import.

## Enable GitHub Pages

1. Push this repo to GitHub.
2. **Settings → Pages**
3. Source: **GitHub Actions** (recommended; uses `.github/workflows/ballot-site.yml`)
   - Or: Deploy from branch → `/docs`
4. Run the **Update ballot site data** workflow once (Actions tab) to publish/refresh `docs/data`.
5. For MapTiler tiles, add a repository secret named `MAP_TILE_KEY` under **Settings → Secrets and variables → Actions**. The workflow writes it to `docs/map-config.js` only in the Pages artifact. Restrict the key to your Pages domain in the tile provider’s dashboard. Without the secret, the map uses Esri light gray tiles, which do not need a key.

## Local preview

```bash
# Export snapshot data into docs/data
python -m pip install -r tools/ballot_report/requirements.txt
python tools/export_ballot_web_data.py --date 2026-11-03 --out docs/data --local-counties Yolo Los Angeles

# Serve the site (required so fetch() can load JSON)
python -m http.server 8080 --directory docs
```

Open http://localhost:8080

## How it works

- `docs/index.html` is the tools landing page. The Election Guide generator is `docs/election-guide.html` (`app.js`, `styles.css`).
- `docs/data/` holds geography + election snapshots produced by `tools/export_ballot_web_data.py`.
- The browser filters statewide/district contests for the selected places and renders the HTML report client-side (no server runtime required).
- Local races/measures appear only for counties included when the snapshot was exported.
- Type **Santa Monica (city)** or **Los Angeles (county)** — names that are both a city and a county must include the kind. County reports include overlapping city races; city reports include overlapping county races.

## Refresh data

```bash
python tools/export_ballot_web_data.py --date 2026-11-03 --out docs/data --local-counties Yolo Los Angeles
```

Or use the GitHub Action **Update ballot site data**.

## Related CLI

```bash
python tools/generate_ballot_report.py Yolo --date 2026-11-03
```
