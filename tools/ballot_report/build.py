from __future__ import annotations

from datetime import date
from pathlib import Path

from .elections import format_election_date, resolve_election
from .geography import (
    appellate_district_for_county,
    districts_for_counties,
    resolve_places,
)
from .sources.county_local import filter_local_items, load_local_for_counties
from .html_report import write_report
from .models import BallotReport, Race
from .sources.justices import retention_races_for
from .sources.sos_candidates import filter_district_races, load_certified_races
from .sources.sos_props import load_statewide_measures


def build_report(
    places: list[str],
    election_date: str | date | None = None,
    as_of: date | None = None,
    include_local: bool = True,
    cache_dir: Path | None = None,
) -> BallotReport:
    resolved = resolve_places(places)
    display_places = resolved.display
    counties = resolved.counties
    unresolved = resolved.unresolved
    if not counties:
        raise ValueError(
            "Could not resolve any counties from: "
            + ", ".join(places)
            + ". Pass a California county name or a known city (see data/city_to_county.json)."
        )

    election = resolve_election(counties, election_date=election_date, as_of=as_of)
    notes: list[str] = []
    sources: list[str] = [
        "California Secretary of State — Upcoming Elections / Certified Candidate List",
        "California Official Voter Information Guide (when available for the election)",
    ]

    if unresolved:
        notes.append(
            "Could not map these places to a county (skipped for geography): "
            + ", ".join(unresolved)
        )

    if election_date is None:
        notes.append(
            f"No --date provided; defaulted to the next scheduled election for these areas: "
            f"{election.name} on {format_election_date(election.date)}."
        )
    else:
        notes.append(
            f"Using requested election date {format_election_date(election.date)} "
            f"({election.name})."
        )
    if election.notes:
        notes.append(election.notes)

    races: list[Race] = []
    measures = []

    # Statewide / districted candidate contests from SOS certified list
    if election.cert_list_url:
        try:
            cert = load_certified_races(url=election.cert_list_url, cache_dir=cache_dir)
            races.extend(cert.get("statewide", []))
            races.extend(cert.get("spi", []))

            dist = districts_for_counties(counties)
            races.extend(filter_district_races(cert.get("us_house", []), dist["us_house"]))
            races.extend(filter_district_races(cert.get("state_senate", []), dist["state_senate"]))
            races.extend(filter_district_races(cert.get("state_assembly", []), dist["state_assembly"]))
            races.extend(filter_district_races(cert.get("boe", []), dist["boe"]))

            notes.append(
                "Federal/state district contests are filtered using tools/ballot_report/data/"
                "district_counties.json. After redistricting, verify district coverage on your "
                "county elections site."
            )
            sources.append(election.cert_list_url)
        except Exception as exc:
            notes.append(f"Could not load SOS certified candidate list: {exc}")
    else:
        notes.append(
            "No certified candidate list URL is configured for this election date yet. "
            "Statewide candidate sections may be incomplete."
        )

    # Judicial retention
    app_districts = []
    for c in counties:
        d = appellate_district_for_county(c)
        if d and d not in app_districts:
            app_districts.append(d)
    races.extend(retention_races_for(election.date.isoformat(), app_districts))

    # Statewide propositions (currently wired for 2026-11-03 VIG)
    if election.kind == "statewide_general" and election.date.isoformat() == "2026-11-03":
        try:
            measures.extend(load_statewide_measures(cache_dir=cache_dir))
            if election.vig_base_url:
                sources.append(election.vig_base_url)
            sources.append("https://vig.cdn.sos.ca.gov/2026/general/pdf/text-proposed-laws.pdf")
        except Exception as exc:
            notes.append(f"Could not load statewide propositions: {exc}")
    elif election.kind == "statewide_general":
        notes.append(
            "Statewide proposition scraping is fully configured for the Nov 3, 2026 general "
            "election VIG. For other generals, add VIG URLs in election_calendar.json."
        )

    # Local races / measures
    if include_local:
        local_races, local_measures, local_notes = load_local_for_counties(counties)
        local_races, local_measures = filter_local_items(
            local_races,
            local_measures,
            selected_counties=resolved.selected_counties,
            selected_cities=resolved.selected_cities,
        )
        races.extend(local_races)
        measures.extend(local_measures)
        notes.extend(local_notes)
        if resolved.selected_cities and not resolved.selected_counties:
            notes.append(
                "City selection includes overlapping county contests plus municipal/"
                "school/special district races that name the selected city."
            )
        if resolved.selected_counties:
            notes.append(
                "County selection includes countywide contests and all overlapping city races "
                "found in the county source."
            )

    place_label = ", ".join(display_places)
    title = f"{place_label} — {election.name} Ballot Guide ({format_election_date(election.date)})"

    return BallotReport(
        title=title,
        places=display_places,
        counties=counties,
        cities=resolved.cities,
        election_date=format_election_date(election.date),
        races=_dedupe_races(races),
        measures=measures,
        notes=notes,
        sources=sources,
    )


def _dedupe_races(races: list[Race]) -> list[Race]:
    seen: set[str] = set()
    out: list[Race] = []
    for race in races:
        key = f"{race.level}::{race.name.lower()}"
        if key in seen:
            continue
        seen.add(key)
        out.append(race)
    return out


def generate_ballot_report(
    places: list[str],
    output: str | Path,
    election_date: str | date | None = None,
    as_of: date | None = None,
    include_local: bool = True,
) -> Path:
    report = build_report(
        places=places,
        election_date=election_date,
        as_of=as_of,
        include_local=include_local,
    )
    return write_report(report, Path(output))
