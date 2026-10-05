from dataclasses import dataclass, field, asdict
from typing import List, Optional

ANSWERED, CAVEATS, CONFLICT, INSUFFICIENT = "ANSWERED", "ANSWERED_WITH_CAVEATS", "CONFLICT", "INSUFFICIENT_EVIDENCE"


@dataclass
class Evidence:
    passage_id: str
    source: str          # dataset-relative path
    doc_code: Optional[str]
    revision: Optional[str]
    location: str        # page / slide / sheet-row / section
    quote: str
    trust: Optional[int]
    method: str          # text | ocr | table | vector | structured


@dataclass
class Claim:
    text: str
    evidence: List[Evidence] = field(default_factory=list)


@dataclass
class Answer:
    question: str
    answer: str
    status: str
    confidence: str
    claims: List[Claim] = field(default_factory=list)
    conflicts: List[str] = field(default_factory=list)
    unknowns: List[str] = field(default_factory=list)
    assumptions: List[str] = field(default_factory=list)
    retrieved: List[dict] = field(default_factory=list)
    handler: str = ""
    timings_ms: dict = field(default_factory=dict)

    def cited_passage_ids(self):
        return [e.passage_id for c in self.claims for e in c.evidence]

    def to_dict(self):
        return asdict(self)
