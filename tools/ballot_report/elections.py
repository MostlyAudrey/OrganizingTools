from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "data"


@dataclass(frozen=True)
class ElectionEvent:
    date: date
    name: str
    kind: str  # statewide_general, statewide_primary, special, local
    scope: str  # "statewide" or county name
    cert_list_url: str = ""
    vig_base_url: str = ""
    notes: str = ""

    @property
    def slug(self) -> str:
        return self.date.isoformat()

    @property
    def label(self) -> str:
        return f"{self.name} ({self.date.strftime('%B %-d, %Y')})" if False else (
            f"{self.name} ({self.date.strftime('%B %d, %Y').replace(' 0', ' ')})"
        )


def _parse_date(value: str | date | None) -> date | None:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%B %d, %Y", "%b %d, %Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    # tolerate "November 3 2026"
    m = re.match(r"([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})", text)
    if m:
        try:
            return datetime.strptime(f"{m.group(1)} {m.group(2)} {m.group(3)}", "%B %d %Y").date()
        except ValueError:
            try:
                return datetime.strptime(f"{m.group(1)} {m.group(2)} {m.group(3)}", "%b %d %Y").date()
            except ValueError:
                pass
    raise ValueError(
        f"Could not parse election date {value!r}. Use YYYY-MM-DD or 'November 3, 2026'."
    )


def load_election_calendar() -> list[ElectionEvent]:
    path = DATA_DIR / "election_calendar.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    events: list[ElectionEvent] = []
    for item in raw.get("elections", []):
        events.append(
            ElectionEvent(
                date=date.fromisoformat(item["date"]),
                name=item["name"],
                kind=item.get("kind", "statewide_general"),
                scope=item.get("scope", "statewide"),
                cert_list_url=item.get("cert_list_url", ""),
                vig_base_url=item.get("vig_base_url", ""),
                notes=item.get("notes", ""),
            )
        )
    return sorted(events, key=lambda e: e.date)


def elections_for_places(counties: list[str], calendar: list[ElectionEvent] | None = None) -> list[ElectionEvent]:
    """Statewide elections plus any county-scoped elections for the requested counties."""
    calendar = calendar or load_election_calendar()
    county_set = {c.lower() for c in counties}
    out: list[ElectionEvent] = []
    for ev in calendar:
        if ev.scope == "statewide":
            out.append(ev)
        elif ev.scope.lower() in county_set:
            out.append(ev)
    return out


def resolve_election(
    counties: list[str],
    election_date: str | date | None = None,
    as_of: date | None = None,
) -> ElectionEvent:
    """
    Resolve which election ballot to generate.

    - If election_date is provided, pick that exact date (must exist in calendar for these places).
    - Otherwise pick the next election on/after as_of (default: today) in those areas.
    """
    as_of = as_of or date.today()
    calendar = elections_for_places(counties)
    if not calendar:
        raise RuntimeError("No elections found in calendar for the requested places.")

    if election_date is not None:
        target = _parse_date(election_date)
        matches = [e for e in calendar if e.date == target]
        if not matches:
            available = ", ".join(f"{e.date.isoformat()} ({e.name})" for e in calendar)
            raise ValueError(
                f"No election on {target.isoformat()} for {', '.join(counties) or 'these places'}. "
                f"Available: {available}"
            )
        # Prefer statewide if both statewide + local share a date
        matches.sort(key=lambda e: 0 if e.scope == "statewide" else 1)
        return matches[0]

    upcoming = [e for e in calendar if e.date >= as_of]
    if upcoming:
        # If multiple on same day, prefer statewide
        first_date = upcoming[0].date
        same_day = [e for e in upcoming if e.date == first_date]
        same_day.sort(key=lambda e: 0 if e.scope == "statewide" else 1)
        return same_day[0]

    # All elections are in the past — return the most recent
    past = [e for e in calendar if e.date < as_of]
    past.sort(key=lambda e: e.date, reverse=True)
    return past[0]


def format_election_date(d: date) -> str:
    return d.strftime("%B %d, %Y").replace(" 0", " ")
