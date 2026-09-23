#!/usr/bin/env python3
"""Turn Yolo Data Multiple Sheets.xlsx into site JSON, including employer coordinates."""

from __future__ import annotations

import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parents[1]
WORKBOOK = ROOT / "Yolo Data Multiple Sheets.xlsx"
OUT_PROFILE = ROOT / "docs" / "data" / "yolo-profile.json"
OUT_COUNTY = ROOT / "docs" / "data" / "yolo-county.geojson"
GEOCODE_CACHE = ROOT / "tools" / "yolo_employer_geocodes.json"

COUNTY_URL = (
    "https://gis.yolocounty.gov/ext/rest/services/Public/Baselayers/"
    "FeatureServer/0/query?where=1%3D1&outFields=Name,SQ_MILES"
    "&returnGeometry=true&outSR=4326&f=geojson"
)
NOMINATIM = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "yolo-profile-export/1.0 (local civic research)"

# Street addresses checked against public records. City-level pins are labeled in `note`.
EMPLOYER_PLACES = {
    "Beckman Coulter Inc": {
        "query": "1584 Enterprise Blvd, West Sacramento, California",
        "note": "1584 Enterprise Blvd, from the EDD employer record.",
    },
    "Cache Creek Casino Resort": {
        "query": "Cache Creek Casino, Brooks, California",
        "note": "14455 State Highway 16, from the EDD employer record.",
    },
    "Capital Express Lines": {
        "query": "1925 Enterprise Blvd, West Sacramento, California",
        "note": "1925 Enterprise Blvd, the company's listed West Sacramento branch.",
    },
    "City of Davis": {
        "query": "23 Russell Boulevard, Davis, California",
        "note": "Davis City Hall, 23 Russell Boulevard.",
    },
    "City of Davis-City Manager Ofc": {
        "query": "23 Russell Boulevard, Davis, California",
        "note": "City Manager's Office at Davis City Hall, 23 Russell Boulevard.",
    },
    "Clark Pacific": {
        "query": "710 Riverpoint Court, West Sacramento, California",
        "note": "710 Riverpoint Court, Suite 100, the company's West Sacramento headquarters.",
    },
    "Dennis Blazona Constr Inc": {
        "query": "525 Harbor Blvd, West Sacramento, California",
        "note": "525 Harbor Blvd, the listed address for Blazona Concrete Construction.",
    },
    "KOVR": {
        "query": "2713 KOVR Drive, West Sacramento, California",
        "note": "2713 KOVR Drive, the station's main studio in the FCC public file.",
    },
    "Nor-Cal Beverage Co": {
        "query": "3600 Massie Ct, West Sacramento, California",
        "note": "3600 Massie Court, the listed distribution center.",
    },
    "Pacific Coast Producers": {
        "query": "1376 Lemen Avenue, Woodland, California",
        "note": "1376 Lemen Avenue, the company's Woodland tomato plant.",
    },
    "Procurement Office": {
        "query": "West Sacramento, Yolo County, California",
        "note": "Listed in West Sacramento. A street address was not confirmed, so the pin marks the city.",
        "precision": "city",
    },
    "Promega Corp": {
        "query": "Madison, Yolo County, California",
        "note": "EDD lists 2800 Woods Hollow Rd with a Madison, CA ZIP. That street is Promega's Wisconsin headquarters, so the pin marks Madison, California only.",
        "precision": "city",
    },
    "Target Distribution Ctr": {
        "query": "2050 E Beamer St, Woodland, California",
        "note": "2050 East Beamer Street.",
    },
    "Treasure Chest Advg Co Inc": {
        "query": "1201 Shore Street, West Sacramento, California",
        "note": "1201 Shore Street. A 1994 OSHA record lists Shore Drive at this number. The worksite may no longer be active.",
    },
    "University of California Davis": {
        "query": "1 Shields Avenue, Davis, California",
        "note": "Main campus, 1 Shields Avenue.",
    },
    "Yolo County District Attorney": {
        "query": "301 2nd Street, Woodland, California",
        "note": "301 Second Street, the office address published by the District Attorney.",
    },
    "Yolo County Office of Edu": {
        "query": "1280 Santa Anita Court, Woodland, California",
        "note": "1280 Santa Anita Court, the address on the California school directory.",
    },
    "Yolo County Sheriff-Civil Div": {
        "query": "140 Tony Diaz Drive, Woodland, California",
        "note": "140 Tony Diaz Drive, the Sheriff's Civil Section address.",
    },
    "Woodland Healthcare Foundation": {
        "query": "1325 Cottonwood Street, Woodland, California",
        "note": "Shown at Woodland Healthcare, 1325 Cottonwood Street. A separate foundation address was not confirmed.",
    },
}

