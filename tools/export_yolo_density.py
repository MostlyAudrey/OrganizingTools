#!/usr/bin/env python3
"""Build a Yolo County census-tract population density layer for the profile map.

Population is POP100 from the SACOG ACS 5-year 2024 regional tract file. Those
tract counts add up to the county total shown on the profile. Land area is
Census TIGER/Line AREALAND for the ACS 2024 tract vintage.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "data" / "yolo-density.geojson"
USER_AGENT = "yolo-profile-export/1.0 (local civic research)"
SQ_METERS_PER_SQ_MILE = 2_589_988.110336

POPULATION_URL = (
    "https://services.sacog.org/hosting/rest/services/Census/"
    "Tracts_SACOG_Region_ACS_5yr_2024/FeatureServer/31/query"
)
LAND_URL = (
    "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/"
    "Tracts_Blocks/MapServer/7/query"
)


def fetch_json(url: str, params: dict) -> dict:
    request = urllib.request.Request(
        f"{url}?{urllib.parse.urlencode(params)}",
        headers={"User-Agent": USER_AGENT},
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.loads(response.read().decode())


def main() -> None:
    population = fetch_json(
        POPULATION_URL,
        {
            "where": "COUNTY=113",
            "outFields": "NAME,NAMELSAD,TRACT,POP100,GEOCODE",
            "returnGeometry": "true",
            "outSR": "4326",
            "geometryPrecision": "5",
            "f": "geojson",
        },
    )
    land = fetch_json(
        LAND_URL,
        {
            "where": "STATE='06' AND COUNTY='113'",
            "outFields": "GEOID,AREALAND",
            "returnGeometry": "false",
            "f": "json",
        },
    )
    area_by_geoid = {
        feature["attributes"]["GEOID"]: int(feature["attributes"]["AREALAND"])
        for feature in land.get("features") or []
    }
    if not population.get("features"):
        raise SystemExit("Population query returned no features: " + json.dumps(population)[:800])
    features = []
    missing = []
    for feature in population.get("features") or []:
        props = feature["properties"]
        geoid = str(props["GEOCODE"])
        aland = area_by_geoid.get(geoid)
        if aland is None:
            missing.append(geoid)
            continue
        people = int(props["POP100"] or 0)
        sq_mi = aland / SQ_METERS_PER_SQ_MILE
        features.append(
            {
                "type": "Feature",
                "properties": {
                    "geoid": geoid,
                    "name": props["NAMELSAD"] or props["NAME"],
                    "population": people,
                    "land_sq_mi": round(sq_mi, 2),
                    "density": round(people / sq_mi, 1) if sq_mi else None,
                },
                "geometry": feature["geometry"],
            }
        )
    if missing:
        raise SystemExit(f"No land area for {len(missing)} tracts: {', '.join(missing)}")
    if not features:
        raise SystemExit("No Yolo tracts returned")
    features.sort(key=lambda item: item["properties"]["geoid"])
    collection = {
        "type": "FeatureCollection",
        "population_source": "SACOG ACS 5-year 2024 regional tract file (POP100). Tract counts add up to the county population on this profile.",
        "area_source": "U.S. Census Bureau TIGER/Line land area, ACS 2024 tract vintage",
        "features": features,
    }
    OUT.write_text(json.dumps(collection, separators=(",", ":")), encoding="utf-8")
    total = sum(item["properties"]["population"] for item in features)
    densities = [item["properties"]["density"] for item in features]
    print(f"Wrote {len(features)} tracts, population {total:,}, density {min(densities)} to {max(densities)}")
    print(f"{OUT} ({OUT.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
