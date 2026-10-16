#!/usr/bin/env python3
"""Export ballot_report data as JSON for the GitHub Pages UI."""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ballot_report.elections import load_election_calendar
from ballot_report.geography import (
    APPELLATE_DISTRICTS,
    CA_COUNTIES,
    appellate_district_for_county,
    districts_for_counties,
)
from ballot_report.sources.county_local import load_local_for_counties
from ballot_report.sources.justices import retention_races_for
from ballot_report.sources.sos_candidates import load_certified_races
from ballot_report.sources.sos_props import load_statewide_measures

DATA_DIR = ROOT / "ballot_report" / "data"
SITE_DATA = ROOT / "ballot_site" / "data"


def _race_to_dict(race) -> dict:
    return {
        "name": race.name,
        "level": race.level,
        "description": race.description,
        "vote_for": race.vote_for,
        "county": getattr(race, "county", "") or "",
        "city": getattr(race, "city", "") or "",
        "candidates": [
            {
                "name": c.name,
                "party": c.party,
                "designation": c.designation,
                "incumbent": c.incumbent,
                "notes": c.notes,
            }
            for c in race.candidates
        ],
    }


def _measure_to_dict(m) -> dict:
    return {
        "title": m.title,
        "level": m.level,
        "jurisdiction": m.jurisdiction,
        "threshold": m.threshold,
        "ballot_question": m.ballot_question,
        "summary": m.summary,
        "yes_means": m.yes_means,
        "no_means": m.no_means,
        "analysis": m.analysis,
        "arg_for": m.arg_for,
        "reb_for": m.reb_for,
        "arg_against": m.arg_against,
        "reb_against": m.reb_against,
        "full_text": m.full_text,
        "tax_rate_statement": m.tax_rate_statement,
        "source_url": m.source_url,
    }


def export_geography(out_dir: Path) -> None:
    city_map = json.loads((DATA_DIR / "city_to_county.json").read_text(encoding="utf-8"))
    districts = json.loads((DATA_DIR / "district_counties.json").read_text(encoding="utf-8"))
    urls = json.loads((DATA_DIR / "county_elections_urls.json").read_text(encoding="utf-8"))
    payload = {
        "counties": CA_COUNTIES,
        "city_to_county": city_map,
        "district_counties": districts,
        "appellate_districts": APPELLATE_DISTRICTS,
        "county_elections_urls": urls,
    }
    (out_dir / "geography.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")


