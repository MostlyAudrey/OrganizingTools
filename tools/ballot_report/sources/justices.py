from __future__ import annotations

"""
Known judicial retention contests by election date.

Court of Appeal justices are filtered by appellate district / county at report-build time.
"""

from ..models import Candidate, Race

# November 3, 2026 — from SOS VIG / Ballotpedia
RETENTION_2026_11_03 = {
    "supreme": [
        Race(
            name="California Supreme Court — Retain Associate Justice Kelli M. Evans?",
            level="Judicial (Retention)",
            candidates=[
                Candidate(
                    "Kelli M. Evans",
                    "Nonpartisan",
                    "Associate Justice, Supreme Court of California",
                    True,
                    "Retention: Yes or No.",
                )
            ],
            description="Statewide retention. A Yes vote retains the justice; a No vote does not.",
            vote_for="Yes or No",
        ),
        Race(
            name="California Supreme Court — Retain Associate Justice Joshua P. Groban?",
            level="Judicial (Retention)",
            candidates=[
                Candidate(
                    "Joshua P. Groban",
                    "Nonpartisan",
                    "Associate Justice, Supreme Court of California",
                    True,
                    "Retention: Yes or No.",
                )
            ],
            description="Statewide retention. A Yes vote retains the justice; a No vote does not.",
            vote_for="Yes or No",
        ),
    ],
    "coa": {
        "3": [
            "Laurie M. Earl",
            "Lauri Damrell",
            "David B. Sapp",
            "Stacy Boulware Eurie",
            "Jonathan Renner",
            "Aimee A. Feinberg",
            "Shama Mesiwala",
        ],
    },
}


def retention_races_for(election_iso: str, appellate_districts: list[str]) -> list[Race]:
    if election_iso != "2026-11-03":
        return []
    data = RETENTION_2026_11_03
    out = list(data["supreme"])
    for dist in appellate_districts:
        names = data["coa"].get(str(dist), [])
        if not names:
            continue
        out.append(
            Race(
                name=f"Court of Appeal, {_ordinal(dist)} Appellate District",
                level="Judicial (Retention)",
                description=(
                    f"Voters in this appellate district decide Yes/No retention for each justice. "
                    f"Each justice is a separate ballot question."
                ),
                candidates=[
                    Candidate(
                        n,
                        "Nonpartisan",
                        f"Associate Justice, Court of Appeal, {_ordinal(dist)} Appellate District",
                        True,
                        "Retention: Yes or No.",
                    )
                    for n in names
                ],
                vote_for="Yes or No for each justice",
            )
        )
    return out


def _ordinal(n: str) -> str:
    mapping = {
        "1": "First",
        "2": "Second",
        "3": "Third",
        "4": "Fourth",
        "5": "Fifth",
        "6": "Sixth",
    }
    return mapping.get(str(n), str(n))
