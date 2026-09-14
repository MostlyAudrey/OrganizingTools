from __future__ import annotations

import html as htmlmod
import re
import urllib.request
from html.parser import HTMLParser
from urllib.parse import urljoin

from ..geography import county_elections_url, normalize_place
from ..models import Candidate, Measure, Race

UA = {"User-Agent": "Mozilla/5.0 (compatible; BallotReportBot/1.0)"}


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=90) as resp:
        return resp.read().decode("utf-8", errors="ignore")


def html_to_text(h: str) -> str:
    t = re.sub(r"<script[\s\S]*?</script>", "", h, flags=re.I)
    t = re.sub(r"<style[\s\S]*?</style>", "", t, flags=re.I)
    t = re.sub(r"<br\s*/?>", "\n", t, flags=re.I)
    t = re.sub(r"</(p|h[1-6]|li|tr|div)>", "\n", t, flags=re.I)
    t = re.sub(r"<[^>]+>", " ", t)
    t = htmlmod.unescape(t)
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


class TableExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.blocks: list[tuple[str, list[list[str]]]] = []
        self._in_table = self._in_row = self._in_cell = self._in_heading = False
        self._curr_table: list[list[str]] = []
        self._curr_row: list[str] = []
        self._curr_cell: list[str] = []
        self._heading_buf: list[str] = []
        self._last_heading = ""

    def handle_starttag(self, tag, attrs):
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self._in_heading = True
            self._heading_buf = []
        if tag == "table":
            self._in_table = True
            self._curr_table = []
        elif tag == "tr" and self._in_table:
            self._in_row = True
            self._curr_row = []
        elif tag in {"td", "th"} and self._in_row:
            self._in_cell = True
            self._curr_cell = []
        elif tag == "br" and self._in_cell:
            self._curr_cell.append("\n")

    def handle_endtag(self, tag):
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"} and self._in_heading:
            self._in_heading = False
            text = htmlmod.unescape("".join(self._heading_buf)).strip()
            text = re.sub(r"\s+", " ", text)
            if text:
                self._last_heading = text
        if tag in {"td", "th"} and self._in_cell:
            self._in_cell = False
            cell = htmlmod.unescape("".join(self._curr_cell))
            cell = re.sub(r"[ \t]+", " ", cell)
            cell = re.sub(r"\n+", "\n", cell).strip()
            self._curr_row.append(cell)
        elif tag == "tr" and self._in_row:
            self._in_row = False
            if any(c.strip() for c in self._curr_row):
                self._curr_table.append(self._curr_row)
        elif tag == "table" and self._in_table:
            self._in_table = False
            self.blocks.append((self._last_heading, self._curr_table))

    def handle_data(self, data):
        if self._in_heading:
            self._heading_buf.append(data)
        if self._in_cell:
            self._curr_cell.append(data)


def _discover_civicplus_links(home_html: str, base_url: str) -> dict[str, str]:
    links = {}
    for href, text in re.findall(r'href="([^"]+)"[^>]*>([^<]{2,100})', home_html):
        label = re.sub(r"\s+", " ", htmlmod.unescape(text)).strip().lower()
        url = urljoin(base_url, href)
        if "federal" in label and "federal" not in links:
            links["federal"] = url
        elif label == "state" or label.startswith("state "):
            links.setdefault("state", url)
        elif "county" == label or label.startswith("county "):
            links.setdefault("county", url)
        elif "school" in label:
            links.setdefault("school", url)
        elif "municipal" in label or label == "city" or "city" in label:
            links.setdefault("municipal", url)
        elif "special district" in label:
            links.setdefault("special", url)
        elif "local measure" in label or label == "measures":
            links.setdefault("measures", url)
        elif "current election" in label:
            links.setdefault("current", url)
    # Numeric path fallbacks commonly used by CivicPlus elections sites
    for path, key in [
        ("/392/Federal", "federal"),
        ("/393/State", "state"),
        ("/395/County", "county"),
        ("/397/School-Districts", "school"),
        ("/423/Municipal-City", "municipal"),
        ("/424/Special-Districts", "special"),
        ("/407/Local-Measures", "measures"),
    ]:
        links.setdefault(key, urljoin(base_url, path))
    return links


