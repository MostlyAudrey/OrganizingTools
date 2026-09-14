from __future__ import annotations

import json
import re
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "data"

# Court of Appeal district → counties (Gov. Code / courts.ca.gov)
APPELLATE_DISTRICTS: dict[str, list[str]] = {
    "1": [
        "Alameda", "Contra Costa", "Del Norte", "Humboldt", "Lake", "Marin",
        "Mendocino", "Napa", "San Francisco", "San Mateo", "Solano", "Sonoma",
    ],
    "2": ["Los Angeles", "San Luis Obispo", "Santa Barbara", "Ventura"],
    "3": [
        "Alpine", "Amador", "Butte", "Calaveras", "Colusa", "El Dorado", "Glenn",
        "Lassen", "Modoc", "Mono", "Nevada", "Placer", "Plumas", "Sacramento",
        "San Joaquin", "Shasta", "Sierra", "Siskiyou", "Sutter", "Tehama",
        "Trinity", "Yolo", "Yuba",
    ],
    "4": ["Imperial", "Inyo", "Orange", "Riverside", "San Bernardino", "San Diego"],
    "5": [
        "Fresno", "Kern", "Kings", "Madera", "Mariposa", "Merced", "Stanislaus",
        "Tulare", "Tuolumne",
    ],
    "6": ["Monterey", "San Benito", "Santa Clara", "Santa Cruz"],
}

CA_COUNTIES = sorted({c for counties in APPELLATE_DISTRICTS.values() for c in counties})


def _load_json(name: str) -> dict:
    path = DATA_DIR / name
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_place(name: str) -> str:
    name = name.strip()
    name = re.sub(r"\s+County$", "", name, flags=re.I)
    name = re.sub(r"\s+City$", "", name, flags=re.I)
    name = re.sub(r"^City of\s+", "", name, flags=re.I)
    return name.strip()


def appellate_district_for_county(county: str) -> str | None:
    county = normalize_place(county)
    for dist, counties in APPELLATE_DISTRICTS.items():
        if county in counties:
            return dist
    return None


def resolve_places(places: list[str]) -> tuple[list[str], list[str], list[str]]:
    """
    Resolve mixed city/county inputs.
    Returns (display_places, counties, unresolved).
    """
    city_map = {k.lower(): v for k, v in _load_json("city_to_county.json").items()}
    counties: list[str] = []
    display: list[str] = []
    unresolved: list[str] = []

    county_lookup = {c.lower(): c for c in CA_COUNTIES}

    for raw in places:
        place = normalize_place(raw)
        display.append(place)
        key = place.lower()
        if key in county_lookup:
            counties.append(county_lookup[key])
            continue
        if key in city_map:
            counties.append(city_map[key])
            continue
        # fuzzy: "West Sacramento" style already normalized
        unresolved.append(raw)

    # unique preserve order
    seen = set()
    uniq_counties = []
    for c in counties:
        if c not in seen:
            seen.add(c)
            uniq_counties.append(c)
    return display, uniq_counties, unresolved


def districts_for_counties(counties: list[str]) -> dict[str, list[str]]:
    """Return office-type → district numbers covering any of the counties."""
    crosswalk = _load_json("district_counties.json")
    out: dict[str, list[str]] = {
        "us_house": [],
        "state_senate": [],
        "state_assembly": [],
        "boe": [],
    }
    county_set = {normalize_place(c) for c in counties}
    for office, districts in crosswalk.items():
        if office not in out:
            out[office] = []
        for dist, dist_counties in districts.items():
            if county_set.intersection(dist_counties):
                out[office].append(str(dist))
    for k in out:
        out[k] = sorted(out[k], key=lambda x: int(re.sub(r"\D", "", x) or 0))
    return out


def county_elections_url(county: str) -> str | None:
    urls = _load_json("county_elections_urls.json")
    return urls.get(normalize_place(county)) or urls.get(county)
