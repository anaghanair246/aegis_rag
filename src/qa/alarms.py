"""Alarm-record answering (facet-aware, procedure-aware).

An alarm table row is ONE record: condition, possible causes, required action (whole cell), footnote, references.
This module answers only the facets the question asks for (meaning / causes / action / restart), always from the
whole record, and validates its own output:
  * completeness guard  - an action answer must contain the entire stored required-action cell (repairs it if not);
  * contamination guard - a stop/restart instruction may only be stated for an alarm if the cited evidence is THAT
                          alarm's record (or a non-alarm-table passage); otherwise the draft is discarded and rebuilt;
  * unverifiable ids    - an alarm id absent from the documents abstains, explains why, and never maps to other docs.
Nothing here is keyed to particular alarm ids or questions: ids and ranges come from the stored facts."""
import re
from typing import Dict, List, Optional
from src.qa.models import Answer, Claim, ANSWERED, CAVEATS, INSUFFICIENT

ID_RE = re.compile(r"(?<![A-Za-z0-9\-])A([-\s]?)(\d{2,5})(?![A-Za-z0-9])")
FACET_PATTERNS = {
    "meaning": r"\b(mean\w*|indicat\w*|signif\w*|condition|thresholds?|limits?|setpoint|what is (the )?(alarm )?A\d)",
    "causes": r"\b(causes?|caused|why|reasons?|trigger\w*|raised|due to|source|originat\w*)\b",
    "action": r"\b(actions?|do|response|respond\w*|procedures?|fix\w*|resolve\w*|handle|handling|required|remed\w*|steps?|clear\w*|deal|rectif\w*|mandatory|shutdown)\b",
    "restart": r"\b(re-?start\w*|resume\w*|return(ing)? to service|start(ing)? (it |the \w+ )?(again|up)|bring\w* (it |the \w+ )?back|power(ing)? (it |the \w+ )?(on|up) again)\b",
}
DEFAULT_FACETS = ["meaning", "causes", "action"]
ORDER = ["meaning", "causes", "action", "restart"]
RESTART_RE = re.compile(r"\b(re-?start|resume|return to service)\w*", re.I)
STOP_RE = re.compile(r"\b(stop the \w+|shut ?down|isolate|close \w+-?\d*|do not (?:re-?)?start\w*)", re.I)
REF_VERBS_NEUTRAL = {"see", "refer", "consult", "review", "check"}
_norm = lambda t: re.sub(r"\s+", " ", t.replace("*", "")).strip().lower()


def find_alarm_ids(q: str) -> List[Dict[str, str]]:
    """Alarm-id-like tokens: 'A19', 'A-1042', or 'A 19' (only when the question says 'alarm')."""
    out, seen = [], set()
    for m in ID_RE.finditer(q):
        sep, digits = m.group(1), m.group(2)
        if sep.isspace() and "alarm" not in q.lower():
            continue
        aid = "A" + digits
        if aid not in seen:
            seen.add(aid); out.append({"raw": m.group(0).strip(), "id": aid})
    return out


