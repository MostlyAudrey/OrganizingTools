from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Candidate:
    name: str
    party: str = ""
    designation: str = ""
    incumbent: bool = False
    notes: str = ""

    @property
    def heading(self) -> str:
        return f"{self.name} (Incumbent)" if self.incumbent else self.name

    @property
    def details(self) -> str:
        bits = []
        if self.party:
            bits.append(self.party)
        if self.designation:
            bits.append(f"Ballot designation: {self.designation}")
        if self.notes:
            bits.append(self.notes)
        return " — ".join(bits) if bits else "No additional details available."


@dataclass
class Race:
    name: str
    level: str  # Federal, State, Judicial, County, Municipal / City, School Districts, Special Districts
    candidates: list[Candidate] = field(default_factory=list)
    description: str = ""
    vote_for: str = ""


@dataclass
class Measure:
    title: str
    level: str  # Statewide Ballot Measures, Local Ballot Measures
    jurisdiction: str = ""
    threshold: str = ""
    ballot_question: str = ""
    summary: str = ""
    yes_means: str = ""
    no_means: str = ""
    analysis: str = ""
    arg_for: str = ""
    reb_for: str = ""
    arg_against: str = ""
    reb_against: str = ""
    full_text: str = ""
    tax_rate_statement: str = ""
    source_url: str = ""


@dataclass
class BallotReport:
    title: str
    places: list[str]
    counties: list[str]
    election_date: str
    races: list[Race] = field(default_factory=list)
    measures: list[Measure] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
