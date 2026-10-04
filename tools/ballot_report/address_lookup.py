"""Place a California street address into the districts used by the ballot guide.

The point comes from the Esri World Geocoder. County, city, congressional
district, state senate, state assembly, and school district come from the
U.S. Census TIGERweb current map service. Both services allow browser calls,
so the website uses the same sources.
"""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from .geography import CA_COUNTIES, infer_city_from_text

UA = {"User-Agent": "ballot-guide/1.0"}
ESRI_GEOCODE = (
    "https://geocode.arcgis.com/arcgis/rest/services/World/GeocodeServer/findAddressCandidates"
)
TIGER = (
    "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/tigerWMS_Current/MapServer"
)

# Layer ids on tigerWMS_Current as published in 2026.
LAYER_UNIFIED = 14
LAYER_SECONDARY = 16
LAYER_ELEMENTARY = 18
LAYER_PLACES = 28
LAYER_CONGRESS = 54
LAYER_SENATE = 56
LAYER_ASSEMBLY = 58
LAYER_COUNTIES = 82

ROOFTOP_TYPES = {"PointAddress", "Subaddress", "StreetAddress"}


class AddressLookupError(ValueError):
    pass


@dataclass
class AddressLocation:
    query: str
    matched_address: str
    county: str
    city: str
    lat: float
    lng: float
    us_house: str
    state_senate: str
    state_assembly: str
    school_districts: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def lookup_address(query: str) -> AddressLocation:
    text = (query or "").strip()
    if not text:
        raise AddressLookupError("Enter a street address.")
    lng, lat, matched = _geocode(text)
    layers = {
        "county": LAYER_COUNTIES,
        "place": LAYER_PLACES,
        "congress": LAYER_CONGRESS,
        "senate": LAYER_SENATE,
        "assembly": LAYER_ASSEMBLY,
        "unified": LAYER_UNIFIED,
        "secondary": LAYER_SECONDARY,
        "elementary": LAYER_ELEMENTARY,
    }
    found = _query_layers(lng, lat, layers)
    county = _basename(found.get("county"))
    if county not in CA_COUNTIES:
        raise AddressLookupError(
            "That address is not inside a California county this guide covers."
        )
    city = _basename(found.get("place"))
    schools = []
    for key in ("unified", "secondary", "elementary"):
        name = _basename(found.get(key))
        if name and name not in schools:
            schools.append(name)
    us_house = _district_number(found.get("congress"))
    state_senate = _district_number(found.get("senate"))
    state_assembly = _district_number(found.get("assembly"))
    located = AddressLocation(
        query=text,
        matched_address=matched,
        county=county,
        city=city,
        lat=lat,
        lng=lng,
        us_house=us_house,
        state_senate=state_senate,
        state_assembly=state_assembly,
        school_districts=schools,
    )
    located.notes = _notes(located)
    return located


def address_keeps_item(*, title: str, level: str, city: str, located: AddressLocation) -> bool:
    """Keep a local race or measure that applies to this address.

    Supervisor districts, council districts, and trustee areas stay in the
    report because the Census layers do not assign those numbers.
    """
    level_l = (level or "").lower()
    if "school" in level_l:
        return _school_match(title, located.school_districts)
    if "special" in level_l:
        return bool(located.city) and _has_word(title, located.city)
    if "municipal" in level_l:
        if not located.city:
            return False
        if city:
            return city.lower() == located.city.lower()
        return _has_word(title, located.city)
    if level_l == "county" or level_l.startswith("county"):
        if city and located.city and city.lower() != located.city.lower():
            return False
        return True

    other_city = infer_city_from_text(title, located.county)
    if other_city and located.city and other_city.lower() != located.city.lower():
        return False
    if located.city and _has_word(title, located.city):
        return True
    if _school_match(title, located.school_districts):
        return True
    if _has_word(title, located.county):
        return True
    return not other_city