def _candidates_from_table(rows: list[list[str]]) -> list[Candidate]:
    cands: list[Candidate] = []
    if not rows:
        return cands
    # Skip header-ish first row
    start = 1 if rows and re.search(r"candidate|party|affiliation", rows[0][0], re.I) else 0
    for row in rows[start:]:
        if not row or not row[0].strip():
            continue
        raw = row[0]
        if re.search(r"^candidate$|vote for|misc\.?", raw, re.I):
            continue
        parts = [p.strip() for p in re.split(r"\n+", raw) if p.strip()]
        if not parts:
            continue
        name = parts[0]
        if name.lower() in {"vacant"} or "did not file" in raw.lower() and len(parts) == 1:
            continue
        designation = parts[1] if len(parts) > 1 else ""
        party = ""
        for cell in row[1:]:
            if re.search(r"\bDEM\b|\bDemocratic\b", cell, re.I):
                party = "Democratic Party"
            elif re.search(r"\bREP\b|\bRepublican\b", cell, re.I):
                party = "Republican Party"
            elif re.search(r"\bNPP\b|No Party Preference", cell, re.I):
                party = "No Party Preference"
            elif re.search(r"Nonpartisan|Non-Partisan", cell, re.I):
                party = "Nonpartisan"
        incumbent = bool(re.search(r"\(I\)|Incumbent", raw, re.I))
        name = re.sub(r"\s*\((?:I|A/I|W/I)\)\s*", " ", name).strip()
        name = re.sub(r"\s+", " ", name)
        if "did not file" in raw.lower() and designation.lower() in {"", "did not file"}:
            continue
        if designation.lower() == "did not file":
            continue
        cands.append(
            Candidate(
                name=name,
                party=party or ("Nonpartisan" if not party else party),
                designation=designation,
                incumbent=incumbent,
            )
        )
    # Filter withdrawn
    cands = [c for c in cands if "withdrawn" not in c.designation.lower()]
    return cands


def _guess_level(heading: str, path_key: str) -> str:
    h = heading.lower()
    if path_key == "federal" or "congress" in h or "representative" in h:
        return "Federal"
    if path_key == "state" or "governor" in h or "assembly" in h or "senate" in h or "equalization" in h:
        return "State"
    if "supervisor" in h or path_key == "county":
        return "County"
    if "school" in h or "trustee" in h or "board of education" in h:
        return "School Districts"
    if "council" in h or "mayor" in h or path_key == "municipal":
        return "Municipal / City"
    if path_key == "special" or "district" in h:
        return "Special Districts"
    return "County"


def scrape_civicplus_county(county: str, base_url: str | None = None) -> tuple[list[Race], list[Measure], list[str]]:
    """
    Best-effort scrape of CivicPlus-style county elections sites (e.g. Yolo).
    Returns races, measures, notes.
    """
    notes: list[str] = []
    base_url = base_url or county_elections_url(county)
    if not base_url:
        return [], [], [f"No known elections website URL for {county} County."]

    try:
        home = fetch(base_url)
    except Exception as exc:
        return [], [], [f"Could not fetch {base_url}: {exc}"]

    links = _discover_civicplus_links(home, base_url)
    races: list[Race] = []

    for key in ["federal", "state", "county", "municipal", "school", "special"]:
        url = links.get(key)
        if not url:
            continue
        try:
            page = fetch(url)
        except Exception as exc:
            notes.append(f"Could not fetch {key} page ({url}): {exc}")
            continue
        parser = TableExtractor()
        try:
            parser.feed(page)
        except Exception:
            continue
        # Use nearby headings from plain text for race titles when table heading is generic
        text = html_to_text(page)
        # Split text into race blocks by "Vote for"
        headings = re.findall(
            r"((?:U\.S\.|United States|Governor|Lieutenant|Secretary|Controller|Treasurer|Attorney|Insurance|Member|Superintendent|County Supervisor|City of|.*?(?:Council|Trustee|Governing Board|Director|Commissioner)).*?)\n\s*Vote for",
            text,
            re.I,
        )
        table_cands = [_candidates_from_table(rows) for _, rows in parser.blocks]
        # Pair tables with headings when counts match-ish
        if headings and table_cands and abs(len(headings) - len(table_cands)) <= 2:
            for i, cands in enumerate(table_cands):
                if not cands:
                    continue
                title = headings[i] if i < len(headings) else parser.blocks[i][0] or f"{key.title()} contest"
                title = re.sub(r"\s+", " ", title).strip()
                # Skip off-ballot noise if heading says OFF THE BALLOT and only one unopposed appointment style
                if re.search(r"OFF THE BALLOT", title, re.I):
                    continue
                races.append(
                    Race(
                        name=title,
                        level=_guess_level(title, key),
                        candidates=cands,
                        vote_for="See ballot",
                    )
                )
        else:
            for heading, rows in parser.blocks:
                cands = _candidates_from_table(rows)
                if not cands:
                    continue
                title = heading or f"{normalize_place(county)} {key} contest"
                if re.search(r"OFF THE BALLOT", title, re.I):
                    continue
                races.append(
                    Race(
                        name=title,
                        level=_guess_level(title, key),
                        candidates=cands,
                    )
                )

    measures: list[Measure] = []
    measures_url = links.get("measures")
    if measures_url:
        try:
            mhtml = fetch(measures_url)
            measures.extend(_parse_measure_index(mhtml, measures_url, county))
        except Exception as exc:
            notes.append(f"Could not fetch local measures ({measures_url}): {exc}")

    notes.append(
        f"Local races/measures for {county} scraped best-effort from {base_url}. "
        "Confirm against the county sample ballot."
    )
    return races, measures, notes


