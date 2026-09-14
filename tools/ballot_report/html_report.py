from __future__ import annotations

import html
import re
from pathlib import Path

from .models import BallotReport, Measure, Race

LEVEL_ORDER = [
    "Federal",
    "State",
    "Judicial (Retention)",
    "County",
    "Municipal / City",
    "School Districts",
    "Special Districts",
    "Statewide Ballot Measures (Propositions)",
    "Local Ballot Measures",
]


def esc(s: str) -> str:
    return html.escape(re.sub(r"[ \t]+\n", "\n", s or "").strip())


def p_blocks(text: str) -> str:
    text = (text or "").strip()
    if not text:
        return "<p><em>Not available from official sources at time of compilation.</em></p>"
    parts = re.split(r"\n\s*\n", text)
    out = []
    for part in parts:
        part = re.sub(r"\s*\n\s*", " ", part).strip()
        if part:
            out.append(f"<p>{esc(part)}</p>")
    return "\n".join(out) if out else f"<p>{esc(text)}</p>"


def h1(t: str) -> str:
    return f"<h1>{esc(t)}</h1>"


def h2(t: str) -> str:
    return f"<h2>{esc(t)}</h2>"


def h3(t: str) -> str:
    return f"<h3>{esc(t)}</h3>"


def p(t: str) -> str:
    return f"<p>{esc(t)}</p>"


def render_race(race: Race) -> str:
    parts = [h2(race.name)]
    if race.description:
        parts.append(p(race.description))
    if race.vote_for:
        parts.append(p(race.vote_for))
    if not race.candidates:
        parts.append(p("No candidates listed in available official sources."))
    for cand in race.candidates:
        parts.append(h3(cand.heading))
        parts.append(p(cand.details))
    return "\n".join(parts)


def render_measure(m: Measure) -> str:
    parts = [h2(m.title)]
    if m.jurisdiction:
        parts.append(p(f"Jurisdiction: {m.jurisdiction}"))
    if m.threshold:
        parts.append(p(f"Passage threshold: {m.threshold}"))
    if m.ballot_question:
        parts.append(h3("Ballot Question"))
        parts.append(p_blocks(m.ballot_question))
    if m.summary:
        parts.append(h3("Official Summary"))
        parts.append(p_blocks(m.summary))
    parts.append(h3("What a Yes Vote Means"))
    parts.append(p_blocks(m.yes_means))
    parts.append(h3("What a No Vote Means"))
    parts.append(p_blocks(m.no_means))
    if m.analysis:
        parts.append(h3("Impartial Analysis"))
        parts.append(p_blocks(m.analysis))
    parts.append(h3("Argument in Favor"))
    parts.append(p_blocks(m.arg_for))
    if m.reb_for.strip():
        parts.append(h3("Rebuttal to Argument in Favor"))
        parts.append(p_blocks(m.reb_for))
    parts.append(h3("Argument Against"))
    parts.append(p_blocks(m.arg_against))
    if m.reb_against.strip():
        parts.append(h3("Rebuttal to Argument Against"))
        parts.append(p_blocks(m.reb_against))
    if m.tax_rate_statement:
        parts.append(h3("Tax Rate Statement"))
        parts.append(p_blocks(m.tax_rate_statement))
    parts.append(h3("Full Text"))
    parts.append(p_blocks(m.full_text))
    if m.source_url:
        parts.append(p(f"Source: {m.source_url}"))
    return "\n".join(parts)


def render_html(report: BallotReport) -> str:
    races_by_level: dict[str, list[Race]] = {}
    for race in report.races:
        races_by_level.setdefault(race.level, []).append(race)

    measures_by_level: dict[str, list[Measure]] = {}
    for measure in report.measures:
        measures_by_level.setdefault(measure.level, []).append(measure)

    sections: list[str] = [
        """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>"""
        + esc(report.title)
        + """</title>
<style>
  body { font-family: Georgia, 'Times New Roman', serif; max-width: 900px; margin: 2rem auto; padding: 0 1rem; line-height: 1.45; color: #111; }
  h1 { border-bottom: 2px solid #222; padding-bottom: .3rem; margin-top: 2.5rem; }
  h2 { margin-top: 1.8rem; color: #222; }
  h3 { margin-top: 1.1rem; color: #333; }
  p { margin: .55rem 0; }
  .note { background: #f5f5f5; padding: 1rem; border-left: 4px solid #666; margin: 1rem 0; }
</style>
</head>
<body>
""",
        h1(report.title),
        p(
            f"Places: {', '.join(report.places)}. "
            f"Resolved counties: {', '.join(report.counties) or '(none)'}. "
            f"Election: {report.election_date}."
        ),
        '<div class="note">'
        + p(
            "How to import: In Google Docs use File → Open → Upload this .html file. "
            "In Microsoft Word use File → Open and select this HTML file. "
            "Heading styles (Heading 1 / 2 / 3) are preserved."
        )
        + "</div>",
    ]

    if report.notes:
        sections.append(h1("Notes"))
        for note in report.notes:
            sections.append(p(note))

    for level in LEVEL_ORDER:
        if level in races_by_level:
            sections.append(h1(level))
            for race in races_by_level[level]:
                sections.append(render_race(race))
        if level in measures_by_level:
            sections.append(h1(level))
            for measure in measures_by_level[level]:
                sections.append(render_measure(measure))

    # Any unexpected levels
    for level, races in races_by_level.items():
        if level not in LEVEL_ORDER:
            sections.append(h1(level))
            for race in races:
                sections.append(render_race(race))
    for level, measures in measures_by_level.items():
        if level not in LEVEL_ORDER:
            sections.append(h1(level))
            for measure in measures:
                sections.append(render_measure(measure))

    sections.append(h1("Sources"))
    for src in report.sources:
        sections.append(p(src))
    sections.append(
        p(
            "Compiled as a research aid. Confirm final ballot content with your county sample ballot "
            "or Official Voter Information Guide."
        )
    )
    sections.append("</body></html>")
    return "\n".join(sections)


def write_report(report: BallotReport, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_html(report), encoding="utf-8")
    return path
