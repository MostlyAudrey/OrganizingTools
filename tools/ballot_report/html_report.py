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


def heading_id(text: str, used: dict[str, int]) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-") or "section"
    used[base] = used.get(base, 0) + 1
    return base if used[base] == 1 else f"{base}-{used[base]}"


def heading(tag: str, text: str, hid: str) -> str:
    return f'<{tag} id="{esc(hid)}">{esc(text)}</{tag}>'


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


def h1(t: str, hid: str = "") -> str:
    return heading("h1", t, hid) if hid else f"<h1>{esc(t)}</h1>"


def h2(t: str, hid: str = "") -> str:
    return heading("h2", t, hid) if hid else f"<h2>{esc(t)}</h2>"


def h3(t: str) -> str:
    return f"<h3>{esc(t)}</h3>"


def p(t: str) -> str:
    return f"<p>{esc(t)}</p>"


def render_race(race: Race, hid: str = "") -> str:
    parts = [h2(race.name, hid)]
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


def render_measure(m: Measure, hid: str = "", include_measure_arguments: bool = True) -> str:
    parts = [h2(m.title, hid)]
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
    if include_measure_arguments:
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
    if include_measure_arguments:
        parts.append(h3("Full Text"))
        parts.append(p_blocks(m.full_text))
    if m.source_url:
        parts.append(p(f"Source: {m.source_url}"))
    return "\n".join(parts)


def render_html(report: BallotReport, include_measure_arguments: bool = True) -> str:
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
  nav.toc { margin: 1.6rem 0 2rem; padding: 1rem 1.25rem 1.15rem; border: 1px solid #bbb; background: #fafafa; }
  nav.toc > p { margin: 0 0 .6rem; font-weight: 700; }
  nav.toc ul { margin: .2rem 0; padding-left: 1.25rem; }
  nav.toc > ul { padding-left: 1.1rem; }
  nav.toc li { margin: .2rem 0; }
  nav.toc a { color: #111; }
</style>
</head>
<body>
""",
        h1(report.title),
        p(
            f"Places: {', '.join(report.places)}. "
            f"Counties: {', '.join(report.counties) or '(none)'}. "
            f"Cities: {', '.join(report.cities) or '(none)'}. "
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

    used_ids: dict[str, int] = {}
    toc: list[tuple[str, str, list[tuple[str, str]]]] = []
    title_id = heading_id(report.title, used_ids)
    toc.append((report.title, title_id, []))
    sections[1] = h1(report.title, title_id)

    def add_h1(title: str) -> str:
        hid = heading_id(title, used_ids)
        toc.append((title, hid, []))
        return hid

    def add_h2(title: str) -> str:
        hid = heading_id(title, used_ids)
        if toc:
            toc[-1][2].append((title, hid))
        return hid

    body: list[str] = []
    if report.notes:
        body.append(h1("Notes", add_h1("Notes")))
        for note in report.notes:
            body.append(p(note))

    ordered_levels = list(LEVEL_ORDER)
    for level in list(races_by_level) + list(measures_by_level):
        if level not in ordered_levels:
            ordered_levels.append(level)
    for level in ordered_levels:
        if level in races_by_level:
            body.append(h1(level, add_h1(level)))
            for race in races_by_level[level]:
                body.append(render_race(race, add_h2(race.name)))
        if level in measures_by_level:
            body.append(h1(level, add_h1(level)))
            for measure in measures_by_level[level]:
                body.append(
                    render_measure(
                        measure,
                        add_h2(measure.title),
                        include_measure_arguments=include_measure_arguments,
                    )
                )

    body.append(h1("Sources", add_h1("Sources")))

    toc_html = ['<nav class="toc" aria-label="Table of contents">', "<p>Contents</p>", "<ul>"]
    for title, hid, children in toc:
        toc_html.append(f'<li><a href="#{esc(hid)}">{esc(title)}</a>')
        if children:
            toc_html.append("<ul>")
            for child_title, child_id in children:
                toc_html.append(f'<li><a href="#{esc(child_id)}">{esc(child_title)}</a></li>')
            toc_html.append("</ul>")
        toc_html.append("</li>")
    toc_html.extend(["</ul>", "</nav>"])
    sections.extend(toc_html)
    sections.extend(body)
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


def write_report(report: BallotReport, path: Path, include_measure_arguments: bool = True) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        render_html(report, include_measure_arguments=include_measure_arguments),
        encoding="utf-8",
    )
    return path
