from __future__ import annotations

import html as htmlmod
import re
import tempfile
import urllib.request
from pathlib import Path

from pypdf import PdfReader

from ..models import Measure

UA = {"User-Agent": "Mozilla/5.0 (compatible; BallotReportBot/1.0)"}
PROP_NUMS = [1, 2, 3, 4, 5, 37, 38, 39, 40, 41, 42, 43, 44, 45]
VIG_PROP_URL = "https://voterguide.sos.ca.gov/propositions/{n}/"
VIG_ARGS_URL = "https://voterguide.sos.ca.gov/propositions/{n}/arguments-rebuttals.htm"
LAW_PDF_URL = "https://vig.cdn.sos.ca.gov/2026/general/pdf/text-proposed-laws.pdf"


def fetch_text(url: str) -> str:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=90) as resp:
        return resp.read().decode("utf-8", errors="ignore")


def html_to_text(h: str) -> str:
    t = re.sub(r"<script[\s\S]*?</script>", "", h, flags=re.I)
    t = re.sub(r"<style[\s\S]*?</style>", "", t, flags=re.I)
    t = re.sub(r"<br\s*/?>", "\n", t, flags=re.I)
    t = re.sub(r"</(p|h[1-6]|li|div|section)>", "\n", t, flags=re.I)
    t = re.sub(r"<[^>]+>", " ", t)
    t = htmlmod.unescape(t)
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def _section(text: str, starts: list[str], ends: list[str]) -> str:
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


def _split_laws(text: str) -> dict[int, str]:
    parts = re.split(r"(?=PROPOSITION\s+\d+\b)", text, flags=re.I)
    out: dict[int, str] = {}
    for part in parts:
        m = re.search(r"PROPOSITION\s+(\d+)\b", part, re.I)
        if m:
            out[int(m.group(1))] = part.strip()
    return out


def load_statewide_measures(cache_dir: Path | None = None) -> list[Measure]:
    cache_dir = cache_dir or Path(tempfile.gettempdir()) / "ballot_report_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    props_dir = cache_dir / "props"
    props_dir.mkdir(exist_ok=True)

    law_path = cache_dir / "text-proposed-laws.pdf"
    laws: dict[int, str] = {}
    try:
        if not law_path.exists():
            req = urllib.request.Request(LAW_PDF_URL, headers=UA)
            with urllib.request.urlopen(req, timeout=120) as resp:
                law_path.write_bytes(resp.read())
        reader = PdfReader(str(law_path))
        law_text = "\n".join((p.extract_text() or "") for p in reader.pages)
        (cache_dir / "text-proposed-laws.txt").write_text(law_text, encoding="utf-8")
        laws = _split_laws(law_text)
    except Exception:
        laws = {}

    measures: list[Measure] = []
    for n in PROP_NUMS:
        main_path = props_dir / f"prop{n}.html"
        args_path = props_dir / f"prop{n}_args.html"
        try:
            if not main_path.exists():
                main_path.write_text(fetch_text(VIG_PROP_URL.format(n=n)), encoding="utf-8")
            if not args_path.exists():
                try:
                    args_path.write_text(fetch_text(VIG_ARGS_URL.format(n=n)), encoding="utf-8")
                except Exception:
                    args_path.write_text("", encoding="utf-8")
        except Exception as exc:
            measures.append(
                Measure(
                    title=f"Proposition {n}",
                    level="Statewide Ballot Measures (Propositions)",
                    summary=f"Could not fetch proposition page: {exc}",
                    source_url=VIG_PROP_URL.format(n=n),
                )
            )
            continue

        main_t = html_to_text(main_path.read_text(encoding="utf-8", errors="ignore"))
        args_t = html_to_text(args_path.read_text(encoding="utf-8", errors="ignore")) if args_path.exists() else ""

        title_m = re.search(rf"PROP\s*\n?\s*{n}\s*\n+\s*([A-Z0-9][^\n]+)", main_t)
        title = title_m.group(1).strip() if title_m else f"Proposition {n}"
        summary = _section(main_t, ["SUMMARY"], ["WHAT YOUR VOTE MEANS", "ARGUMENTS"])
        summary = re.sub(r"^SUMMARY\s*", "", summary).strip()
        yes = _section(main_t, ["A YES vote on this measure means"], ["A NO vote on this measure means", "ARGUMENTS"])
        no = _section(main_t, ["A NO vote on this measure means"], ["ARGUMENTS", "FOR ADDITIONAL INFORMATION"])
        yes = re.sub(r"^A YES vote on this measure means[:\s]*", "", yes, flags=re.I).strip()
        no = re.sub(r"^A NO vote on this measure means[:\s]*", "", no, flags=re.I).strip()
        yes = re.split(r"\n\s*NO\b", yes)[0].strip()

        source = args_t if len(args_t) > 1000 else main_t
        arg_for = _section(source, ["Argument in Favor", "ARGUMENT IN FAVOR"], ["Rebuttal to Argument in Favor", "Argument Against"])
        reb_for = _section(source, ["Rebuttal to Argument in Favor", "REBUTTAL TO ARGUMENT IN FAVOR"], ["Argument Against", "ARGUMENT AGAINST"])
        arg_against = _section(source, ["Argument Against", "ARGUMENT AGAINST"], ["Rebuttal to Argument Against", "FOR ADDITIONAL INFORMATION", "Back to the Top"])
        reb_against = _section(source, ["Rebuttal to Argument Against", "REBUTTAL TO ARGUMENT AGAINST"], ["FOR ADDITIONAL INFORMATION", "Back to the Top", "Propositions"])

        measures.append(
            Measure(
                title=f"Proposition {n}: {title}",
                level="Statewide Ballot Measures (Propositions)",
                jurisdiction="Statewide — all California voters",
                threshold="Majority",
                summary=summary,
                yes_means=yes,
                no_means=no,
                arg_for=arg_for,
                reb_for=reb_for,
                arg_against=arg_against,
                reb_against=reb_against,
                full_text=laws.get(n, "See https://vig.cdn.sos.ca.gov/2026/general/pdf/text-proposed-laws.pdf"),
                source_url=VIG_PROP_URL.format(n=n),
            )
        )
    return measures