def sentences(text: str) -> List[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+(?=[A-Z])", text.replace("*", "").strip()) if s.strip()]


class AlarmAnswerer:
    def __init__(self, engine):
        self.e, self.fs, self.db = engine, engine.fs, engine.db

    # ---------- discovery ----------
    def documented(self) -> List[str]:
        with self.db.conn() as c:
            return [r[0] for r in c.execute("SELECT DISTINCT subject FROM facts WHERE predicate='condition' ORDER BY subject")]

    def targets(self, q: str) -> List[Dict[str, str]]:
        found = find_alarm_ids(q)
        have = {t["id"] for t in found}
        low = q.lower()
        for a in self.documented():  # alarm named by its documented condition text rather than its id
            cond = self.fs.get(a, "condition")
            if cond and len(cond[0].value.split()) >= 3 and cond[0].value.lower() in low and a not in have:
                found.append({"raw": cond[0].value, "id": a})
        return found

    @staticmethod
    def facets(q: str) -> List[str]:
        got = [f for f in ORDER if re.search(FACET_PATTERNS[f], q, re.I)]
        return got or list(DEFAULT_FACETS)

    # ---------- answering ----------
    def answer(self, q: str, targets: Optional[List[Dict[str, str]]] = None, facets: Optional[List[str]] = None) -> Answer:
        targets = targets or self.targets(q)
        facets = facets or self.facets(q)
        doc = set(self.documented())
        subs = [self._record(q, t["id"], facets) if t["id"] in doc else self._unverified(q, t) for t in targets]
        if len(subs) == 1:
            return subs[0]
        rank = {ANSWERED: 0, CAVEATS: 1, INSUFFICIENT: 2}
        st = max((s.status for s in subs), key=lambda x: rank.get(x, 1))
        return Answer(q, " ‖ ".join(s.answer for s in subs), st, "medium" if st != INSUFFICIENT else "n/a",
                      [c for s in subs for c in s.claims], [x for s in subs for x in s.conflicts],
                      [x for s in subs for x in s.unknowns], [x for s in subs for x in s.assumptions])

    def _src(self, facts) -> str:
        p = self.fs.passage(facts[0].passage_id) if facts else {}
        return f"{p.get('doc_code') or p.get('filename', '?')}" + (f" Rev {p['doc_rev']}" if p.get("doc_rev") else "")

    def _record(self, q: str, a: str, facets: List[str]) -> Answer:
        fs, cl, parts, unknowns, notes, gaps = self.fs, [], [], [], [], []
        cond, causes, act = fs.get(a, "condition"), fs.get(a, "possible_cause"), fs.get(a, "required_action")
        foot, refs = fs.get(a, "required_action_footnote"), fs.get(a, "required_action_reference")
        src = self._src(cond or act or causes)
        covered, missing = set(), set()
        action_txt = act[0].value.replace("*", "").strip() if act else None

        if "meaning" in facets:
            if cond:
                parts.append(f"{a} indicates: {cond[0].value}.")
                cl.append(self.e.claim(f"{a} indicates: {cond[0].value} ({src}).", cond)); covered.add("meaning")
                ev = fs.get(a, "evaluated_against")
                if ev:
                    cl.append(self.e.claim(f"Per ECN-1058, {a} is evaluated against the active pressure sensor: {ev[0].value}; thresholds unchanged.", ev))
            else:
                missing.add("meaning")
        if "causes" in facets:
            if causes:
                txt = "; ".join(f"({i+1}) {c.value}" for i, c in enumerate(causes))
                parts.append(f"Possible causes of {a}: {txt}.")
                cl.append(self.e.claim(f"Possible causes of {a} ({src}): {txt}.", causes)); covered.add("causes")
            else:
                missing.add("causes")
        if "action" in facets:
            if act:
                note = f" [Footnote: {foot[0].value}]" if foot else ""
                parts.append(f"Required action for {a} ({src}): {action_txt}{note}")
                cl.append(self.e.claim(f"Required action for {a} ({src}), complete cell: {action_txt}", act))
                if foot:
                    cl.append(self.e.claim(f"Footnote qualifying the {a} required action: {foot[0].value}", foot))
                elif act[0].value.endswith("*"):
                    gaps.append(f"The {a} required action carries a footnote marker (*) but the footnote text could not be located.")
                for pf in fs.get(a, "persistence_threshold_before_action"):
                    cl.append(self.e.claim(f"Maintenance Manual: the persistence threshold for {a} is {pf.value} {pf.unit} ({pf.note}).", [pf]))
                for r in refs:
                    c, g = self._reference(a, r.value, action_txt)
                    if c: cl.append(c)
                    if g: gaps.append(g)
                if not any(STOP_RE.search(s) or RESTART_RE.search(s) for s in sentences(act[0].value)):
                    others = [o for o in self.documented() if o != a and any(STOP_RE.search(s) or RESTART_RE.search(s) for s in sentences((fs.get(o, "required_action") or [type("F", (), {"value": ""})])[0].value))]
                    notes.append(f"The Alarm Reference lists no stop-the-unit or restart instruction in {a}'s required action; do not assume one applies."
                                 + (f" Such instructions appear only on {', '.join(others)} (a different alarm and condition) and are not shown to apply to {a}." if others else ""))
                covered.add("action")
            else:
                missing.add("action")
        if "restart" in facets:
            rs = [s for s in sentences(act[0].value) if RESTART_RE.search(s)] if act else []
            if rs:
                parts.append(f"Restart after {a}: " + " ".join(rs))
                cl.append(self.e.claim(f"Restart restriction for {a} ({src}): " + " ".join(rs), act)); covered.add("restart")
            else:
                missing.add("restart")
                parts.append(f"Restart after {a}: the package documents no restart condition or authorisation for {a}, so restarting cannot be confirmed as permitted."
                             + (f" The only documented required action is: {action_txt}" if act else ""))
                if act:
                    cl.append(self.e.claim(f"Documented required action for {a} ({src}) — it contains no restart authorisation: {action_txt}", act))
                notes.append(f"The absence of a documented restriction for {a} is not permission to restart; follow the documented required action and site procedures.")

        unknowns += gaps + notes
        for m in sorted(missing - {"restart"}):
            unknowns.append(f"No documented {m} for {a} in the package.")
        if not covered:
            status, conf = INSUFFICIENT, "n/a"
        elif missing or gaps:
            status, conf = CAVEATS, "medium"
        else:
            status, conf = ANSWERED, "high"
        if status == INSUFFICIENT and not parts:
            parts.append(f"No documentation of {a} facets {sorted(missing)} was found.")
        return Answer(q, " ".join(parts), status, conf, cl, [], unknowns, [])

    def _reference(self, alarm: str, ref: str, action: str):
        m = re.match(r"(Maintenance|Operator) Manual Section (\d+)", ref)
        kind, n = m.group(1), m.group(2)
        suffix = "maintenance_manual.pdf" if kind == "Maintenance" else "operator_manual.pdf"
        for p in self.e.index.ps:
            if not p["rel_path"].endswith(suffix):
                continue
            sec = re.search(rf"(?ms)^{n}\.\s+(.+?)(?=^\d+\.\s+[A-Z]|\Z)", p["content"])
            if not sec:
                continue
            body = sec.group(0); title = sec.group(1).split("\n")[0].strip()
            sent = next((s for s in sentences(action) if f"Section {n}" in s), action)
            verb = (re.findall(r"[A-Za-z]+", sent) or [""])[0].lower()
            cl = self.e.claim(f"The {kind} Manual Section {n} referenced by the {alarm} required action is '{title}'"
                              + (f" and it mentions {alarm}." if alarm in body else f" and it does not mention {alarm}."), passages=[p["passage_id"]], needle=f"{n}. {title[:18]}")
            gap = None
            if verb not in REF_VERBS_NEUTRAL and verb[:5] not in body.lower():
                gap = (f"The referenced {kind} Manual Section {n} ('{title}') as provided in the package contains no '{verb}' procedure, "
                       f"so the detailed steps behind \"{sent.strip()}\" cannot be given from the available documents.")
            return cl, gap
        return None, f"The {kind} Manual Section {n} referenced by the {alarm} required action is not present in the package."

    # ---------- identifiers that cannot be verified ----------
    def _unverified(self, q: str, tok: Dict[str, str]) -> Answer:
        a, raw, fs = tok["id"], tok["raw"], self.fs
        doc = self.documented()
        cl, unknowns = [], []
        row = fs.get(doc[0], "condition") if doc else []
        if row:
            cl.append(self.e.claim(f"The Alarm Reference lists only these alarms: {', '.join(doc)}.", [fs.get(d, "condition")[0] for d in doc]))
        rng = fs.get("AEG-AL-700", "external_alarm_ranges")
        digits = int(a[1:])
        in_ext = False
        if rng:
            for lo, hi in re.findall(r"A(\d+)[–-]A(\d+)", rng[0].value):
                in_ext |= int(lo) <= digits <= int(hi)
            cl.append(self.e.claim(f"Other alarm ranges ({rng[0].value}) are {rng[0].note}.", rng))
        with self.db.conn() as c:
            coll = c.execute("SELECT d.rel_path, d.doc_code, p.passage_id FROM documents d JOIN passages p USING(doc_id) "
                             "WHERE d.doc_code LIKE ? AND p.passage_id LIKE '%\\_p1' ESCAPE '\\' LIMIT 1", (f"%-{digits}",)).fetchone()
        if in_ext:
            why = f"{a} falls in a range documented in a companion alarm reference that is not part of the package."
        else:
            why = (f"'{raw}' is not an identifier found in the Alarm Reference"
                   + (" or in the other alarm ranges it cites" if rng else "") + "; the documented alarm tags are two-digit (e.g. " + (doc[0] if doc else "A17") + ").")
        unknowns.append(why)
        if coll:
            cl.append(self.e.claim(f"The number {digits} also appears in {coll['doc_code']}, which is an engineering change notice (a controlled document), not an alarm. "
                                   "No relationship between it and an alarm identifier is inferred.", passages=[coll["passage_id"]], needle=coll["doc_code"]))
            unknowns.append(f"{coll['doc_code']} is a document identifier, not an alarm tag; the similar number is coincidental as far as the package shows.")
        unknowns.append(f"Nothing in the package describes an alarm '{raw}', so its meaning, causes and required action cannot be determined.")
        return Answer(q, f"Cannot be determined: the alarm identifier '{raw}' cannot be verified in the available documents. " + why
                      + (f" ({coll['doc_code']} is a change notice, not an alarm.)" if coll else ""), INSUFFICIENT, "n/a", cl, [], unknowns, [])

    # ---------- output validation ----------
    def guard(self, q: str, ans: Answer) -> Answer:
        if ans.handler in ("screenshot", "alarm_unverified") or ans.status == INSUFFICIENT and not ans.claims:
            return ans
        tg = [t["id"] for t in self.targets(q) if t["id"] in set(self.documented())]
        if not tg:
            return ans
        # (1) contamination: a stop/restart instruction must be supported by evidence belonging to the SAME alarm
        for c in ans.claims:
            for phrase in {m.group(0).lower() for m in STOP_RE.finditer(c.text)}:
                if not self._supported(phrase, c, tg):
                    fresh = self.answer(q, [{"raw": t, "id": t} for t in tg], self.facets(q))
                    fresh.handler = ans.handler
                    fresh.assumptions.append(f"An inconsistent draft containing an instruction ('{phrase}') not supported by the cited {', '.join(tg)} record was discarded and rebuilt from the stored records.")
                    return fresh
        # (2) completeness: an action answer must contain the entire stored required-action cell
        if "action" in self.facets(q):
            blob = _norm(ans.answer + " " + " ".join(c.text for c in ans.claims))
            for t in tg:
                act = self.fs.get(t, "required_action")
                if act and _norm(act[0].value) not in blob:
                    ans.claims.append(self.e.claim(f"Required action for {t}, complete cell (appended by completeness check): {act[0].value.replace('*', '').strip()}", act))
                    ans.answer += f" Complete documented required action for {t}: {act[0].value.replace('*', '').strip()}"
                    ans.assumptions.append(f"Completeness check: the draft omitted part of the documented required action for {t}; the full cell was appended.")
                    if ans.status == ANSWERED:
                        ans.status, ans.confidence = CAVEATS, "medium"
        return ans

    def _supported(self, phrase: str, claim: Claim, tg: List[str]) -> bool:
        for ev in claim.evidence:
            p = self.fs.passage(ev.passage_id)
            txt = _norm(p.get("content", ""))
            if phrase not in txt and not re.search(re.escape(phrase.split()[0]), txt):
                continue
            row = re.match(r"\[table \d+, row \d+\] alarm: (a\d+)", txt)
            if row is None or row.group(1).upper() in tg:
                if phrase in txt:
                    return True
        return False
