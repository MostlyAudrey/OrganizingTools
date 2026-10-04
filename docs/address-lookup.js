const ESRI_GEOCODE =
  "https://geocode.arcgis.com/arcgis/rest/services/World/GeocodeServer/findAddressCandidates";
const TIGER =
  "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/tigerWMS_Current/MapServer";

const LAYERS = {
  unified: 14,
  secondary: 16,
  elementary: 18,
  place: 28,
  congress: 54,
  senate: 56,
  assembly: 58,
  county: 82,
};

const ROOFTOP_TYPES = new Set(["PointAddress", "Subaddress", "StreetAddress"]);

function basename(attrs) {
  return String(attrs?.BASENAME || attrs?.NAME || "").trim();
}

function districtNumber(attrs) {
  const raw = basename(attrs);
  if (!raw) return "";
  if (/^\d+$/.test(raw)) return String(parseInt(raw, 10));
  const match = raw.match(/(\d+)/);
  return match ? String(parseInt(match[1], 10)) : "";
}

function hasWord(text, word) {
  if (!word) return false;
  const escaped = word.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return new RegExp(`\\b${escaped}\\b`, "i").test(text || "");
}

function schoolMatch(title, names) {
  const hay = (title || "").toLowerCase();
  for (const name of names || []) {
    const base = name.toLowerCase().trim();
    if (base && hay.includes(base)) return true;
    const short = base.replace(/\s+school district$/, "").trim();
    if (short && hay.includes(short)) return true;
  }
  return false;
}

function addressNotes(located) {
  const districts = [];
  if (located.usHouse) districts.push(`Congressional District ${located.usHouse}`);
  if (located.stateSenate) districts.push(`State Senate District ${located.stateSenate}`);
  if (located.stateAssembly) districts.push(`Assembly District ${located.stateAssembly}`);
  const districtText = districts.length ? districts.join(", ") : "no legislative district returned";
  const schools = located.schoolDistricts.length ? located.schoolDistricts.join("; ") : "none identified";
  const where = located.city
    ? `${located.city}, ${located.county} County`
    : `unincorporated ${located.county} County`;
  const notes = [
    `Address matched to ${located.matchedAddress} in ${where}. Districts from U.S. Census TIGERweb: ${districtText}. School district: ${schools}.`,
    "County supervisor districts, city council districts, and school-board trustee areas are not in that lookup, so those contests are listed for the whole county, city, or school district. Special-district contests are listed only when the district name includes this city. Confirm the ballot against the county sample ballot.",
  ];
  if (!located.city) {
    notes.push("This address is outside an incorporated city, so city council contests are omitted.");
  }
  return notes;
}

async function queryLayer(layerId, lng, lat) {
  const params = new URLSearchParams({
    geometry: `${lng},${lat}`,
    geometryType: "esriGeometryPoint",
    inSR: "4326",
    spatialRel: "esriSpatialRelIntersects",
    outFields: "NAME,BASENAME",
    returnGeometry: "false",
    f: "json",
  });
  const res = await fetch(`${TIGER}/${layerId}/query?${params}`);
  if (!res.ok) throw new Error(`Census map request failed (${res.status}).`);
  const data = await res.json();
  if (data.error) throw new Error(data.error.message || "Census map request failed.");
  const feature = (data.features || [])[0];
  return feature?.attributes || {};
}

export async function lookupAddress(query) {
  const text = String(query || "").trim();
  if (!text) throw new Error("Enter a street address.");
  const params = new URLSearchParams({
    SingleLine: text,
    f: "json",
    outFields: "Addr_type,City,Region,Subregion,StAddr,Postal",
    maxLocations: "1",
    sourceCountry: "USA",
  });
  const geoRes = await fetch(`${ESRI_GEOCODE}?${params}`);
  if (!geoRes.ok) throw new Error(`Address lookup failed (${geoRes.status}).`);
  const geo = await geoRes.json();
  const hit = (geo.candidates || [])[0];
  if (!hit) {
    throw new Error("No match for that address. Include the house number, street, city, and state.");
  }
  const attrs = hit.attributes || {};
  if (attrs.Region !== "California" && attrs.Region !== "CA") {
    throw new Error("That address is outside California.");
  }
  if (!ROOFTOP_TYPES.has(attrs.Addr_type) || Number(hit.score || 0) < 90) {
    throw new Error(
      "That did not match a specific street address. Include the house number, street, city, and state."
    );
  }
  const lng = hit.location?.x;
  const lat = hit.location?.y;
  if (typeof lng !== "number" || typeof lat !== "number") {
    throw new Error("The geocoder did not return a point for that address.");
  }

  const entries = await Promise.all(
    Object.entries(LAYERS).map(async ([key, layerId]) => [key, await queryLayer(layerId, lng, lat)])
  );
  const found = Object.fromEntries(entries);
  const county = basename(found.county);
  if (!county) throw new Error("That address is not inside a California county this guide covers.");
  const schoolDistricts = [];
  for (const key of ["unified", "secondary", "elementary"]) {
    const name = basename(found[key]);
    if (name && !schoolDistricts.includes(name)) schoolDistricts.push(name);
  }
  const located = {
    query: text,
    matchedAddress: hit.address || text,
    county,
    city: basename(found.place),
    lat,
    lng,
    usHouse: districtNumber(found.congress),
    stateSenate: districtNumber(found.senate),
    stateAssembly: districtNumber(found.assembly),
    schoolDistricts,
  };
  located.notes = addressNotes(located);
  return located;
}

export function addressKeepsItem({ title, level, city, located, inferCity }) {
  const levelL = (level || "").toLowerCase();
  if (levelL.includes("school")) return schoolMatch(title, located.schoolDistricts);
  if (levelL.includes("special")) return Boolean(located.city) && hasWord(title, located.city);
  if (levelL.includes("municipal")) {
    if (!located.city) return false;
    if (city) return city.toLowerCase() === located.city.toLowerCase();
    return hasWord(title, located.city);
  }
  if (levelL === "county" || levelL.startsWith("county")) {
    if (city && located.city && city.toLowerCase() !== located.city.toLowerCase()) return false;
    return true;
  }
  const otherCity = inferCity ? inferCity(title, located.county) : "";
  if (otherCity && located.city && otherCity.toLowerCase() !== located.city.toLowerCase()) return false;
  if (located.city && hasWord(title, located.city)) return true;
  if (schoolMatch(title, located.schoolDistricts)) return true;
  if (hasWord(title, located.county)) return true;
  return !otherCity;
}
