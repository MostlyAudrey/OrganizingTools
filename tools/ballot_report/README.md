# California ballot HTML report generator

Generate a Google Docs / Word-importable HTML ballot guide for one or more
California **counties** or **cities**, using the same structure as the Yolo
November 2026 guide:

- `H1` jurisdiction level (Federal, State, County, …)
- `H2` race / measure name
- `H3` candidate name (+ ` (Incumbent)` when known)
- `<p>` party / ballot designation / measure details

## Setup

```bash
python -m pip install -r tools/ballot_report/requirements.txt
```

## Usage

Next scheduled election for a place (default):

```bash
python tools/generate_ballot_report.py Yolo
python tools/generate_ballot_report.py Davis Woodland
python tools/generate_ballot_report.py Sacramento --no-local
```

Specific election date:

```bash
python tools/generate_ballot_report.py Yolo --date 2026-11-03
python tools/generate_ballot_report.py Yolo --date "November 3, 2026"
python tools/generate_ballot_report.py San Mateo --date 2026-08-18
```

List known elections (and what “next” resolves to):

```bash
python tools/generate_ballot_report.py Yolo --list-elections
python tools/generate_ballot_report.py Yolo --list-elections --as-of 2026-07-01
```

Custom output path:

```bash
python tools/generate_ballot_report.py Yolo -d 2026-11-03 -o ./my_guide.html
```

## Election dates

- `--date` / `-d` selects a specific election.
- If omitted, the tool picks the **next scheduled election on/after today**
  (or `--as-of`) for the resolved counties from
  `tools/ballot_report/data/election_calendar.json`.
- Add future/special elections to that JSON (statewide or county-scoped).

## What is included

| Section | Source |
| --- | --- |
| Statewide constitutional offices, SPI | SOS certified candidate list for that election |
| U.S. House / Senate / Assembly / BOE districts covering the county | SOS list + `data/district_counties.json` |
| Supreme Court + Court of Appeal retention | Bundled for configured elections |
| Statewide propositions | Official VIG (fully wired for 2026-11-03) |
| Local county/city/school/special races & measures | Best-effort scrape of known county elections sites |

## Extending

- **Cities:** `data/city_to_county.json`
- **County elections URLs:** `data/county_elections_urls.json`
- **District coverage:** `data/district_counties.json` (update after redistricting)
- **Election calendar / cert-list URLs:** `data/election_calendar.json`

## GitHub Pages UI

A static site lives in `docs/` for hosting on GitHub Pages:

- Pick counties/cities and an election date in the browser
- Generate / preview / download the same HTML report format
- Data snapshots under `docs/data/` from `tools/export_ballot_web_data.py`

See `docs/README.md` for Pages setup and local preview.
