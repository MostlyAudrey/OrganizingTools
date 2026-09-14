from __future__ import annotations

import io
import re
import urllib.request

from ..geography import infer_city_from_text, normalize_place
from ..models import Candidate, Race

LAVOTE_CANDIDATE_LISTS = {
    "2026-11-03": "https://www.lavote.gov/Apps/CandidateList/Index?id=4348",
}

LAVOTE_PDFS = {
    "2026-11-03": (
        "https://content.lavote.gov/docs/rrcc/documents/"
        "final-list-of-qualified-candidates-to-appear-on-the-ballot"
        "9fcf3b64-1a33-4882-9e17-8cbc3b3c8d76.pdf"
    ),
}


def _fetch_bytes(url: str) -> bytes:
    from .county_local import UA

    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.read()


def _guess_level(office: str) -> str:
    h = office.lower()
    if "united states" in h or "u.s. representative" in h or "us representative" in h:
        return "Federal"
    if "state senator" in h or "member of the assembly" in h or "state assembly" in h:
        return "State"
    if "judge" in h or "superior court" in h:
        return "Judicial"
    if "city of" in h or "member of the city council" in h or "mayor" in h or "rent control" in h or re.search(
        r"\bcity (attorney|clerk|treasurer)\b", h
    ):
        return "Municipal / City"
    if "school" in h or "community college" in h or "board of education" in h or "board of trustees" in h:
        return "School Districts"
    if any(
        key in h
        for key in (
            "water district",
            "sanitation",
            "hospital district",
            "vector control",
            "community services",
            "irrigation",
            "recreation and park",
            "utility district",
            "library district",
            "cemetery district",
        )
    ):
        return "Special Districts"
    if "supervisor" in h or "sheriff" in h or "assessor" in h or "district attorney" in h:
        return "County"
    if "district" in h:
        return "Special Districts"
    return "County"


def _clean_office(office: str) -> str:
    office = re.sub(r"\s+", " ", office).strip()
    office = re.sub(r"^\d+-", "", office)
    office = re.sub(r"\s+GENERAL MUNICIPAL ELECTION\s+", " - ", office, flags=re.I)
    office = office.replace("\u2014", "-").replace("\u2013", "-")
    return office.strip(" —")


def _candidate(name: str, designation: str = "", party: str = "") -> Candidate | None:
    name = re.sub(r"\s+", " ", name).strip(" ,")
    if not name or len(name) < 3:
        return None
    if re.search(
        r"total number of candidates|vote for|non partisan|page \d+|phone:|of \d+",
        name,
        re.I,
    ):
        return None
    if re.match(r"^\d+\s", name) or re.match(r"^P\.?O\.?\s+BOX", name, re.I):
        return None
    if re.search(r", CA \d{5}", name):
        return None
    incumbent = bool(re.search(r"incumbent|councilmember|mayor", designation, re.I))
    party = party or "Nonpartisan"
    return Candidate(name=name, party=party, designation=designation, incumbent=incumbent)


def parse_lavote_html(html: str, county: str = "Los Angeles") -> list[Race]:
    from .county_local import TableExtractor
    parser = TableExtractor()
    parser.feed(html)
    grouped: dict[str, list[Candidate]] = {}
    for _heading, rows in parser.blocks:
        if len(rows) < 2:
            continue
        header = [c.lower() for c in rows[0]]
        try:
            name_i = next(i for i, h in enumerate(header) if "candidate" in h or h == "name")
            office_i = next(i for i, h in enumerate(header) if "office" in h)
        except StopIteration:
            continue
        party_i = next((i for i, h in enumerate(header) if "party" in h), None)
        for row in rows[1:]:
            if max(name_i, office_i) >= len(row):
                continue
            office = _clean_office(row[office_i])
            name = row[name_i].split("\n")[0].strip()
            party = row[party_i] if party_i is not None and party_i < len(row) else ""
            cand = _candidate(name, party=party)
            if not cand or not office:
                continue
            grouped.setdefault(office, []).append(cand)
    return _races_from_groups(grouped, county)


