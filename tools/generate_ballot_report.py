#!/usr/bin/env python3
"""CLI for California ballot HTML reports."""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

# Allow running as: python tools/generate_ballot_report.py
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ballot_report.address_lookup import lookup_address
from ballot_report.build import generate_ballot_report
from ballot_report.elections import elections_for_places, resolve_election
from ballot_report.geography import resolve_places


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Generate a Google Docs / Word-importable HTML ballot guide for California "
            "counties, cities, or a street address."
        )
    )
    parser.add_argument(
        "places",
        nargs="*",
        help="California counties and/or cities (e.g. 'Yolo' 'Santa Monica (city)' 'Los Angeles (county)')",
    )
    parser.add_argument(
        "--address",
        default=None,
        help=(
            "Street address. When set, the guide uses the county, city, congressional district, "
            "state legislative districts, and school district at that address instead of the place list."
        ),
    )
    parser.add_argument(
        "--date",
        "-d",
        dest="election_date",
        default=None,
        help=(
            "Election date to generate (YYYY-MM-DD or 'November 3, 2026'). "
            "If omitted, uses the next scheduled election for these areas."
        ),
    )
    parser.add_argument(
        "--as-of",
        dest="as_of",
        default=None,
        help="Reference date for 'next election' default (YYYY-MM-DD). Defaults to today.",
    )
    parser.add_argument(
        "--output",
        "-o",
        default=None,
        help="Output HTML path. Defaults to tools/ballot_report/output/<places>_<date>.html",
    )
    parser.add_argument(
        "--no-local",
        action="store_true",
        help="Skip best-effort local county website scraping (statewide/district only).",
    )
    parser.add_argument(
        "--omit-measure-arguments",
        action="store_true",
        help=(
            "Omit arguments for and against, rebuttals, and the full text of proposed laws. "
            "The ballot question, summary, yes/no meanings, analysis, and tax rate statement stay."
        ),
    )
    parser.add_argument(
        "--list-elections",
        action="store_true",
        help="List known elections for the given places and exit.",
    )
    args = parser.parse_args(argv)

    if not args.places and not (args.address and args.address.strip()):
        parser.error("Pass at least one county or city, or use --address.")

    located = None
    if args.address and args.address.strip():
        try:
            located = lookup_address(args.address)
        except Exception as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2
        display = [located.matched_address]
        counties = [located.county]
        cities = [located.city] if located.city else []
    else:
        resolved = resolve_places(args.places)
        display, counties, unresolved = resolved.display, resolved.counties, resolved.unresolved
        cities = resolved.cities
        if unresolved and not counties:
            print("ERROR: could not resolve places:", ", ".join(unresolved), file=sys.stderr)
            return 2

    as_of = date.fromisoformat(args.as_of) if args.as_of else date.today()

    if args.list_elections:
        print(f"Places: {', '.join(display)}")
        print(f"Counties: {', '.join(counties)}")
        if cities:
            print(f"Cities: {', '.join(cities)}")
        print(f"As of: {as_of.isoformat()}")
        try:
            nxt = resolve_election(counties, election_date=None, as_of=as_of)
            print(f"Next election default: {nxt.date.isoformat()} — {nxt.name}")
        except Exception as exc:
            print(f"Next election default: unavailable ({exc})")
        print("Known elections:")
        try:
            nxt = resolve_election(counties, election_date=None, as_of=as_of)
            next_key = (nxt.date, nxt.name)
        except Exception:
            next_key = None
        for ev in elections_for_places(counties):
            marker = " (NEXT DEFAULT)" if next_key == (ev.date, ev.name) else ""
            print(f"  - {ev.date.isoformat()}  {ev.name}  [{ev.kind}/{ev.scope}]{marker}")
        return 0

    if not args.output:
        election = resolve_election(counties, election_date=args.election_date, as_of=as_of)
        slug_source = [located.city or located.county] if located else display[:4]
        slug_places = "_".join(p.replace(" ", "") for p in slug_source)
        out = (
            ROOT
            / "ballot_report"
            / "output"
            / f"{slug_places}_{election.date.isoformat()}_ballot_guide.html"
        )
    else:
        out = Path(args.output)

    path = generate_ballot_report(
        places=args.places,
        output=out,
        election_date=args.election_date,
        as_of=as_of,
        include_local=not args.no_local,
        include_measure_arguments=not args.omit_measure_arguments,
        address=args.address,
        located=located,
    )
    print(f"Wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