def _parse_measure_index(html: str, base_url: str, county: str) -> list[Measure]:
    text = html_to_text(html)
    measures: list[Measure] = []
    # Capture Measure X — title / question blocks
    for m in re.finditer(
        r"(Measure\s+[A-Z0-9]+)\s*[–—:-]?\s*([^\n]{0,120})\n([\s\S]{50,1200}??)(?=Measure\s+[A-Z0-9]+|About Us|Ballot Measure Argument|\Z)",
        text,
        re.I,
    ):
        code = m.group(1).strip()
        title_bit = m.group(2).strip()
        body = m.group(3).strip()
        q = ""
        qm = re.search(r"(Shall .+?\?|To .+?\?|With funds that cannot .+?\?)", body, re.S | re.I)
        if qm:
            q = re.sub(r"\s+", " ", qm.group(1)).strip()
        threshold = "Majority (50% + 1)"
        if re.search(r"55%", body):
            threshold = "55% yes required"
        # Try linked detail page
        detail = None
        for href, label in re.findall(r'href="([^"]+)"[^>]*>([^<]{0,120})', html):
            if code.replace(" ", "-").lower() in href.lower() or code.lower() in label.lower():
                detail = urljoin(base_url, href)
                break
        full = analysis = arg_for = arg_against = yes = no = ""
        if detail:
            try:
                dhtml = fetch(detail)
                dtext = html_to_text(dhtml)
                analysis = _between(dtext, ["Impartial Analysis", "County Counsel"], ["Full Text", "Argument In Favor", "Argument in Favor"])
                full = _between(dtext, ["Full Text", "ORDINANCE NO", "RESOLUTION NO", "FULL TEXT"], ["Argument In Favor", "Argument in Favor", "Tax Rate"])
                arg_for = _between(dtext, ["Argument In Favor", "Argument in Favor"], ["Argument Against", "Rebuttal"])
                arg_against = _between(dtext, ["Argument Against"], ["Rebuttal", "About Us"])
                ym = re.search(r'A ["“]?yes["”]? vote[^\n]*', analysis, re.I)
                nm = re.search(r'A ["“]?no["”]? vote[^\n]*', analysis, re.I)
                yes = ym.group(0).strip() if ym else ""
                no = nm.group(0).strip() if nm else ""
            except Exception:
                pass
        measures.append(
            Measure(
                title=f"{code} — {title_bit}" if title_bit else code,
                level="Local Ballot Measures",
                jurisdiction=f"{normalize_place(county)} County / local jurisdiction (see measure)",
                threshold=threshold,
                ballot_question=q,
                summary=body[:500],
                yes_means=yes or "A Yes vote approves the measure.",
                no_means=no or "A No vote rejects the measure.",
                analysis=analysis,
                arg_for=arg_for or "See county voter information guide.",
                arg_against=arg_against or "See county voter information guide / no argument filed.",
                full_text=full or q or "Full text available in the county voter information guide.",
                source_url=detail or base_url,
            )
        )
    return measures


def _between(text: str, starts: list[str], ends: list[str]) -> str:
    low = text.lower()
    start = -1
    used = ""
    for s in starts:
        i = low.find(s.lower())
        if i >= 0 and (start < 0 or i < start):
            start = i
            used = s
    if start < 0:
        return ""
    rest = text[start:]
    lowr = rest.lower()
    end = len(rest)
    for e in ends:
        j = lowr.find(e.lower(), max(len(used), 1))
        if j >= 0:
            end = min(end, j)
    return rest[:end].strip()


def load_local_for_counties(counties: list[str]) -> tuple[list[Race], list[Measure], list[str]]:
    all_races: list[Race] = []
    all_measures: list[Measure] = []
    notes: list[str] = []
    for county in counties:
        races, measures, n = scrape_civicplus_county(county)
        # Prefer county/municipal/school/special from scrape; statewide/federal/state often better from SOS
        local_levels = {"County", "Municipal / City", "School Districts", "Special Districts"}
        all_races.extend([r for r in races if r.level in local_levels])
        all_measures.extend(measures)
        notes.extend(n)
    return all_races, all_measures, notes