def export_election(
    election_date: str,
    include_local: bool,
    out_dir: Path,
    local_counties: list[str] | None = None,
) -> Path:
    calendar = {e.date.isoformat(): e for e in load_election_calendar()}
    if election_date not in calendar:
        raise SystemExit(f"Unknown election date {election_date}")
    ev = calendar[election_date]
    elections_dir = out_dir / "elections"
    elections_dir.mkdir(parents=True, exist_ok=True)

    snapshot: dict = {
        "date": ev.date.isoformat(),
        "name": ev.name,
        "kind": ev.kind,
        "scope": ev.scope,
        "notes": ev.notes,
        "cert_list_url": ev.cert_list_url,
        "vig_base_url": ev.vig_base_url,
        "statewide_races": [],
        "spi_races": [],
        "us_house": {},
        "state_senate": {},
        "state_assembly": {},
        "boe": {},
        "measures": [],
        "retention": {"supreme": [], "coa_by_district": {}},
        "local_by_county": {},
        "generated_at": date.today().isoformat(),
    }

    if ev.cert_list_url:
        cert = load_certified_races(url=ev.cert_list_url)
        snapshot["statewide_races"] = [_race_to_dict(r) for r in cert.get("statewide", [])]
        snapshot["spi_races"] = [_race_to_dict(r) for r in cert.get("spi", [])]
        for bucket, key in [
            ("us_house", "us_house"),
            ("state_senate", "state_senate"),
            ("state_assembly", "state_assembly"),
            ("boe", "boe"),
        ]:
            for race in cert.get(bucket, []):
                import re

                m = re.search(r"District\s+(\d+)", race.name)
                if not m:
                    continue
                snapshot[key][m.group(1)] = _race_to_dict(race)

    # Retention for all appellate districts we know
    for dist in APPELLATE_DISTRICTS:
        races = retention_races_for(ev.date.isoformat(), [dist])
        for race in races:
            if "Supreme Court" in race.name:
                if not any(r["name"] == race.name for r in snapshot["retention"]["supreme"]):
                    snapshot["retention"]["supreme"].append(_race_to_dict(race))
            else:
                snapshot["retention"]["coa_by_district"][dist] = _race_to_dict(race)

    if ev.kind == "statewide_general" and ev.date.isoformat() == "2026-11-03":
        snapshot["measures"] = [_measure_to_dict(m) for m in load_statewide_measures()]

    if include_local:
        urls = json.loads((DATA_DIR / "county_elections_urls.json").read_text(encoding="utf-8"))
        county_list = local_counties if local_counties is not None else sorted(urls.keys())
        for county in county_list:
            try:
                races, measures, notes = load_local_for_counties([county])
                snapshot["local_by_county"][county] = {
                    "races": [_race_to_dict(r) for r in races],
                    "measures": [_measure_to_dict(m) for m in measures],
                    "notes": notes,
                }
                print(f"  local OK: {county} ({len(races)} races, {len(measures)} measures)")
            except Exception as exc:
                snapshot["local_by_county"][county] = {
                    "races": [],
                    "measures": [],
                    "notes": [f"Export failed: {exc}"],
                }
                print(f"  local FAIL: {county}: {exc}")

    out = elections_dir / f"{election_date}.json"
    out.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
    return out


def export_meta(out_dir: Path) -> None:
    calendar = load_election_calendar()
    elections = []
    for ev in calendar:
        path = out_dir / "elections" / f"{ev.date.isoformat()}.json"
        elections.append(
            {
                "date": ev.date.isoformat(),
                "name": ev.name,
                "kind": ev.kind,
                "scope": ev.scope,
                "notes": ev.notes,
                "has_snapshot": path.exists(),
                "snapshot": f"elections/{ev.date.isoformat()}.json" if path.exists() else None,
            }
        )
    meta = {
        "title": "California Ballot Guide",
        "updated": date.today().isoformat(),
        "elections": elections,
        "default_as_of": date.today().isoformat(),
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Export web data for ballot_site")
    parser.add_argument(
        "--date",
        action="append",
        dest="dates",
        help="Election date(s) to snapshot (YYYY-MM-DD). Default: 2026-11-03 if cert list exists.",
    )
    parser.add_argument(
        "--all-configured",
        action="store_true",
        help="Export every calendar election that has a cert_list_url.",
    )
    parser.add_argument(
        "--no-local",
        action="store_true",
        help="Skip county local scrapes (faster).",
    )
    parser.add_argument(
        "--local-counties",
        nargs="*",
        default=None,
        help="Only scrape these counties for local races (default: all with known URLs).",
    )
    parser.add_argument(
        "--out",
        default=str(SITE_DATA),
        help="Output data directory (default: tools/ballot_site/data)",
    )
    args = parser.parse_args(argv)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "elections").mkdir(exist_ok=True)

    export_geography(out_dir)

    dates = list(args.dates or [])
    if args.all_configured:
        dates = [
            e.date.isoformat()
            for e in load_election_calendar()
            if e.cert_list_url
        ]
    if not dates:
        dates = ["2026-11-03"]

    for d in dates:
        print(f"Exporting {d}...")
        path = export_election(
            d,
            include_local=not args.no_local,
            out_dir=out_dir,
            local_counties=args.local_counties,
        )
        print(f"  wrote {path}")

    export_meta(out_dir)
    print(f"Wrote meta + geography under {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