def _races_from_groups(grouped: dict[str, list[Candidate]], county: str) -> list[Race]:
    races: list[Race] = []
    seen_names: set[str] = set()
    for office, cands in grouped.items():
        uniq: list[Candidate] = []
        keys: set[str] = set()
        for c in cands:
            k = c.name.lower()
            if k in keys:
                continue
            keys.add(k)
            uniq.append(c)
        if not uniq:
            continue
        if office.lower() in seen_names:
            continue
        seen_names.add(office.lower())
        races.append(
            Race(
                name=office,
                level=_guess_level(office),
                candidates=uniq,
                county=county,
                city=infer_city_from_text(office, county),
            )
        )
    return races


_STREET_TOKENS = {
    "HWY", "BLVD", "AVE", "ST", "RD", "DR", "WAY", "LN", "BL", "CT", "PL", "PKWY", "BOX",
}
_HEADER_LINES = {
    "contest",
    "candidate name/occupation",
    "address/phone number",
    "email/website",
    "non partisan",
    "nonpartisan",
}
_OFFICE_CONTINUATIONS = {
    "board",
    "council",
    "directors",
    "trustees",
    "education",
    "attorney",
    "clerk",
    "treasurer",
}


def _is_noise_line(line: str) -> bool:
    low = line.lower().strip()
    if low in _HEADER_LINES:
        return True
    if re.match(r"^vote for\b", low):
        return True
    if re.match(r"^total number of candidates", low):
        return True
    if re.match(r"^phone:", low):
        return True
    if re.search(r"P\.?\s*O\.?\s+BOX", line, re.I):
        return True
    if re.search(r",\s*CA\b", line):
        return True
    if re.match(r"^#?\d+$", line):
        return True
    tokens = [t.strip(",") for t in line.split()]
    if any(t.upper() in _STREET_TOKENS for t in tokens):
        return True
    if re.search(r"\d{5}", line):
        return True
    return False


def _is_person_name_line(line: str) -> bool:
    if _is_noise_line(line):
        return False
    if re.search(r"\d", line):
        return False
    if re.search(r"ELECTION|DISTRICT|CITY OF|VOTE FOR|MEMBER OF", line, re.I):
        return False
    tokens = line.split()
    if not (2 <= len(tokens) <= 5):
        return False
    for i, tok in enumerate(tokens):
        core = tok.strip('",()')
        is_nick = tok.startswith('"') or tok.startswith("(")
        is_initial = bool(re.match(r"^[A-Z]\.$", tok))
        is_allcaps = bool(re.match(r"^[A-ZÀ-ÿ][A-ZÀ-ÿ'.-]*$", core))
        is_particle = core.lower() in {"de", "da", "la", "le", "van", "von", "di", "del"}
        if is_allcaps or is_nick or is_initial or (is_particle and i > 0):
            continue
        return False
    return True


def _candidates_from_pdf_lines(body: list[str], office: str) -> tuple[str, list[Candidate]]:
    cands: list[Candidate] = []
    i = 0
    while i < len(body):
        line = str(body[i]).strip()
        if line.lower() in _OFFICE_CONTINUATIONS and not office.lower().endswith(line.lower()):
            office = f"{office} {line}".strip()
            i += 1
            continue
        if _is_noise_line(line) or not _is_person_name_line(line):
            i += 1
            continue
        designation = ""
        if i + 1 < len(body):
            nxt = str(body[i + 1]).strip()
            if (
                nxt
                and not _is_person_name_line(nxt)
                and not _is_noise_line(nxt)
                and not re.match(r"^\d{3,}-", nxt)
                and not nxt.isupper()
            ):
                designation = nxt
                i += 1
        cand = _candidate(line, designation)
        if cand:
            cands.append(cand)
        i += 1
    return office, cands


def _office_from_contest_rest(rest: str) -> tuple[str, str]:
    """Return (office title, leftover candidate text)."""
    rest = re.sub(r"\s+", " ", rest).strip()
    leftover = ""
    m = re.search(
        r"^(.*?(?:Member of the (?:City Council|Rent Control Board|Board of Education|Board of Trustees|Governing Board)|"
        r"Mayor|City Clerk|City Treasurer|City Attorney|Member, Board of Supervisors|"
        r"Sheriff|District Attorney|Assessor|County Superintendent)(?:[^A-Z]*Vote for no more than \d+)?)"
        r"(?:\s+NON PARTISAN)?(?:\s+(.+))?$",
        rest,
        re.I,
    )
    if m:
        office = re.sub(r"\s+Vote for no more than \d+\s*$", "", m.group(1), flags=re.I).strip()
        leftover = (m.group(2) or "").strip()
        leftover = re.sub(r"^NON PARTISAN\s+", "", leftover, flags=re.I)
        return office, leftover
    office = re.sub(r"\s+NON PARTISAN\s*$", "", rest, flags=re.I)
    office = re.sub(r"\s+Vote for no more than \d+\s*$", "", office, flags=re.I)
    return office.strip(), ""


