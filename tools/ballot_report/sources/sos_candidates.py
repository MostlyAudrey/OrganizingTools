from __future__ import annotations

import re
import tempfile
import urllib.request
from pathlib import Path

from pypdf import PdfReader

from ..models import Candidate, Race

DEFAULT_CERT_LIST_URL = (
    "https://elections.cdn.sos.ca.gov/statewide-elections/2026-general/cert-list-candidates.pdf"
)

UA = {"User-Agent": "Mozilla/5.0 (compatible; BallotReportBot/1.0)"}

PARTY_MAP = {
    "Democratic": "Democratic Party",
    "Republican": "Republican Party",
    "No Party Preference": "No Party Preference",
    "Non-Partisan": "Nonpartisan",
    "Green": "Green Party",
    "Libertarian": "Libertarian Party",
    "American Independent": "American Independent Party",
    "Peace and Freedom": "Peace and Freedom Party",
}

PARTIES = (
    "Democratic|Republican|No Party Preference|Non-Partisan|Green|"
    "Libertarian|American Independent|Peace and Freedom"
)

OFFICE_PATTERNS: list[tuple[re.Pattern[str], str, str, str]] = [
    # (header regex, title template with optional {n}, bucket, level)
    (re.compile(r"^Governor\s*$", re.I), "Governor", "statewide", "State"),
    (re.compile(r"^Lieutenant Governor\s*$", re.I), "Lieutenant Governor", "statewide", "State"),
    (re.compile(r"^Secretary of State\s*$", re.I), "Secretary of State", "statewide", "State"),
    (re.compile(r"^Controller\s*$", re.I), "Controller", "statewide", "State"),
    (re.compile(r"^Treasurer\s*$", re.I), "Treasurer", "statewide", "State"),
    (re.compile(r"^Attorney General\s*$", re.I), "Attorney General", "statewide", "State"),
    (re.compile(r"^Insurance Commissioner\s*$", re.I), "Insurance Commissioner", "statewide", "State"),
    (
        re.compile(r"^Superintendent of Public Instruction\s*$", re.I),
        "Superintendent of Public Instruction",
        "spi",
        "State",
    ),
    (
        re.compile(r"^Board of Equalization Member District\s+(\d+)\s*$", re.I),
        "Member, State Board of Equalization, District {n}",
        "boe",
        "State",
    ),
    (
        re.compile(r"^United States Representative District\s+(\d+)\s*$", re.I),
        "U.S. House California District {n}",
        "us_house",
        "Federal",
    ),
    (
        re.compile(r"^State Senate District\s+(\d+)\s*$", re.I),
        "State Senate District {n}",
        "state_senate",
        "State",
    ),
    (
        re.compile(r"^State Assembly Member District\s+(\d+)\s*$", re.I),
        "Member of the State Assembly, District {n}",
        "state_assembly",
        "State",
    ),
]


def fetch_bytes(url: str, dest: Path | None = None) -> bytes:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = resp.read()
    if dest:
        dest.write_bytes(data)
    return data


def _pdf_text(path: Path) -> str:
    reader = PdfReader(str(path))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def _normalize_party(raw: str) -> str:
    return PARTY_MAP.get(raw.strip(), raw.strip())


def _is_junk(line: str) -> bool:
    # Do not treat office titles like "Secretary of State" as junk.
    if re.match(
        r"^(Governor|Lieutenant Governor|Secretary of State|Controller|Treasurer|"
        r"Attorney General|Insurance Commissioner|Superintendent of Public Instruction|"
        r"Board of Equalization|United States Representative|State Senate|State Assembly)\b",
        line,
        re.I,
    ):
        return False
    return bool(
        re.match(
            r"^(Page \d+|General Election|Official Certified|\*?\s*Incumbent|"
            r"SECRETARY OF STATE$|Dated at Sacramento|I, Shirley|That the following|"
            r"ballot designation|Primary Election|OFFICE OF THE|STATE OF CALIFORNIA$|\|)",
            line,
            re.I,
        )
    )


