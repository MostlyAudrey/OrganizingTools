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

from ballot_report.build import generate_ballot_report
from ballot_report.elections import elections_for_places, format_election_date, resolve_election
from ballot_report.geography import resolve_places


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Generate a Google Docs / Word-importable HTML ballot guide for California "
            "counties or cities, in the Federal → Race → Candidate structure."
        )
    )
    parser.add_argument(
        "places",
        nargs="+",
        help="One or more California counties and/or cities (e.g. Yolo Davis Sacramento)",
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
        "--list-elections",
        action="store_true",
        help="List known elections for the given places and exit.",
    )
    args = parser.parse_args(argv)

    display, counties, unresolved = resolve_places(args.places)
    if unresolved and not counties:
        print("ERROR: could not resolve places:", ", ".join(unresolved), file=sys.stderr)
        return 2

    as_of = date.fromisoformat(args.as_of) if args.as_of else date.today()

    if args.list_elections:
        print(f"Places: {', '.join(display)}")
        print(f"Counties: {', '.join(counties)}")
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
        slug_places = "_".join(p.replace(" ", "") for p in display[:4])
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
    )
    print(f"Wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