def parse_lavote_pdf_text(text: str, county: str = "Los Angeles") -> list[Race]:
    """Parse LA Registrar qualified-candidate PDF text."""
    text = text.replace("\r", "")
    lines = []
    for raw in text.split("\n"):
        line = raw.strip()
        if not line:
            continue
        if re.match(r"^\d+\s+OF\s+\d+$", line, re.I):
            continue
        if re.search(r"LOS ANGELES COUNTY|REGISTRAR-RECORDER|QUALIFIED CANDIDATE", line, re.I):
            continue
        lines.append(line)

    contests: dict[str, dict[str, object]] = {}
    order: list[str] = []
    current_id: str | None = None
    contest_re = re.compile(r"^(\d{3,})-(.+)$")

    for line in lines:
        m = contest_re.match(line)
        if m and (
            "ELECTION" in line.upper()
            or "DISTRICT" in line.upper()
            or "CITY OF" in line.upper()
            or "COUNTY" in line.upper()
        ):
            cid, rest = m.group(1), m.group(2)
            office, leftover = _office_from_contest_rest(rest)
            if cid not in contests:
                contests[cid] = {"office": office, "lines": []}
                order.append(cid)
            elif not contests[cid]["office"] and office:
                contests[cid]["office"] = office
            current_id = cid
            if leftover:
                contests[cid]["lines"].append(leftover)  # type: ignore[union-attr]
            continue
        if current_id:
            contests[current_id]["lines"].append(line)  # type: ignore[union-attr]

    grouped: dict[str, list[Candidate]] = {}
    for cid in order:
        office = str(contests[cid]["office"])
        office, cands = _candidates_from_pdf_lines(list(contests[cid]["lines"]), office)  # type: ignore[arg-type]
        office = _clean_office(office)
        grouped.setdefault(office, []).extend(cands)
    return _races_from_groups(grouped, county)


def _pdf_to_text(data: bytes) -> str:
    try:
        from pypdf import PdfReader  # type: ignore
    except ImportError:
        try:
            from PyPDF2 import PdfReader  # type: ignore
        except ImportError:
            raise RuntimeError("Install pypdf to parse the LA County candidate PDF.")
    reader = PdfReader(io.BytesIO(data))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def scrape_lavote(
    county: str = "Los Angeles",
    election_date: str = "2026-11-03",
) -> tuple[list[Race], list[str]]:
    notes: list[str] = []
    html_url = LAVOTE_CANDIDATE_LISTS.get(election_date)
    pdf_url = LAVOTE_PDFS.get(election_date)
    races: list[Race] = []
    if pdf_url:
        try:
            pdf = _fetch_bytes(pdf_url)
            text = _pdf_to_text(pdf)
            races = parse_lavote_pdf_text(text, county)
            notes.append(f"Los Angeles local candidates loaded from PDF {pdf_url}.")
        except Exception as extra:
            notes.append(f"Could not parse LA County candidate PDF: {extra}")
    if len(races) < 5 and html_url:
        try:
            html = _fetch_bytes(html_url).decode("utf-8", errors="ignore")
            races = parse_lavote_html(html, county)
            notes.append(f"Los Angeles local candidates loaded from {html_url}.")
        except Exception as exc:
            notes.append(f"Could not parse LA Vote HTML candidate list: {exc}")

    local_levels = {"County", "Municipal / City", "School Districts", "Special Districts"}
    races = [r for r in races if r.level in local_levels]
    if not races:
        notes.append(
            "No Los Angeles municipal/county contests were parsed. Confirm the lavote.gov candidate list."
        )
    else:
        notes.append(
            f"Parsed {len(races)} Los Angeles County local contests "
            f"({sum(1 for r in races if r.level == 'Municipal / City')} municipal)."
        )
    return races, notes
