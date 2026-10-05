"""Fact store with version scoping + conflict detection. Never silently picks one value."""
import sqlite3
from dataclasses import dataclass
from typing import List, Optional
from src.database import DatabaseManager
from src.knowledge.aliases import sw_in_scope, sw_tuple


@dataclass
class Fact:
    fact_id: int; subject: str; predicate: str; value: str; unit: Optional[str]; sw_from: Optional[str]
    sw_before: Optional[str]; status: str; trust: Optional[int]; passage_id: str; doc_id: str; note: Optional[str]
    confidence: float

    def scope_text(self) -> str:
        if self.sw_from and self.sw_before: return f"software {self.sw_from}–<{self.sw_before}"
        if self.sw_from: return f"software ≥{self.sw_from}"
        if self.sw_before: return f"software <{self.sw_before}"
        return "scope not stated"

    def display(self) -> str:
        return f"{self.value}{' ' + self.unit if self.unit and not self.value.endswith(self.unit) else ''}"


class FactStore:
    def __init__(self, db: DatabaseManager):
        self.db = db

    def get(self, subject: str, predicate: str) -> List[Fact]:
        with self.db.conn() as c:
            rows = c.execute("SELECT * FROM facts WHERE subject=? AND predicate=? ORDER BY trust, fact_id", (subject, predicate)).fetchall()
        return [self._row(r) for r in rows]

    def like(self, subject: str, prefix: str) -> List[Fact]:
        with self.db.conn() as c:
            rows = c.execute("SELECT * FROM facts WHERE subject=? AND predicate LIKE ? ORDER BY trust, fact_id", (subject, prefix + "%")).fetchall()
        return [self._row(r) for r in rows]

    def subjects_with(self, predicate: str) -> List[str]:
        with self.db.conn() as c:
            return [r[0] for r in c.execute("SELECT DISTINCT subject FROM facts WHERE predicate=? ORDER BY subject", (predicate,))]

    def passage(self, passage_id: str) -> dict:
        with self.db.conn() as c:
            r = c.execute("""SELECT p.*, d.filename, d.rel_path, d.doc_code, d.revision_id AS doc_rev, d.applies_to
                             FROM passages p JOIN documents d ON d.doc_id=p.doc_id WHERE passage_id=?""", (passage_id,)).fetchone()
        return dict(r) if r else {}

    def edges(self) -> List[dict]:
        with self.db.conn() as c:
            return [dict(r) for r in c.execute("SELECT * FROM edges")]

    def entity(self, eid: str) -> Optional[dict]:
        with self.db.conn() as c:
            r = c.execute("SELECT * FROM entities WHERE entity_id=?", (eid,)).fetchone()
        return dict(r) if r else None

    def doc_count_by_ext(self, ext: str) -> List[str]:
        with self.db.conn() as c:
            return [r[0] for r in c.execute("SELECT rel_path FROM documents WHERE rel_path LIKE ?", (f"%{ext}",))]

    @staticmethod
    def _row(r: sqlite3.Row) -> Fact:
        return Fact(r["fact_id"], r["subject"], r["predicate"], r["value"], r["unit"], r["sw_from"], r["sw_before"],
                    r["status"], r["trust"], r["passage_id"], r["doc_id"], r["note"], r["confidence"])


def resolve_scoped(facts: List[Fact], sw: Optional[str] = None) -> dict:
    """Partition facts for one (subject,predicate):
       applicable   : scope contains `sw` (or all, if sw unknown), status asserted, trust<=3
       other_scopes : asserted facts valid for other software revisions (version-scoped, NOT conflicts)
       unverified   : low-trust / superseded / unverified-status facts -> reported, never used as the answer
       conflicts    : trusted facts with overlapping scopes but different values."""
    trusted = [f for f in facts if f.status == "asserted" and (f.trust or 9) <= 3]
    appl = [f for f in trusted if sw is None or sw_in_scope(sw, f.sw_from, f.sw_before)]
    other = [f for f in trusted if f not in appl]
    unver = [f for f in facts if f not in trusted]

    def overlap(a: Fact, b: Fact) -> bool:
        af, ab, bf, bb = sw_tuple(a.sw_from), sw_tuple(a.sw_before), sw_tuple(b.sw_from), sw_tuple(b.sw_before)
        lo = max([x for x in (af, bf) if x is not None], default=None)
        hi = min([x for x in (ab, bb) if x is not None], default=None)
        return lo is None or hi is None or lo < hi

    conflicts = []
    for i, a in enumerate(trusted):
        for b in trusted[i + 1:]:
            if a.display() != b.display() and overlap(a, b):
                conflicts.append((a, b))
    return {"applicable": appl, "other_scopes": other, "unverified": unver, "conflicts": conflicts}