RACE_HEADS = [
    "White",
    "Black or African American",
    "American Indian and Alaska Native",
    "Asian",
    "Native Hawaiian and Other Pacific Islander",
    "Some Other Race",
]


def num(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return value
    text = str(value).strip().replace(",", "").replace("%", "")
    text = text.replace("±", "").replace("+/-", "").strip()
    if text in {"", "(X)", "N", "-"}:
        return None
    try:
        if "." in text:
            return float(text)
        return int(text)
    except ValueError:
        return None


def text(value):
    if value is None:
        return ""
    return str(value).replace("\xa0", " ").strip()


def moe(value):
    raw = text(value)
    if not raw or raw == "(X)":
        return None
    cleaned = raw.replace("±", "").replace("+/-", "").replace(",", "").strip()
    try:
        return float(cleaned) if "." in cleaned else int(cleaned)
    except ValueError:
        return None


def rows(ws):
    return list(ws.iter_rows(values_only=True))


def sectioned(table_rows, label_idx=0, start=3):
    """Split ACS-style tables on blank-estimate header rows."""
    sections = []
    current = {"title": "Overview", "rows": []}
    for row in table_rows[start:]:
        label = text(row[label_idx])
        if not label:
            continue
        estimates = [num(cell) for cell in row[label_idx + 1 :]]
        if all(value is None for value in estimates) and label == label.upper():
            if current["rows"]:
                sections.append(current)
            current = {"title": label.title(), "rows": []}
            continue
        current["rows"].append(row)
    if current["rows"]:
        sections.append(current)
    return sections


def load_county():
    if not OUT_COUNTY.exists() or OUT_COUNTY.stat().st_size < 1000:
        req = urllib.request.Request(COUNTY_URL, headers={"User-Agent": USER_AGENT})
        data = urllib.request.urlopen(req, timeout=60).read()
        OUT_COUNTY.parent.mkdir(parents=True, exist_ok=True)
        OUT_COUNTY.write_text(data.decode("utf-8"), encoding="utf-8")
    return json.loads(OUT_COUNTY.read_text(encoding="utf-8"))


def geocode_query(query, cache):
    if query in cache and cache[query].get("lat") is not None:
        return cache[query]
    url = NOMINATIM + "?" + urllib.parse.urlencode(
        {"q": query, "format": "jsonv2", "limit": 1, "countrycodes": "us"}
    )
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        hits = json.loads(urllib.request.urlopen(req, timeout=30).read().decode())
    except Exception as exc:
        hits = []
        error = str(exc)
    else:
        error = ""
    time.sleep(1.1)
    if not hits:
        record = {"lat": None, "lng": None, "label": "", "precision": "unmatched", "error": error}
    else:
        hit = hits[0]
        record = {
            "lat": float(hit["lat"]),
            "lng": float(hit["lon"]),
            "label": hit.get("display_name", ""),
            "precision": hit.get("addresstype") or hit.get("type") or "place",
        }
    cache[query] = record
    return record


def geocode(name, city, cache):
    return geocode_query(f"{name}, {city}, Yolo County, California", cache)


def ring_contains(ring, lng, lat):
    inside = False
    j = len(ring) - 1
    for i, point in enumerate(ring):
        yi, xi = point[1], point[0]
        yj, xj = ring[j][1], ring[j][0]
        if ((yi > lat) != (yj > lat)) and (lng < (xj - xi) * (lat - yi) / ((yj - yi) or 1e-12) + xi):
            inside = not inside
        j = i
    return inside


def county_contains(geo, lng, lat):
    if lng is None or lat is None:
        return False
    geometry = geo["features"][0]["geometry"]
    polygons = geometry["coordinates"] if geometry["type"] == "MultiPolygon" else [geometry["coordinates"]]
    for polygon in polygons:
        if ring_contains(polygon[0], lng, lat):
            return True
    return False


def parse_demographics(ws):
    data = rows(ws)
    blocks = []
    current = None
    for row in data[3:]:
        label = text(row[0])
        if not label:
            continue
        estimate = row[1]
        percent = row[2]
        if estimate is None and percent is None:
            current = {"title": label, "rows": []}
            blocks.append(current)
            continue
        if current is None:
            current = {"title": "Overview", "rows": []}
            blocks.append(current)
        current["rows"].append(
            {
                "label": label,
                "estimate": num(estimate) if not isinstance(estimate, str) or re.search(r"\d", estimate) else text(estimate),
                "percent": text(percent) if isinstance(percent, str) and percent not in {"(X)", ""} else num(percent),
                "percent_label": text(percent),
            }
        )
    return blocks


def parse_income(ws):
    data = rows(ws)
    headers = [text(cell) for cell in data[1][1:]]
    records = []
    medians = []
    for row in data[3:]:
        label = text(row[0])
        if not label:
            continue
        values = {}
        for header, cell in zip(headers, row[1:]):
            raw = text(cell)
            values[header] = {"raw": raw, "value": num(cell)}
        item = {"label": label, "values": values}
        if label.lower().startswith("median") or label.lower().startswith("mean") or label == "Total":
            medians.append(item)
        else:
            records.append(item)
    return {"groups": headers, "distribution": records, "summaries": medians}


def parse_earnings(ws):
    data = rows(ws)
    bands = []
    education = []
    headlines = []
    mode = "headline"
    for row in data[3:]:
        label = text(row[0])
        if not label:
            continue
        if label == label.upper() and num(row[1]) is None:
            mode = "education" if "EDUCAT" in label else "bands"
            continue
        item = {
            "label": label,
            "total": num(row[1]),
            "total_label": text(row[2]),
            "male": num(row[3]),
            "male_label": text(row[4]),
            "female": num(row[5]),
            "female_label": text(row[6]),
        }
        if mode == "headline":
            headlines.append(item)
        elif mode == "bands":
            bands.append(item)
        else:
            education.append(item)
    return {"headlines": headlines, "bands": bands, "education": education}


MAJOR_OCCUPATIONS = {
    "Management, business, science, and arts occupations",
    "Service occupations",
    "Sales and office occupations",
    "Natural resources, construction, and maintenance occupations",
    "Production, transportation, and material moving occupations",
}


def occupation_item(row):
    raw = text(row[0])
    return {
        "label": raw.rstrip(":"),
        "total": num(row[1]),
        "male": num(row[2]),
        "male_percent": text(row[3]),
        "female": num(row[4]),
        "female_percent": text(row[5]),
        "children": [],
        "_header": raw.endswith(":"),
    }


def nest_occupations(pending, parent_total):
    children = []
    consumed = 0
    while pending:
        nxt = pending[0]
        if nxt["label"] in MAJOR_OCCUPATIONS:
            break
        if parent_total is not None and consumed >= parent_total - 1 and children:
            break
        row = pending.pop(0)
        row.pop("_header", None)
        if pending and pending[0].get("_header") is False and row["total"]:
            # Header rows are detected before pop via the original flag.
            pass
        children.append(row)
        consumed += row["total"] or 0
        if parent_total is not None and consumed >= parent_total - 1:
            break
    return children


def parse_occupations(ws):
    data = rows(ws)
    parsed = [occupation_item(row) for row in data[3:] if text(row[0])]
    total = parsed.pop(0)
    total.pop("_header", None)
    groups = []
    pending = parsed
    while pending:
        row = pending.pop(0)
        is_header = row.pop("_header", False)
        if row["label"] not in MAJOR_OCCUPATIONS:
            continue
        kids = []
        consumed = 0
        while pending and pending[0]["label"] not in MAJOR_OCCUPATIONS:
            if consumed >= (row["total"] or 0) - 1 and kids:
                break
            child = pending.pop(0)
            child_header = child.pop("_header", False)
            if child_header:
                nested = []
                nested_sum = 0
                while pending and pending[0]["label"] not in MAJOR_OCCUPATIONS and not pending[0].get("_header"):
                    if nested_sum >= (child["total"] or 0) - 1 and nested:
                        break
                    leaf = pending.pop(0)
                    leaf.pop("_header", None)
                    nested.append(leaf)
                    nested_sum += leaf["total"] or 0
                child["children"] = nested
            kids.append(child)
            consumed += child["total"] or 0
        row["children"] = kids
        groups.append(row)
        if not is_header:
            continue
    return {"total": total, "groups": groups}


def parse_poverty(ws):
    data = rows(ws)
    sections = []
    current = {"title": "All people", "rows": []}
    for row in data[3:]:
        label = text(row[0])
        if not label:
            continue
        if num(row[1]) is None and num(row[5]) is None:
            if current["rows"]:
                sections.append(current)
            current = {"title": label.title() if label.isupper() else label, "rows": []}
            continue
        current["rows"].append(
            {
                "label": label,
                "total": num(row[1]),
                "total_moe": moe(row[2]),
                "below": num(row[3]),
                "below_moe": moe(row[4]),
                "percent": num(row[5]),
                "percent_moe": moe(row[6]),
            }
        )
    if current["rows"]:
        sections.append(current)
    return sections


def locate(query, cache, county_geo, precision=None):
    place = geocode_query(query, cache)
    lat = place.get("lat")
    lng = place.get("lng")
    label = place.get("label") or ""
    kind = precision or place.get("precision") or "place"
    if lat is None or not county_contains(county_geo, lng, lat):
        return {"lat": None, "lng": None, "label": label, "precision": "unmatched"}
    return {"lat": lat, "lng": lng, "label": label, "precision": kind}


# One map pin per local. Queries are Yolo workplaces. Halls outside the county are described in the note.
UNION_SITES = {
    "UAW Local 4811": {
        "query": "1 Shields Avenue, Davis, California",
        "place_name": "University of California, Davis",
        "city": "Davis",
        "note": "Statewide local. No Yolo office found, so the pin is UC Davis.",
    },
    "Teamsters Local 2010": {
        "query": "1 Shields Avenue, Davis, California",
        "place_name": "University of California, Davis",
        "city": "Davis",
        "note": "UC system local. No Yolo office found, so the pin is UC Davis.",
    },
    "UPTE-CWA Local 9119": {
        "query": "1 Shields Avenue, Davis, California",
        "place_name": "University of California, Davis",
        "city": "Davis",
        "note": "UC system local. No Yolo office found, so the pin is UC Davis.",
    },
    "AFSCME Local 3299": {
        "query": "1 Shields Avenue, Davis, California",
        "place_name": "University of California, Davis",
        "city": "Davis",
        "note": "UC system local. No Yolo office found, so the pin is UC Davis.",
    },
    "UC-AFT": {
        "query": "1 Shields Avenue, Davis, California",
        "place_name": "University of California, Davis",
        "city": "Davis",
        "note": "UC system local. No Yolo office found, so the pin is UC Davis.",
    },
    "UAW (non-academic)": {
        "query": "1 Shields Avenue, Davis, California",
        "place_name": "University of California, Davis",
        "city": "Davis",
        "note": "UC system local. No Yolo office found, so the pin is UC Davis.",
    },
    "CIR/SEIU": {
        "query": "1 Shields Avenue, Davis, California",
        "place_name": "University of California, Davis",
        "city": "Davis",
        "note": "Statewide resident union. Some UC Davis residents work in Sacramento. Pin is the Davis campus.",
    },
    "Federated University Police Officers Association": {
        "query": "UC Davis Police Department, Davis, California",
        "place_name": "UC Davis Police Department",
        "city": "Davis",
        "note": "Campus association. No separate hall found. Pin is the UC Davis police department.",
    },
    "IAFF Local 4920": {
        "query": "UC Davis Fire Department, Davis, California",
        "place_name": "UC Davis Fire Department",
        "city": "Davis",
        "note": "Campus fire local. Pin is the UC Davis Fire Department on Kleiber Hall Drive.",
    },
    "Union of American Physicians and Dentists / AFSCME Local 206": {
        "query": "1 Shields Avenue, Davis, California",
        "place_name": "University of California, Davis",
        "city": "Davis",
        "note": "Statewide local. A strict Yolo headcount is not published. Pin is the Davis campus.",
    },
    "California Nurses Association / NNU": {
        "query": "2000 County Road 99D, Davis, California",
        "place_name": "Sutter Davis Hospital",
        "city": "Davis",
        "note": "Union office is outside Yolo. Pin is Sutter Davis Hospital, the counted Yolo nurse unit. The same union also covers some UC nurses.",
    },
    "SEIU Local 2015": {
        "query": "1850 E 8th Street, Davis, California",
        "place_name": "Courtyard Healthcare Center",
        "city": "Davis",
        "note": "Statewide long-term care local. Pin is Courtyard Healthcare Center, 1850 E 8th Street.",
    },
    "Workers United / SEIU": {
        "query": "623 2nd Street, Davis, California",
        "place_name": "Starbucks, 623 2nd Street",
        "city": "Davis",
        "note": "No Yolo hall found. Pin is the Davis Starbucks named in the inventory. A Dunnigan Starbucks is also listed, without a confirmed street address.",
    },
    "SEIU Local 1021": {
        "query": "1411 West Covell Boulevard, Davis, California",
        "place_name": "Peet's Coffee, 1411 West Covell Boulevard",
        "city": "Davis",
        "note": "Regional office is in Sacramento (5450 Power Inn Road). Pin is the Davis Peet's store.",
    },
    "Teamsters Local 150": {
        "query": "3575 Reed Avenue, West Sacramento, California",
        "place_name": "Tony's Fine Foods / UNFI",
        "city": "West Sacramento",
        "note": "Hall is 7120 East Parkway, Sacramento, outside Yolo. Pin is Tony's Fine Foods / UNFI at 3575 Reed Avenue. UPS in West Sacramento is another workplace.",
    },
    "SEIU-UHW West": {
        "query": "1325 Cottonwood Street, Woodland, California",
        "place_name": "Woodland Memorial Hospital",
        "city": "Woodland",
        "note": "Regional union. Pin is Woodland Memorial Hospital. The inventory says this small unit should be rechecked.",
    },
    "Stationary Engineers Local 39": {
        "query": "625 Court Street, Woodland, California",
        "place_name": "Yolo County Administration Building",
        "city": "Woodland",
        "note": "Hall is 337 Valencia Street, San Francisco. Pin is the county administration building. The local also represents City of West Sacramento workers.",
    },
    "Yolo County Supervisor & Professional Employees Association": {
        "query": "625 Court Street, Woodland, California",
        "place_name": "Yolo County Administration Building",
        "city": "Woodland",
        "note": "County employee association. No separate hall found. Pin is 625 Court Street.",
    },
    "Yolo County Attorneys Association": {
        "query": "625 Court Street, Woodland, California",
        "place_name": "Yolo County Administration Building",
        "city": "Woodland",
        "note": "County employee association. No separate hall found. Pin is 625 Court Street.",
    },
    "Deputy County Counsel Association": {
        "query": "625 Court Street, Woodland, California",
        "place_name": "Yolo County Administration Building",
        "city": "Woodland",
        "note": "County employee association. No separate hall found. Pin is 625 Court Street.",
    },
    "Yolo County Probation Association": {
        "query": "2780 East Gibson Road, Woodland, California",
        "place_name": "Yolo County Probation Department",
        "city": "Woodland",
        "note": "Employee association. No separate hall found. Pin is the probation department, 2780 East Gibson Road.",
    },
    "Yolo County Deputy Sheriffs Association": {
        "query": "140 Tony Diaz Drive, Woodland, California",
        "place_name": "Yolo County Sheriff's Office",
        "city": "Woodland",
        "note": "Employee association. No separate hall found. Pin is the sheriff's office, 140 Tony Diaz Drive.",
    },
    "Yolo County Correctional Officers Association": {
        "query": "2420 East Gibson Road, Woodland, California",
        "place_name": "Monroe Detention Center",
        "city": "Woodland",
        "note": "Employee association. No separate hall found. Pin is Monroe Detention Center, 2420 East Gibson Road.",
    },
    "Yolo County Sheriff's Management Association": {
        "query": "140 Tony Diaz Drive, Woodland, California",
        "place_name": "Yolo County Sheriff's Office",
        "city": "Woodland",
        "note": "Employee association. No separate hall found. Pin is the sheriff's office, 140 Tony Diaz Drive.",
    },
    "Program, Administrative & Support Employees Association": {
        "query": "23 Russell Boulevard, Davis, California",
        "place_name": "Davis City Hall",
        "city": "Davis",
        "note": "City employee association. No separate hall found. Pin is Davis City Hall.",
    },
    "Davis Firefighters Local 3494": {
        "query": "530 5th Street, Davis, California",
        "place_name": "Davis Fire Station 31",
        "city": "Davis",
        "note": "No separate hall found. Pin is the headquarters station, 530 Fifth Street.",
    },
    "Davis Police Officers Association": {
        "query": "2600 5th Street, Davis, California",
        "place_name": "Davis Police Department",
        "city": "Davis",
        "note": "Employee association. No separate hall found. Pin is the police department, 2600 Fifth Street.",
    },
    "Davis City Employees Association": {
        "query": "23 Russell Boulevard, Davis, California",
        "place_name": "Davis City Hall",
        "city": "Davis",
        "note": "City employee association. No separate hall found. Pin is Davis City Hall.",
    },
    "Davis Waste Water Treatment Plant Association": {
        "query": "1717 5th Street, Davis, California",
        "place_name": "Davis Public Works utilities yard",
        "city": "Davis",
        "note": "Employee association. No separate hall found. Pin is 1717 Fifth Street, the city's published utilities operations yard.",
    },
    "Woodland City Employees Association": {
        "query": "300 1st Street, Woodland, California",
        "place_name": "Woodland City Hall",
        "city": "Woodland",
        "note": "City employee association. No separate hall found. Pin is Woodland City Hall, 300 First Street.",
    },
    "Woodland Mid-Management Professional Association": {
        "query": "300 1st Street, Woodland, California",
        "place_name": "Woodland City Hall",
        "city": "Woodland",
        "note": "City employee association. No separate hall found. Pin is Woodland City Hall.",
    },
    "Woodland Police Officers Association": {
        "query": "1000 Lincoln Avenue, Woodland, California",
        "place_name": "Woodland Police Department",
        "city": "Woodland",
        "note": "Employee association. No separate hall found. Pin is 1000 Lincoln Avenue.",
    },
    "Woodland Police Supervisors Association": {
        "query": "1000 Lincoln Avenue, Woodland, California",
        "place_name": "Woodland Police Department",
        "city": "Woodland",
        "note": "Employee association. No separate hall found. Pin is 1000 Lincoln Avenue.",
    },
    "Woodland Police Mid-Management Unit": {
        "query": "1000 Lincoln Avenue, Woodland, California",
        "place_name": "Woodland Police Department",
        "city": "Woodland",
        "note": "Employee association. No separate hall found. Pin is 1000 Lincoln Avenue.",
    },
    "Woodland Professional Firefighters Association": {
        "query": "101 Court Street, Woodland, California",
        "place_name": "Woodland Fire Station 1",
        "city": "Woodland",
        "note": "No separate hall found. Pin is Fire Station 1, 101 Court Street.",
    },
    "Woodland Fire Mid-Management Association": {
        "query": "101 Court Street, Woodland, California",
        "place_name": "Woodland Fire Station 1",
        "city": "Woodland",
        "note": "No separate hall found. Pin is Fire Station 1, 101 Court Street.",
    },
    "West Sacramento Firefighters Association": {
        "query": "2040 Lake Washington Boulevard, West Sacramento, California",
        "place_name": "West Sacramento Fire Department",
        "city": "West Sacramento",
        "note": "No separate hall found. Pin is the fire administration station at 2040 Lake Washington Boulevard.",
    },
    "West Sacramento Battalion Chiefs Association": {
        "query": "2040 Lake Washington Boulevard, West Sacramento, California",
        "place_name": "West Sacramento Fire Department",
        "city": "West Sacramento",
        "note": "No separate hall found. Pin is the fire administration station at 2040 Lake Washington Boulevard.",
    },
    "West Sacramento Police Officers Association": {
        "query": "550 Jefferson Boulevard, West Sacramento, California",
        "place_name": "West Sacramento Police Department",
        "city": "West Sacramento",
        "note": "Employee association. No separate hall found. Pin is 550 Jefferson Boulevard.",
    },
    "West Sacramento Police Management Association": {
        "query": "550 Jefferson Boulevard, West Sacramento, California",
        "place_name": "West Sacramento Police Department",
        "city": "West Sacramento",
        "note": "Employee association. No separate hall found. Pin is 550 Jefferson Boulevard.",
    },
    "Davis Teachers Association / CTA": {
        "query": "526 B Street, Davis, California",
        "place_name": "Davis Joint Unified School District",
        "city": "Davis",
        "note": "No separate hall found. Pin is the district office, 526 B Street.",
    },
    "CSEA Chapter 572": {
        "query": "526 B Street, Davis, California",
        "place_name": "Davis Joint Unified School District",
        "city": "Davis",
        "note": "Chapter office not found apart from the district. Pin is 526 B Street.",
    },
    "Woodland Education Association / CTA": {
        "query": "435 6th Street, Woodland, California",
        "place_name": "Woodland Joint Unified School District",
        "city": "Woodland",
        "note": "No separate hall found. Pin is the district office, 435 Sixth Street.",
    },
    "CSEA Chapter 118": {
        "query": "435 6th Street, Woodland, California",
        "place_name": "Woodland Joint Unified School District",
        "city": "Woodland",
        "note": "Chapter office not found apart from the district. Pin is 435 Sixth Street.",
    },
    "West Sacramento Teachers Association / CTA": {
        "query": "930 Westacre Road, West Sacramento, California",
        "place_name": "Washington Unified School District",
        "city": "West Sacramento",
        "note": "No separate hall found. Pin is the district office, 930 Westacre Road.",
    },
    "CSEA Riverview Chapter 168": {
        "query": "930 Westacre Road, West Sacramento, California",
        "place_name": "Washington Unified School District",
        "city": "West Sacramento",
        "note": "Chapter office not found apart from the district. Pin is 930 Westacre Road.",
    },
    "Winters Area Education Association": {
        "query": "909 Grant Avenue, Winters, California",
        "place_name": "Winters Joint Unified School District",
        "city": "Winters",
        "note": "No separate hall found. Pin is the district office, 909 West Grant Avenue.",
    },
    "WAPPSU": {
        "query": "909 Grant Avenue, Winters, California",
        "place_name": "Winters Joint Unified School District",
        "city": "Winters",
        "note": "Pupil personnel association. No separate hall found. Pin is the district office.",
    },
    "Yolo Education Association": {
        "query": "1280 Santa Anita Court, Woodland, California",
        "place_name": "Yolo County Office of Education",
        "city": "Woodland",
        "note": "No separate hall found. Pin is the county office of education, 1280 Santa Anita Court.",
    },
    "AFSCME Council 57, Local 146": {
        "query": "1280 Santa Anita Court, Woodland, California",
        "place_name": "Yolo County Office of Education",
        "city": "Woodland",
        "note": "No Yolo hall found. Pin is the county office of education.",
    },
    "Amalgamated Transit Union Local 256": {
        "query": "350 Industrial Way, Woodland, California",
        "place_name": "Yolobus / Yolo Transportation District",
        "city": "Woodland",
        "note": "Local 256's hall is in Sacramento. Pin is the Yolobus office at 350 Industrial Way.",
    },
    "UFCW Local 5": {
        "query": "1601 West Capitol Avenue, West Sacramento, California",
        "place_name": "Raley's, 1601 West Capitol Avenue",
        "city": "West Sacramento",
        "note": "Local 5's office is in Hayward. The inventory does not name one store, so the pin is a West Sacramento Raley's at 1601 West Capitol Avenue.",
    },
    "APWU Sacramento Area Local 66": {
        "query": "West Sacramento Post Office, California",
        "place_name": "West Sacramento Post Office",
        "city": "West Sacramento",
        "note": "Sacramento Area Local 66 is based in Sacramento. Pin is the West Sacramento Post Office at 1601 Merkley Avenue.",
    },
}

CSEA_SITES = {
    "Winters Joint Unified School District": {
        "query": "909 Grant Avenue, Winters, California",
        "place_name": "Winters Joint Unified School District",
        "city": "Winters",
        "note": "CSEA chapter for Winters classified employees. No separate hall found. Pin is the district office.",
    },
    "Yolo County Office of Education": {
        "query": "1280 Santa Anita Court, Woodland, California",
        "place_name": "Yolo County Office of Education",
        "city": "Woodland",
        "note": "CSEA unit at the county office of education. No separate hall found. Pin is 1280 Santa Anita Court.",
    },
}


def site_for_union(union, employer):
    if union == "CSEA":
        return CSEA_SITES.get(employer)
    return UNION_SITES.get(union)


def parse_employers(ws, cache, county_geo):
    found = []
    for row in rows(ws)[1:]:
        name = text(row[0])
        city = text(row[1])
        industry = text(row[2])
        if not name:
            continue
        spec = EMPLOYER_PLACES.get(name)
        if spec:
            place = locate(spec["query"], cache, county_geo, spec.get("precision"))
            note = spec["note"]
        else:
            place = locate(f"{name}, {city}, Yolo County, California", cache, county_geo)
            note = place.get("label") or ""
        found.append(
            {
                "name": name,
                "city": city,
                "industry": industry,
                "lat": place["lat"],
                "lng": place["lng"],
                "geocode_label": place.get("label", ""),
                "precision": place.get("precision", ""),
                "note": note,
            }
        )
    return found


def parse_unions(ws):
    data = rows(ws)
    note = text(data[1][0])
    header = [text(cell) for cell in data[3]]
    records = []
    for row in data[4:]:
        if not text(row[0]):
            continue
        item = {}
        for key, cell in zip(header, row):
            if key == "Workers represented":
                item["workers"] = num(cell)
            elif key == "Union / local":
                item["union"] = text(cell)
            elif key == "Employer / workplace":
                item["employer"] = text(cell)
            elif key == "Bargaining unit / workers":
                item["unit"] = text(cell)
            elif key == "City / area":
                item["city"] = text(cell)
            elif key == "Sector":
                item["sector"] = text(cell)
            elif key == "Industry":
                item["industry"] = text(cell)
            elif key == "Count basis":
                item["count_basis"] = text(cell)
            elif key == "Evidence status":
                item["status"] = text(cell)
            elif key == "Union contact / website":
                item["contact"] = text(cell)
            elif key == "Evidence source URL":
                item["source"] = text(cell)
            elif key == "Notes":
                item["notes"] = text(cell)
        records.append(item)
    return {"note": note, "rows": records}


def union_markers(records, cache, county_geo):
    grouped = {}
    for row in records:
        union = row.get("union") or ""
        if union.lower().startswith("unknown"):
            continue
        spec = site_for_union(union, row.get("employer"))
        if not spec:
            continue
        key = (union, spec["query"])
        bucket = grouped.setdefault(key, {"spec": spec, "union": union, "rows": []})
        bucket["rows"].append(row)
    markers = []
    for (_union, _query), bucket in grouped.items():
        spec = bucket["spec"]
        place = locate(spec["query"], cache, county_geo)
        workers = [row.get("workers") for row in bucket["rows"] if row.get("workers")]
        markers.append(
            {
                "name": bucket["union"],
                "place_name": spec["place_name"],
                "city": spec["city"],
                "note": spec["note"],
                "lat": place["lat"],
                "lng": place["lng"],
                "geocode_label": place.get("label") or "",
                "units": [
                    {
                        "employer": row.get("employer"),
                        "unit": row.get("unit"),
                        "workers": row.get("workers"),
                        "status": row.get("status"),
                        "city": row.get("city"),
                    }
                    for row in bucket["rows"]
                ],
                "workers_counted": sum(workers) if workers else None,
                "unit_count": len(bucket["rows"]),
            }
        )
    return markers


def slim_row(row):
    return {
        "label": row["label"],
        "estimate": row.get("estimate"),
        "percent": row.get("percent_label") or "",
    }


def race_groups(blocks):
    rows = next(block["rows"] for block in blocks if block["title"] == "RACE")
    heads = set(RACE_HEADS)
    groups = []
    current = None
    for row in rows:
        label = row["label"]
        if label in heads or label == "Two or More Races":
            existing = next((group for group in groups if group["label"] == label), None)
            if existing:
                current = existing
                continue
            current = {**slim_row(row), "children": []}
            groups.append(current)
            continue
        if current and label not in {"Total population", "One race"}:
            current["children"].append(slim_row(row))
    order = RACE_HEADS + ["Two or More Races"]
    groups.sort(key=lambda group: order.index(group["label"]) if group["label"] in order else len(order))
    return groups


def build_views(demo_blocks):
    overview = next(block["rows"] for block in demo_blocks if block["title"] == "Overview")
    by_label = {}
    for row in overview:
        by_label.setdefault(row["label"], row)
    age_labels = [
        "Under 5 years",
        "5 to 9 years",
        "10 to 14 years",
        "15 to 19 years",
        "20 to 24 years",
        "25 to 34 years",
        "35 to 44 years",
        "45 to 54 years",
        "55 to 59 years",
        "60 to 64 years",
        "65 to 74 years",
        "75 to 84 years",
        "85 years and over",
    ]
    hispanic_rows = next(block["rows"] for block in demo_blocks if "HISPANIC" in block["title"])
    origin = []
    not_hispanic = []
    mode = "origin"
    for row in hispanic_rows:
        if row["label"] == "Total population":
            continue
        if row["label"] == "Not Hispanic or Latino":
            mode = "race"
            not_hispanic.append(slim_row(row))
            continue
        if mode == "origin":
            origin.append(slim_row(row))
        else:
            not_hispanic.append(slim_row(row))

    def grab(label):
        row = by_label.get(label) or {}
        return slim_row(row) if row else {"label": label, "estimate": None, "percent": ""}

    return {
        "population": grab("Total population"),
        "median_age": grab("Median age (years)"),
        "sex": [grab("Male"), grab("Female")],
        "under_18": grab("Under 18 years"),
        "over_65": grab("65 years and over"),
        "age": [grab(label) for label in age_labels],
        "race": race_groups(demo_blocks),
        "hispanic_origin": origin,
        "hispanic_race": not_hispanic,
    }


def main():
    county_geo = load_county()
    cache = {}
    if GEOCODE_CACHE.exists():
        cache = json.loads(GEOCODE_CACHE.read_text(encoding="utf-8"))
    wb = openpyxl.load_workbook(WORKBOOK, data_only=True)
    demographics = parse_demographics(wb["Yolo Demographics"])
    unions = parse_unions(wb["Union Inventory"])
    employers = parse_employers(wb["Major Employers"], cache, county_geo)
    unions["markers"] = union_markers(unions["rows"], cache, county_geo)
    GEOCODE_CACHE.write_text(json.dumps(cache, indent=2), encoding="utf-8")
    profile = {
        "title": "Yolo County",
        "workbook": WORKBOOK.name,
        "union_compiled": "August 31, 2026",
        "views": build_views(demographics),
        "income": parse_income(wb["Family and Household Income"]),
        "earnings": parse_earnings(wb["Individual Earnings"]),
        "occupations": parse_occupations(wb["Occupations"]),
        "poverty": parse_poverty(wb["Yolo Poverty Stats"]),
        "employers": employers,
        "unions": unions,
    }
    OUT_PROFILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_PROFILE.write_text(json.dumps(profile, indent=2), encoding="utf-8")
    print(f"wrote {OUT_PROFILE}")
    missing_emp = [item["name"] for item in employers if item["lat"] is None]
    missing_unions = [item["name"] for item in unions["markers"] if item["lat"] is None]
    print("employers", len(employers), "unmatched", missing_emp)
    print("union pins", len(unions["markers"]), "unmatched", missing_unions)
    print("occ", [(group["label"], len(group["children"])) for group in profile["occupations"]["groups"]])


if __name__ == "__main__":
    main()