def parse_certified_list(text: str) -> dict[str, list[Race]]:
    races: dict[str, list[Race]] = {
        "statewide": [],
        "us_house": [],
        "state_senate": [],
        "state_assembly": [],
        "boe": [],
        "spi": [],
        "justices_sc": [],
        "justices_coa": [],
    }

    lines = [ln.strip() for ln in text.splitlines()]
    current: dict | None = None
    pending_name_party: tuple[str, str, bool] | None = None

    def flush():
        nonlocal current
        if current and current["candidates"]:
            races[current["bucket"]].append(
                Race(
                    name=current["title"],
                    level=current["level"],
                    candidates=current["candidates"],
                    vote_for="Vote for one",
                    description=current.get("description", ""),
                )
            )
        current = None

    name_party_re = re.compile(
        rf"^(?P<name>.+?)\s*(?P<star>\*)?\s+(?P<party>{PARTIES})\s*$"
    )

    for line in lines:
        if not line or _is_junk(line):
            continue

        matched_office = False
        for pat, template, bucket, level in OFFICE_PATTERNS:
            m = pat.match(line)
            if not m:
                continue
            flush()
            n = m.group(1) if m.lastindex else None
            title = template.format(n=n) if n else template
            current = {
                "title": title,
                "bucket": bucket,
                "level": level,
                "candidates": [],
                "description": f"District {n}" if n else "",
            }
            pending_name_party = None
            matched_office = True
            break
        if matched_office:
            continue

        # Stop candidate collection when we hit justices section headers
        if re.match(r"^JUSTICES OF THE", line, re.I):
            flush()
            pending_name_party = None
            continue

        if current is None:
            continue

        m = name_party_re.match(line)
        if m:
            # If we already had a name/party waiting without designation, commit it
            if pending_name_party:
                name, party, inc = pending_name_party
                current["candidates"].append(
                    Candidate(name=name, party=_normalize_party(party), designation="", incumbent=inc)
                )
            name = m.group("name").strip().rstrip("*").strip()
            incumbent = bool(m.group("star")) or "*" in m.group(0)
            pending_name_party = (name, m.group("party"), incumbent)
            continue

        # If this line is actually the next office header, don't treat it as a designation
        for pat, template, bucket, level in OFFICE_PATTERNS:
            m_off = pat.match(line)
            if not m_off:
                continue
            if pending_name_party:
                name, party, inc = pending_name_party
                current["candidates"].append(
                    Candidate(name=name, party=_normalize_party(party), designation="", incumbent=inc)
                )
                pending_name_party = None
            flush()
            n = m_off.group(1) if m_off.lastindex else None
            title = template.format(n=n) if n else template
            current = {
                "title": title,
                "bucket": bucket,
                "level": level,
                "candidates": [],
                "description": f"District {n}" if n else "",
            }
            break
        else:
            # Designation line for pending candidate
            if pending_name_party:
                name, party, inc = pending_name_party
                current["candidates"].append(
                    Candidate(
                        name=name,
                        party=_normalize_party(party),
                        designation=line,
                        incumbent=inc,
                    )
                )
                pending_name_party = None
            continue
        continue

    if pending_name_party and current is not None:
        name, party, inc = pending_name_party
        current["candidates"].append(
            Candidate(name=name, party=_normalize_party(party), designation="", incumbent=inc)
        )
    flush()

    # Supreme Court justices if mentioned
    if re.search(r"Kelli M\.\s*Evans", text, re.I):
        races["justices_sc"].append(
            Race(
                name="California Supreme Court — Retain Associate Justice Kelli M. Evans?",
                level="Judicial (Retention)",
                candidates=[
                    Candidate(
                        "Kelli M. Evans",
                        "Nonpartisan",
                        "Associate Justice, Supreme Court of California",
                        True,
                    )
                ],
                description="Retention: Yes or No.",
                vote_for="Yes or No",
            )
        )
    if re.search(r"Joshua P\.\s*Groban", text, re.I):
        races["justices_sc"].append(
            Race(
                name="California Supreme Court — Retain Associate Justice Joshua P. Groban?",
                level="Judicial (Retention)",
                candidates=[
                    Candidate(
                        "Joshua P. Groban",
                        "Nonpartisan",
                        "Associate Justice, Supreme Court of California",
                        True,
                    )
                ],
                description="Retention: Yes or No.",
                vote_for="Yes or No",
            )
        )

    return races


def load_certified_races(url: str = DEFAULT_CERT_LIST_URL, cache_dir: Path | None = None) -> dict[str, list[Race]]:
    cache_dir = cache_dir or Path(tempfile.gettempdir()) / "ballot_report_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    # Cache key by URL filename so primary vs general don't collide
    fname = re.sub(r"[^\w.\-]+", "_", url.rstrip("/").split("/")[-1]) or "cert-list.pdf"
    pdf_path = cache_dir / fname
    txt_path = cache_dir / (fname + ".txt")
    if not pdf_path.exists() or pdf_path.stat().st_size < 1000:
        fetch_bytes(url, pdf_path)
    text = _pdf_text(pdf_path)
    txt_path.write_text(text, encoding="utf-8")
    return parse_certified_list(text)


def filter_district_races(races: list[Race], district_nums: list[str]) -> list[Race]:
    wanted = {str(n) for n in district_nums}
    out = []
    for race in races:
        m = re.search(r"District\s+(\d+)", race.name)
        if m and m.group(1) in wanted:
            out.append(race)
    return out
