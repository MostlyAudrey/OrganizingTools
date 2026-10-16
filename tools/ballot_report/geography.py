from __future__ import annotations

import json
import re
from dataclasses import dataclass
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


@dataclass
class PlaceResolution:
    display: list[str]
    counties: list[str]
    cities: list[str]
    selected_counties: list[str]
    selected_cities: list[str]
    unresolved: list[str]


def city_to_county_map() -> dict[str, str]:
    return {k.lower(): v for k, v in _load_json("city_to_county.json").items()}


def known_cities() -> list[str]:
    return sorted(_load_json("city_to_county.json").keys(), key=lambda s: s.lower())


def cities_in_county(county: str) -> list[str]:
    county = normalize_place(county)
    return [city for city, cty in _load_json("city_to_county.json").items() if cty == county]


def normalize_place(name: str) -> str:
    name = name.strip()
    name = re.sub(r"\s*\((city|county)\)\s*$", "", name, flags=re.I)
    name = re.sub(r"\s+County$", "", name, flags=re.I)
    name = re.sub(r"\s+City$", "", name, flags=re.I)
    name = re.sub(r"^City of\s+", "", name, flags=re.I)
    return name.strip()


def parse_place_kind(raw: str) -> tuple[str, str | None]:
    """Return (normalized name, 'city'|'county'|None if unspecified)."""
    text = raw.strip()
    kind = None
    m = re.search(r"\((city|county)\)\s*$", text, flags=re.I)
    if m:
        kind = m.group(1).lower()
        text = text[: m.start()]
    return normalize_place(text), kind


def is_ambiguous_place(name: str) -> bool:
    key = normalize_place(name).lower()
    return key in {c.lower() for c in CA_COUNTIES} and key in city_to_county_map()


def appellate_district_for_county(county: str) -> str | None:
    county = normalize_place(county)
    for dist, counties in APPELLATE_DISTRICTS.items():
        if county in counties:
            return dist
    return None


def resolve_places(places: list[str]) -> PlaceResolution:
    """Resolve mixed city/county inputs, including ambiguous names like Los Angeles."""
    city_map = city_to_county_map()
    city_canonical = {k.lower(): k for k in _load_json("city_to_county.json")}
    county_lookup = {c.lower(): c for c in CA_COUNTIES}

    display: list[str] = []
    selected_counties: list[str] = []
    selected_cities: list[str] = []
    unresolved: list[str] = []

    for raw in places:
        place, kind = parse_place_kind(raw)
        if not place:
            continue
        key = place.lower()
        is_county = key in county_lookup
        is_city = key in city_map

        if kind == "county":
            if is_county:
                selected_counties.append(county_lookup[key])
                display.append(f"{county_lookup[key]} (county)")
            else:
                unresolved.append(raw)
            continue
        if kind == "city":
            if is_city:
                selected_cities.append(city_canonical[key])
                display.append(f"{city_canonical[key]} (city)")
            else:
                unresolved.append(raw)
            continue

        if is_county and is_city:
            unresolved.append(f"{place} (ambiguous — specify city or county)")
            continue
        if is_county:
            selected_counties.append(county_lookup[key])
            display.append(f"{county_lookup[key]} (county)")
            continue
        if is_city:
            selected_cities.append(city_canonical[key])
            display.append(f"{city_canonical[key]} (city)")
            continue
        unresolved.append(raw)

    def uniq(seq: list[str]) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for item in seq:
            if item not in seen:
                seen.add(item)
                out.append(item)
        return out

    selected_counties = uniq(selected_counties)
    selected_cities = uniq(selected_cities)
    counties = uniq(
        selected_counties + [city_map[c.lower()] for c in selected_cities]
    )
    return PlaceResolution(
        display=uniq(display),
        counties=counties,
        cities=selected_cities,
        selected_counties=selected_counties,
        selected_cities=selected_cities,
        unresolved=unresolved,
    )


def infer_city_from_text(text: str, county: str = "") -> str:
    """Best-effort city name from a contest title."""
    if not text:
        return ""

    def _pretty(name: str) -> str:
        name = normalize_place(name)
        name = name.strip(" —–-")
        if name.isupper():
            name = name.title()
        return name

    m = re.search(
        r"City of\s+(.+?)(?:\s+GENERAL|\s+Member|\s+Vote for|\s*,|\s+-|\s*$)",
        text,
        re.I,
    )
    if m:
        return _pretty(m.group(1))
    city_map = _load_json("city_to_county.json")
    names = sorted(city_map.keys(), key=len, reverse=True)
    county_key = normalize_place(county).lower()
    for city in names:
        if county and city_map[city] != county:
            continue
        # Don't treat the parent county name in a title as a city (Los Angeles County vs City of Los Angeles).
        if city.lower() == county_key:
            continue
        if re.search(rf"\b{re.escape(city)}\b", text, re.I):
            return city
    return ""


def local_item_matches(
    *,
    title: str,
    level: str,
    city: str,
    selected_counties: list[str],
    selected_cities: list[str],
    county: str,
) -> bool:
    """
    County selection includes all overlapping city races.
    City selection includes overlapping county races plus that city's contests.
    """
    city = city or infer_city_from_text(title, county)
    if selected_counties and county in selected_counties:
        return True
    if not selected_cities:
        return bool(selected_counties)
    if city:
        return any(city.lower() == sc.lower() for sc in selected_cities)
    if any(re.search(rf"\b{re.escape(sc)}\b", title, re.I) for sc in selected_cities):
        return True
    # City-only reports still include unnamed countywide offices (supervisors, etc.)
    if level == "County":
        city_map = city_to_county_map()
        return any(city_map.get(sc.lower()) == county for sc in selected_cities)
    return False


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