def _notes(located: AddressLocation) -> list[str]:
    districts = []
    if located.us_house:
        districts.append(f"Congressional District {located.us_house}")
    if located.state_senate:
        districts.append(f"State Senate District {located.state_senate}")
    if located.state_assembly:
        districts.append(f"Assembly District {located.state_assembly}")
    district_text = ", ".join(districts) if districts else "no legislative district returned"
    schools = "; ".join(located.school_districts) if located.school_districts else "none identified"
    where = f"{located.city}, {located.county} County" if located.city else f"unincorporated {located.county} County"
    notes = [
        (
            f"Address matched to {located.matched_address} in {where}. "
            f"Districts from U.S. Census TIGERweb: {district_text}. "
            f"School district: {schools}."
        ),
        (
            "County supervisor districts, city council districts, and school-board trustee areas "
            "are not in that lookup, so those contests are listed for the whole county, city, or "
            "school district. Special-district contests are listed only when the district name "
            "includes this city. Confirm the ballot against the county sample ballot."
        ),
    ]
    if not located.city:
        notes.append("This address is outside an incorporated city, so city council contests are omitted.")
    return notes


def _geocode(text: str) -> tuple[float, float, str]:
    params = urllib.parse.urlencode(
        {
            "SingleLine": text,
            "f": "json",
            "outFields": "Addr_type,City,Region,Subregion,StAddr,Postal",
            "maxLocations": "1",
            "sourceCountry": "USA",
        }
    )
    data = _get_json(f"{ESRI_GEOCODE}?{params}")
    candidates = data.get("candidates") or []
    if not candidates:
        raise AddressLookupError(
            "No match for that address. Include the house number, street, city, and state."
        )
    hit = candidates[0]
    attrs = hit.get("attributes") or {}
    region = str(attrs.get("Region") or "")
    if region not in {"California", "CA"}:
        raise AddressLookupError("That address is outside California.")
    addr_type = str(attrs.get("Addr_type") or "")
    score = float(hit.get("score") or 0)
    if addr_type not in ROOFTOP_TYPES or score < 90:
        raise AddressLookupError(
            "That did not match a specific street address. Include the house number, street, city, and state."
        )
    loc = hit.get("location") or {}
    try:
        lng = float(loc["x"])
        lat = float(loc["y"])
    except (KeyError, TypeError, ValueError) as exc:
        raise AddressLookupError("The geocoder did not return a point for that address.") from exc
    matched = str(hit.get("address") or text)
    return lng, lat, matched


def _query_layers(lng: float, lat: float, layers: dict[str, int]) -> dict[str, dict]:
    def one(item: tuple[str, int]) -> tuple[str, dict]:
        key, layer_id = item
        params = urllib.parse.urlencode(
            {
                "geometry": f"{lng},{lat}",
                "geometryType": "esriGeometryPoint",
                "inSR": "4326",
                "spatialRel": "esriSpatialRelIntersects",
                "outFields": "NAME,BASENAME",
                "returnGeometry": "false",
                "f": "json",
            }
        )
        data = _get_json(f"{TIGER}/{layer_id}/query?{params}")
        if data.get("error"):
            message = (data["error"] or {}).get("message") or "Census map request failed."
            raise AddressLookupError(message)
        features = data.get("features") or []
        attrs = (features[0].get("attributes") if features else {}) or {}
        return key, attrs

    out: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=len(layers)) as pool:
        for key, attrs in pool.map(one, layers.items()):
            out[key] = attrs
    return out


def _get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=40) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except AddressLookupError:
        raise
    except Exception as exc:
        raise AddressLookupError(f"Address lookup failed: {exc}") from exc


def _basename(attrs: dict | None) -> str:
    if not attrs:
        return ""
    return str(attrs.get("BASENAME") or attrs.get("NAME") or "").strip()


def _district_number(attrs: dict | None) -> str:
    raw = _basename(attrs)
    if not raw:
        return ""
    if raw.isdigit():
        return str(int(raw))
    match = re.search(r"(\d+)", raw)
    return str(int(match.group(1))) if match else ""


def _has_word(text: str, word: str) -> bool:
    if not word:
        return False
    return bool(re.search(rf"\b{re.escape(word)}\b", text or "", flags=re.I))


def _school_match(title: str, names: list[str]) -> bool:
    hay = (title or "").lower()
    for name in names:
        base = name.lower().strip()
        if base and base in hay:
            return True
        short = re.sub(r"\s+school district$", "", base).strip()
        if short and short in hay:
            return True
    return False
