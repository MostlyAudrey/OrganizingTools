const LEVEL_ORDER = [
  "Federal",
  "State",
  "Judicial (Retention)",
  "County",
  "Municipal / City",
  "School Districts",
  "Special Districts",
  "Statewide Ballot Measures (Propositions)",
  "Local Ballot Measures",
];

const state = {
  meta: null,
  geography: null,
  places: [],
  snapshot: null,
  lastHtml: "",
};

const $ = (id) => document.getElementById(id);

function esc(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function pBlocks(text) {
  const raw = String(text ?? "").trim();
  if (!raw) {
    return "<p><em>Not available from official sources at time of compilation.</em></p>";
  }
  return raw
    .split(/\n\s*\n/)
    .map((part) => part.replace(/\s*\n\s*/g, " ").trim())
    .filter(Boolean)
    .map((part) => `<p>${esc(part)}</p>`)
    .join("\n");
}

function normalizePlace(name) {
  return String(name)
    .trim()
    .replace(/\s*\((city|county)\)\s*$/i, "")
    .replace(/\s+County$/i, "")
    .replace(/\s+City$/i, "")
    .replace(/^City of\s+/i, "")
    .trim();
}

function parsePlaceKind(raw) {
  const text = String(raw ?? "").trim();
  const m = text.match(/\((city|county)\)\s*$/i);
  const kind = m ? m[1].toLowerCase() : null;
  const name = normalizePlace(text);
  return { name, kind };
}

function geoLookups() {
  const cityMap = Object.fromEntries(
    Object.entries(state.geography.city_to_county || {}).map(([k, v]) => [k.toLowerCase(), v])
  );
  const cityCanonical = Object.fromEntries(
    Object.keys(state.geography.city_to_county || {}).map((k) => [k.toLowerCase(), k])
  );
  const countyLookup = Object.fromEntries(
    (state.geography.counties || []).map((c) => [c.toLowerCase(), c])
  );
  return { cityMap, cityCanonical, countyLookup };
}

function isAmbiguousName(name) {
  const { cityMap, countyLookup } = geoLookups();
  const key = name.toLowerCase();
  return Boolean(countyLookup[key] && cityMap[key]);
}

function placeId(place) {
  return `${place.kind}:${place.name.toLowerCase()}`;
}

function resolvePlaces(places) {
  const { cityMap, cityCanonical, countyLookup } = geoLookups();
  const display = [];
  const selectedCounties = [];
  const selectedCities = [];
  const unresolved = [];

  for (const item of places) {
    const raw = typeof item === "string" ? item : item.label || `${item.name} (${item.kind})`;
    const parsed = typeof item === "string" ? parsePlaceKind(item) : { name: item.name, kind: item.kind };
    const place = parsed.name;
    if (!place) continue;
    const key = place.toLowerCase();
    const isCounty = Boolean(countyLookup[key]);
    const isCity = Boolean(cityMap[key]);
    let kind = parsed.kind;

    if (kind === "county") {
      if (isCounty) {
        selectedCounties.push(countyLookup[key]);
        display.push(`${countyLookup[key]} (county)`);
      } else unresolved.push(raw);
      continue;
    }
    if (kind === "city") {
      if (isCity) {
        selectedCities.push(cityCanonical[key]);
        display.push(`${cityCanonical[key]} (city)`);
      } else unresolved.push(raw);
      continue;
    }
    if (isCounty && isCity) {
      unresolved.push(`${place} (ambiguous — specify city or county)`);
      continue;
    }
    if (isCounty) {
      selectedCounties.push(countyLookup[key]);
      display.push(`${countyLookup[key]} (county)`);
      continue;
    }
    if (isCity) {
      selectedCities.push(cityCanonical[key]);
      display.push(`${cityCanonical[key]} (city)`);
      continue;
    }
    unresolved.push(raw);
  }

  const uniq = (seq) => [...new Set(seq)];
  const counties = uniq([
    ...selectedCounties,
    ...selectedCities.map((c) => cityMap[c.toLowerCase()]).filter(Boolean),
  ]);
  return {
    display: uniq(display),
    counties,
    cities: uniq(selectedCities),
    selectedCounties: uniq(selectedCounties),
    selectedCities: uniq(selectedCities),
    unresolved,
  };
}

function inferCityFromText(text, county = "") {
  const raw = String(text || "");
  if (!raw) return "";
  let   m = raw.match(/City of\s+(.+?)(?:\s+GENERAL|\s+Member|\s+Vote for|\s*,|\s+-|\s*$)/i);
    if (m) {
    let name = normalizePlace(m[1]).replace(/[—–-]+$/g, "").trim();
    if (name === name.toUpperCase()) {
      name = name.replace(/\w\S*/g, (w) => w[0] + w.slice(1).toLowerCase());
    }
    return name;
  }
  const cityMap = state.geography.city_to_county || {};
  const names = Object.keys(cityMap).sort((a, b) => b.length - a.length);
  const countyKey = String(county || "").toLowerCase();
  for (const city of names) {
    if (county && cityMap[city] !== county) continue;
    if (city.toLowerCase() === countyKey) continue;
    const re = new RegExp(`\\b${city.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\b`, "i");
    if (re.test(raw)) return city;
  }
  return "";
}

function localItemMatches(item, { selectedCounties, selectedCities, county }) {
  const title = item.name || item.title || "";
  const level = item.level || "";
  let city = item.city || inferCityFromText(`${title} ${item.jurisdiction || ""}`, county);
  if (selectedCounties.includes(county)) return true;
  if (!selectedCities.length) return selectedCounties.length > 0;
  if (city && selectedCities.some((c) => c.toLowerCase() === city.toLowerCase())) return true;
  if (selectedCities.some((c) => new RegExp(`\\b${c.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\b`, "i").test(title))) {
    return true;
  }
  if (level === "County") {
    const cityMap = state.geography.city_to_county || {};
    return selectedCities.some((c) => cityMap[c] === county);
  }
  return false;
}

function districtsForCounties(counties) {
  const out = { us_house: [], state_senate: [], state_assembly: [], boe: [] };
  const countySet = new Set(counties);
  const crosswalk = state.geography.district_counties || {};
  for (const [office, districts] of Object.entries(crosswalk)) {
    if (!out[office]) out[office] = [];
    for (const [dist, distCounties] of Object.entries(districts)) {
      if (distCounties.some((c) => countySet.has(c))) out[office].push(String(dist));
    }
    out[office].sort((a, b) => Number(a) - Number(b));
  }
  return out;
}

function appellateDistrictsForCounties(counties) {
  const result = [];
  for (const [dist, list] of Object.entries(state.geography.appellate_districts || {})) {
    if (counties.some((c) => list.includes(c)) && !result.includes(dist)) result.push(dist);
  }
  return result;
}

function formatDateLabel(iso) {
  const [y, m, d] = iso.split("-").map(Number);
  const dt = new Date(Date.UTC(y, m - 1, d));
  return dt.toLocaleDateString("en-US", {
    month: "long",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
  });
}

function nextElectionIso(asOfIso) {
  const asOf = asOfIso || new Date().toISOString().slice(0, 10);
  const all = [...(state.meta.elections || [])].sort((a, b) => a.date.localeCompare(b.date));
  const upcoming = all.filter((e) => e.date >= asOf);
  const pool = upcoming.length ? upcoming : [...all].reverse();
  // Prefer statewide contests when several share/nearby dates
  const statewide = pool.find((e) => e.scope === "statewide");
  return (statewide || pool[0])?.date || null;
}

function candidateHeading(c) {
  return c.incumbent ? `${c.name} (Incumbent)` : c.name;
}

function candidateDetails(c) {
  const bits = [];
  if (c.party) bits.push(c.party);
  if (c.designation) bits.push(`Ballot designation: ${c.designation}`);
  if (c.notes) bits.push(c.notes);
  return bits.join(" — ") || "No additional details available.";
}

function renderRace(race) {
  const parts = [`<h2>${esc(race.name)}</h2>`];
  if (race.description) parts.push(`<p>${esc(race.description)}</p>`);
  if (race.vote_for) parts.push(`<p>${esc(race.vote_for)}</p>`);
  if (!race.candidates?.length) {
    parts.push("<p>No candidates listed in available official sources.</p>");
  }
  for (const c of race.candidates || []) {
    parts.push(`<h3>${esc(candidateHeading(c))}</h3>`);
    parts.push(`<p>${esc(candidateDetails(c))}</p>`);
  }
  return parts.join("\n");
}

function renderMeasure(m) {
  const parts = [`<h2>${esc(m.title)}</h2>`];
  if (m.jurisdiction) parts.push(`<p>Jurisdiction: ${esc(m.jurisdiction)}</p>`);
  if (m.threshold) parts.push(`<p>Passage threshold: ${esc(m.threshold)}</p>`);
  if (m.ballot_question) {
    parts.push("<h3>Ballot Question</h3>", pBlocks(m.ballot_question));
  }
  if (m.summary) {
    parts.push("<h3>Official Summary</h3>", pBlocks(m.summary));
  }
  parts.push("<h3>What a Yes Vote Means</h3>", pBlocks(m.yes_means));
  parts.push("<h3>What a No Vote Means</h3>", pBlocks(m.no_means));
  if (m.analysis) {
    parts.push("<h3>Impartial Analysis</h3>", pBlocks(m.analysis));
  }
  parts.push("<h3>Argument in Favor</h3>", pBlocks(m.arg_for));
  if ((m.reb_for || "").trim()) {
    parts.push("<h3>Rebuttal to Argument in Favor</h3>", pBlocks(m.reb_for));
  }
  parts.push("<h3>Argument Against</h3>", pBlocks(m.arg_against));
  if ((m.reb_against || "").trim()) {
    parts.push("<h3>Rebuttal to Argument Against</h3>", pBlocks(m.reb_against));
  }
  if (m.tax_rate_statement) {
    parts.push("<h3>Tax Rate Statement</h3>", pBlocks(m.tax_rate_statement));
  }
  parts.push("<h3>Full Text</h3>", pBlocks(m.full_text));
  if (m.source_url) parts.push(`<p>Source: ${esc(m.source_url)}</p>`);
  return parts.join("\n");
}

function buildReportHtml({
  places,
  counties,
  cities,
  selectedCounties,
  selectedCities,
  unresolved,
  election,
  snapshot,
  includeLocal,
}) {
  const notes = [];
  const sources = [];
  const races = [];
  const measures = [];

  if (unresolved.length) {
    notes.push(`Could not map these places to a county: ${unresolved.join(", ")}`);
  }
  notes.push(`Using election ${formatDateLabel(election.date)} (${election.name}).`);
  if (election.notes) notes.push(election.notes);
  if (!snapshot) {
    notes.push(
      "No data snapshot is published for this election yet. Run tools/export_ballot_web_data.py and redeploy."
    );
  }

  if (snapshot) {
    races.push(...(snapshot.statewide_races || []));
    races.push(...(snapshot.spi_races || []));
    const dist = districtsForCounties(counties);
    for (const n of dist.us_house) {
      if (snapshot.us_house?.[n]) races.push(snapshot.us_house[n]);
    }
    for (const n of dist.state_senate) {
      if (snapshot.state_senate?.[n]) races.push(snapshot.state_senate[n]);
    }
    for (const n of dist.state_assembly) {
      if (snapshot.state_assembly?.[n]) races.push(snapshot.state_assembly[n]);
    }
    for (const n of dist.boe) {
      if (snapshot.boe?.[n]) races.push(snapshot.boe[n]);
    }

    races.push(...(snapshot.retention?.supreme || []));
    for (const d of appellateDistrictsForCounties(counties)) {
      const coa = snapshot.retention?.coa_by_district?.[d];
      if (coa) races.push(coa);
    }

    measures.push(...(snapshot.measures || []));
    if (snapshot.cert_list_url) sources.push(snapshot.cert_list_url);
    if (snapshot.vig_base_url) sources.push(snapshot.vig_base_url);
    sources.push("California Secretary of State Official Voter Information Guide / certified lists");

    if (includeLocal) {
      for (const county of counties) {
        const local = snapshot.local_by_county?.[county];
        if (!local) {
          notes.push(
            `No local race/measure snapshot for ${county} County in this published dataset.`
          );
          continue;
        }
        const localRaces = (local.races || []).filter((r) =>
          localItemMatches(
            { ...r, county: r.county || county },
            { selectedCounties, selectedCities, county }
          )
        );
        const localMeasures = (local.measures || []).filter((m) =>
          localItemMatches(
            { ...m, name: `${m.title || ""} ${m.jurisdiction || ""}`, county },
            { selectedCounties, selectedCities, county }
          )
        );
        races.push(...localRaces);
        measures.push(...localMeasures);
        notes.push(...(local.notes || []));
      }
      if (selectedCities.length && !selectedCounties.length) {
        notes.push(
          "City selection includes overlapping county contests plus municipal races for the selected city."
        );
      }
      if (selectedCounties.length) {
        notes.push(
          "County selection includes countywide contests and all overlapping city races in the snapshot."
        );
      }
    } else {
      notes.push("Local races and measures were excluded by your settings.");
    }

    notes.push(
      "District contests are filtered from published district-county coverage data; confirm on your county sample ballot after redistricting."
    );
  }

  // Dedupe races
  const seen = new Set();
  const dedupedRaces = [];
  for (const race of races) {
    const key = `${race.level}::${(race.name || "").toLowerCase()}`;
    if (seen.has(key)) continue;
    seen.add(key);
    dedupedRaces.push(race);
  }

  const byLevel = {};
  for (const race of dedupedRaces) {
    (byLevel[race.level] ||= []).push(race);
  }
  const measuresByLevel = {};
  for (const m of measures) {
    (measuresByLevel[m.level] ||= []).push(m);
  }

  const title = `${places.join(", ")} — ${election.name} Ballot Guide (${formatDateLabel(election.date)})`;
  const sections = [
    `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>${esc(title)}</title>
<style>
  body { font-family: Georgia, 'Times New Roman', serif; max-width: 900px; margin: 2rem auto; padding: 0 1rem; line-height: 1.45; color: #111; }
  h1 { border-bottom: 2px solid #222; padding-bottom: .3rem; margin-top: 2.5rem; }
  h2 { margin-top: 1.8rem; color: #222; }
  h3 { margin-top: 1.1rem; color: #333; }
  p { margin: .55rem 0; }
  .note { background: #f5f5f5; padding: 1rem; border-left: 4px solid #666; margin: 1rem 0; }
</style>
</head>
<body>`,
    `<h1>${esc(title)}</h1>`,
    `<p>Places: ${esc(places.join(", "))}. Counties: ${esc(counties.join(", ") || "(none)")}. Cities: ${esc((cities || []).join(", ") || "(none)")}. Election: ${esc(formatDateLabel(election.date))}.</p>`,
    `<div class="note"><p>How to import: In Google Docs use File → Open → Upload this .html file. In Microsoft Word use File → Open and select this HTML file.</p></div>`,
  ];

  if (notes.length) {
    sections.push("<h1>Notes</h1>");
    for (const note of notes) sections.push(`<p>${esc(note)}</p>`);
  }

  for (const level of LEVEL_ORDER) {
    if (byLevel[level]?.length) {
      sections.push(`<h1>${esc(level)}</h1>`);
      for (const race of byLevel[level]) sections.push(renderRace(race));
    }
    if (measuresByLevel[level]?.length) {
      sections.push(`<h1>${esc(level)}</h1>`);
      for (const m of measuresByLevel[level]) sections.push(renderMeasure(m));
    }
  }

  sections.push("<h1>Sources</h1>");
  for (const src of sources) sections.push(`<p>${esc(src)}</p>`);
  sections.push(
    "<p>Compiled as a research aid. Confirm final ballot content with your county sample ballot or Official Voter Information Guide.</p>"
  );
  sections.push("</body></html>");
  return sections.join("\n");
}

function setStatus(msg, tone = "") {
  const el = $("status");
  el.textContent = msg;
  el.dataset.tone = tone;
}

function renderChips() {
  const wrap = $("place-chips");
  wrap.innerHTML = "";
  for (const place of state.places) {
    const label = place.label || `${place.name} (${place.kind})`;
    const chip = document.createElement("span");
    chip.className = "chip";
    chip.innerHTML = `<span>${esc(label)}</span>`;
    const btn = document.createElement("button");
    btn.type = "button";
    btn.setAttribute("aria-label", `Remove ${label}`);
    btn.textContent = "×";
    btn.addEventListener("click", () => {
      state.places = state.places.filter((p) => placeId(p) !== placeId(place));
      renderChips();
      updateResolved();
    });
    chip.appendChild(btn);
    wrap.appendChild(chip);
  }
  updateResolved();
}

function updateResolved() {
  if (!state.geography) return;
  const { counties, cities, unresolved } = resolvePlaces(state.places);
  const bits = [];
  if (counties.length) bits.push(`Counties: ${counties.join(", ")}`);
  if (cities.length) bits.push(`Cities: ${cities.join(", ")}`);
  if (unresolved.length) bits.push(`Unresolved: ${unresolved.join(", ")}`);
  $("resolved-places").textContent = bits.join(" · ");
}

function fillSuggestions() {
  const list = $("place-suggestions");
  const counties = (state.geography.counties || []).map((c) => `${c} (county)`);
  const cities = Object.keys(state.geography.city_to_county || {}).map((c) => `${c} (city)`);
  const values = [...counties, ...cities].sort((a, b) => a.localeCompare(b));
  list.innerHTML = values.map((v) => `<option value="${esc(v)}"></option>`).join("");
}

function fillElections() {
  const select = $("election-select");
  const next = nextElectionIso(state.meta.default_as_of);
  select.innerHTML = (state.meta.elections || [])
    .map((e) => {
      const mark = e.date === next ? " (next)" : "";
      const avail = e.has_snapshot ? "" : " — snapshot not published";
      return `<option value="${esc(e.date)}" ${e.date === next ? "selected" : ""}>${esc(
        formatDateLabel(e.date)
      )} — ${esc(e.name)}${mark}${avail}</option>`;
    })
    .join("");
  updateElectionHint();
}

function updateElectionHint() {
  const iso = $("election-select").value;
  const ev = (state.meta.elections || []).find((e) => e.date === iso);
  if (!ev) {
    $("election-hint").textContent = "";
    return;
  }
  $("election-hint").textContent = ev.has_snapshot
    ? ev.notes || "Snapshot available."
    : "No published snapshot for this date yet. Statewide/local details may be incomplete until data is exported.";
}

async function loadSnapshot(iso) {
  const ev = (state.meta.elections || []).find((e) => e.date === iso);
  if (!ev?.snapshot) {
    state.snapshot = null;
    return null;
  }
  const res = await fetch(`data/${ev.snapshot}`);
  if (!res.ok) throw new Error(`Could not load snapshot ${ev.snapshot}`);
  state.snapshot = await res.json();
  return state.snapshot;
}

function addPlace() {
  const input = $("place-input");
  const { name, kind } = parsePlaceKind(input.value);
  if (!name) return;
  const { cityMap, cityCanonical, countyLookup } = geoLookups();
  const key = name.toLowerCase();
  let resolvedKind = kind;
  if (!resolvedKind) {
    if (isAmbiguousName(name)) {
      setStatus(`“${name}” is both a city and a county. Choose “${name} (city)” or “${name} (county)”.`, "error");
      return;
    }
    if (countyLookup[key]) resolvedKind = "county";
    else if (cityMap[key]) resolvedKind = "city";
  }
  if (resolvedKind === "county" && !countyLookup[key]) {
    setStatus(`Unknown county: ${name}`, "error");
    return;
  }
  if (resolvedKind === "city" && !cityMap[key]) {
    setStatus(`Unknown city: ${name}`, "error");
    return;
  }
  if (!resolvedKind) {
    setStatus(`Could not map “${name}” to a California city or county.`, "error");
    return;
  }
  const place = {
    name: resolvedKind === "county" ? countyLookup[key] : cityCanonical[key],
    kind: resolvedKind,
    label: `${resolvedKind === "county" ? countyLookup[key] : cityCanonical[key]} (${resolvedKind})`,
  };
  if (!state.places.some((p) => placeId(p) === placeId(place))) {
    state.places.push(place);
  }
  input.value = "";
  setStatus("");
  renderChips();
}

async function generate() {
  try {
    if (!state.places.length) {
      setStatus("Add at least one county or city.", "error");
      return;
    }
    const resolved = resolvePlaces(state.places);
    const { display, counties, unresolved, cities, selectedCounties, selectedCities } = resolved;
    if (!counties.length) {
      setStatus("Could not resolve any counties from the places you entered.", "error");
      return;
    }
    setStatus("Loading election data…");
    const iso = $("election-select").value;
    const election = (state.meta.elections || []).find((e) => e.date === iso);
    await loadSnapshot(iso);
    const html = buildReportHtml({
      places: display,
      counties,
      cities,
      selectedCounties,
      selectedCities,
      unresolved,
      election,
      snapshot: state.snapshot,
      includeLocal: $("include-local").checked,
    });
    state.lastHtml = html;
    const doc = $("preview").contentDocument;
    doc.open();
    doc.write(html);
    doc.close();
    $("download").disabled = false;
    $("copy").disabled = false;
    setStatus(`Generated guide for ${display.join(", ")} · ${formatDateLabel(iso)}.`, "ok");
  } catch (err) {
    console.error(err);
    setStatus(err.message || String(err), "error");
  }
}

function downloadHtml() {
  if (!state.lastHtml) return;
  const iso = $("election-select").value;
  const slug =
    state.places.map((p) => `${p.name}${p.kind === "city" ? "City" : "County"}`).join("_").replace(/\s+/g, "") ||
    "ballot";
  const blob = new Blob([state.lastHtml], { type: "text/html;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${slug}_${iso}_ballot_guide.html`;
  a.click();
  URL.revokeObjectURL(url);
}

async function copyHtml() {
  if (!state.lastHtml) return;
  await navigator.clipboard.writeText(state.lastHtml);
  setStatus("HTML copied to clipboard.", "ok");
}

async function init() {
  try {
    const [metaRes, geoRes] = await Promise.all([
      fetch("data/meta.json"),
      fetch("data/geography.json"),
    ]);
    if (!metaRes.ok || !geoRes.ok) {
      throw new Error(
        "Missing data files. Run: python tools/export_ballot_web_data.py --out docs/data"
      );
    }
    state.meta = await metaRes.json();
    state.geography = await geoRes.json();
    fillSuggestions();
    fillElections();
    $("election-select").addEventListener("change", updateElectionHint);
    $("add-place").addEventListener("click", addPlace);
    $("place-input").addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        addPlace();
      }
    });
    $("clear-places").addEventListener("click", () => {
      state.places = [];
      renderChips();
    });
    $("generate").addEventListener("click", generate);
    $("download").addEventListener("click", downloadHtml);
    $("copy").addEventListener("click", copyHtml);

    // Sensible demo default
    if (!state.places.length) {
      state.places = [{ name: "Yolo", kind: "county", label: "Yolo (county)" }];
      renderChips();
    }
    setStatus("Ready. Add places and generate a report.");
  } catch (err) {
    console.error(err);
    setStatus(err.message || String(err), "error");
  }
}

init();
