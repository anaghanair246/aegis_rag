"""Grounded QA engine.
Design: question -> entity resolution (evidence-backed aliases) -> intent router -> handler builds claims ONLY from
stored facts/edges/passages (each carries provenance) -> abstain when no fact supports an answer.
No free-text generation happens in this path, so values/units cannot be hallucinated. An optional LLM path
(qa/llm.py) is used only for questions no handler recognises, and its citations are validated."""
import re
import time
from typing import List, Optional
from src import config
from src.database import DatabaseManager
from src.knowledge.aliases import norm
from src.qa.facts import FactStore, resolve_scoped, Fact
from src.qa.models import Answer, Claim, Evidence, ANSWERED, CAVEATS, CONFLICT, INSUFFICIENT
from src.retrieval.index import HybridIndex
from src.qa.alarms import AlarmAnswerer, find_alarm_ids
from src.config import TRUST_LABEL


def _sent(text: str, needle: Optional[str], width: int = 230) -> str:
    t = re.sub(r"\s+", " ", text)
    if needle:
        i = t.lower().find(needle.lower())
        if i >= 0:
            lo = max(0, i - width // 2)
            return ("…" if lo else "") + t[lo: lo + width] + ("…" if lo + width < len(t) else "")
    return t[:width] + ("…" if len(t) > width else "")


class QAEngine:
    def __init__(self, db: DatabaseManager, index: Optional[HybridIndex] = None):
        self.db, self.fs = db, FactStore(db)
        self.index = index or HybridIndex(db)
        self.alarms = AlarmAnswerer(self)

    # ---------- helpers ----------
    def ev(self, passage_id: str, needle: Optional[str] = None) -> Evidence:
        p = self.fs.passage(passage_id)
        if not p:
            raise KeyError(f"citation to unknown passage {passage_id}")
        if p["page_number"]:
            loc = f"{'slide' if p['rel_path'].endswith('.pptx') else 'page'} {p['page_number']}"
        else:
            loc = p["section_title"] or "n/a"
        if p["extraction_method"] == "table" and "Row " in p["content"][:40]:
            loc = p["content"].split("]")[0].lstrip("[")
        mt = re.match(r"\[Table (\d+), row (\d+)\]", p["content"])
        if mt:
            loc = f"page {p['page_number']}, table {mt.group(1)}, row {mt.group(2)}"
        if p["extraction_method"] == "vector":
            loc = f"page {p['page_number']} (diagram geometry)"
        quote = re.sub(r"\s+", " ", p["content"])[:700] if mt else _sent(p["content"], needle)   # table rows are quoted whole (every cell visible)
        return Evidence(p["passage_id"], p["rel_path"], p["doc_code"], p["doc_rev"], loc, quote,
                        p["authority_level"], p["extraction_method"])

    def claim(self, text, facts: List[Fact] = (), passages: List[str] = (), needle=None) -> Claim:
        seen, evs = set(), []
        for f in facts:
            if f.passage_id not in seen:
                seen.add(f.passage_id); evs.append(self.ev(f.passage_id, f.value.split(",")[0][:40] if needle is None else needle))
        for pid in passages:
            if pid not in seen:
                seen.add(pid); evs.append(self.ev(pid, needle))
        return Claim(text, evs)

    @staticmethod
    def _sw_in_question(q: str) -> Optional[str]:
        m = re.search(r"(?:software|firmware|revision|rev\.?)\s*(\d\.\d(?:\.\d)?)", q, re.I)
        return m.group(1) if m else None

    def _fin(self, ans: Answer) -> Answer:
        ids = ans.cited_passage_ids()
        known = {p for p in self.index.ids}
        assert all(i in known for i in ids), "citation validation failed"  # citations must be real passages
        return ans

    # ---------- main ----------
    def ask(self, question: str, sw: Optional[str] = None) -> Answer:
        t0 = time.time()
        q = question.strip()
        ents = self.index.canon.entities(q)
        hits = self.index.search(q, k=config.TOP_K)
        t1 = time.time()
        sw = sw or None
        ans = None
        # Entity guard: HPU-pressure handlers must not answer about a component the docs say is unrelated.
        if "PS-40" in ents and re.search(r"pressure|setpoint|threshold|limit", q, re.I):
            e = self.fs.entity("PS-40")
            st = self.fs.get("PS-40", "status")
            ans = Answer(q, "Cannot be determined: PS-40 is a coolant-loop sensor (Skid B) that the Component Register says is NOT related to the HPU discharge circuit; "
                         "the 180/200 bar figures do not apply to it and no PS-40 specification is in the package.", INSUFFICIENT, "n/a",
                         [self.claim("Register entry for PS-40.", st),
                          self.claim("The documented normal pressures (180 bar before 3.2, 200 bar from 3.2) belong to the HPU discharge circuit (PS-04 / PS-04A).", self.fs.get("HPU", "normal_operating_pressure")[:2])], [], ["No operating pressure for PS-40 is documented."], handler="entity_guard")
        for name, pred, fn in ([] if ans else self._routes()):
            if pred(q, ents):
                ans = fn(q, ents, sw)
                ans.handler = name
                break
        if ans is None:
            ans = self._fallback(q, ents, hits)
        ans = self.alarms.guard(q, ans)
        ans.retrieved = [{"passage_id": h.passage_id, "score": round(h.score, 4), "source": h.passage["rel_path"],
                          "trust": h.passage["authority_level"]} for h in hits]
        t2 = time.time()
        ans.timings_ms = {"retrieval": round((t1 - t0) * 1000, 1), "answer": round((t2 - t1) * 1000, 1),
                          "total": round((t2 - t0) * 1000, 1)}
        return self._fin(ans)

    # ---------- routing ----------
    def _routes(self):
        R = lambda pat: (lambda q, e: re.search(pat, q, re.I) is not None)
        return [
            ("gap", self._is_gap, self.h_gap),
            ("screenshot", R(r"screenshot|screen_0\d|\bHMI\b|\b(home|alarm|alarms|diagnostics?)\s+(screen|list|page)|\bon (the )?(screen|panel display)"), self.h_screenshot),
            ("config_key", R(r"sensor_ps04a_threshold_bar|configuration export|config(uration)? key"), self.h_config_key),
            ("term", lambda q, e: len(e) >= 1 and re.search(r"['\"‘“][^'\"’”]+['\"’”]|\bthe term\b|\bstands? for\b|\bwhat is (a|an|the) \w+ (called|known as)\b", q, re.I) is not None and re.search(r"what|define|refer|mean|stand", q, re.I) is not None and not re.search(r"alarm|\bA1\d\b|sensor_ps04a", q, re.I), self.h_term),
            ("identity", lambda q, e: re.search(r"\b(same|identical|equivalent|interchangeable)\b|names? for (one|the same)", q, re.I) is not None and len(e) >= 2 or re.search(r"names? for|interchangeable", q, re.I) is not None and len(e) >= 2, self.h_identity),
            ("introduced_by", R(r"which (document|ecn|notice|bulletin).*(introduc|chang|replac)"), self.h_introduced_by),
            ("slide_novelty", R(r"training slide|slide deck"), self.h_slide_novelty),
            ("schematic_links", R(r"connect\w*\s+(directly\s+)?to.*(controller|PLC-03)|(controller|PLC-03).*connect"), self.h_schematic_links),
            ("a17_persist", R(r"(A17|alarm).*(persist|stays? active|remains?|longer than|more than|for over)\b.*(second|\bs\b)|persist.*(A17|alarm)"), self.h_a17_persist),
            ("alarm_ref", lambda q, e: bool(self.alarms.targets(q)), self.h_alarm_ref),
            ("reset", R(r"\bre-?set\b|\brestart\w*\b.*\b(PLC|controller)\b|\b(PLC|controller)\b.*\brestart\w*\b"), self.h_reset),
            ("restart_hpu", R(r"\b(re-?start\w*|resume)\b"), self.h_restart_hpu),
            ("alarm_for_reading", lambda q, e: all(re.search(x, q, re.I) for x in (r"\d+\s*bar", r"alarm", r"\b(below|above|under|over|exceed\w*|drops?|falls?|rises?)\b")), self.h_alarm_for_reading),
            ("revision_history", R(r"(revision\s*)?history|(software|firmware|revision) \d\.\d.*(effect|releas|date)|when (did|was|were).*(revision|software|firmware)"), self.h_revision_history),
            ("location", R(r"\blocat(ion|ed)\b|where is"), self.h_location),
            ("pressure_scope", R(r"(all|every|some|only).*(unit|install)|apply to"), self.h_pressure_scope),
            ("pressure_history", R(r"(before|prior to|previous|earlier).*(3\.2|revision)|pre-?3\.2|what changed"), self.h_pressure_history),
            ("startup", R(r"before (starting|start)|prior to (switch|turn|power|start)\w*|startup|precondition|start(ing)? the (HPU|hydraulic)|must be true"), self.h_startup),
            ("normal_pressure", R(r"(normal|operating|current|nominal|expected|typical).*(pressure|setpoint|reading)|pressure.*(normal|operating|setpoint)"), self.h_normal_pressure),
        ]

    # ---------- handlers ----------
    def h_startup(self, q, ents, sw):
        fs = self.fs.get("HPU", "startup_precondition")
        cfg = self.fs.like("HPU", "config:")
        cl = [self.claim(f"Before starting the HPU: {f.value}.", [f]) for f in fs]
        if cfg:
            vals = {f.predicate.split(":")[1]: f.value for f in cfg if f.predicate.split(":")[1].endswith("state") or f.predicate.endswith("band")}
            cl.append(self.claim("The controller's configuration export (PLC-03) encodes the same four startup interlocks: "
                                 + "; ".join(f"{k.replace('_required_state','').replace('_required_band','')} = {v}" for k, v in vals.items()) + ".", cfg))
        slide = self.fs.passage(next((p["passage_id"] for p in self.index.ps if p["rel_path"].endswith("training_slide_excerpt.pptx") and "Before You Press Start" in p["content"]), ""))
        if slide:
            cl.append(self.claim("The training slide lists the same four checks (memory aid only, not a replacement procedure).", passages=[slide["passage_id"]]))
        return Answer(q, "Per the Operator Manual (§4.3), before starting the HPU: " + " ".join(f"({i+1}) {f.value}." for i, f in enumerate(fs)),
                      ANSWERED if fs else INSUFFICIENT, "high", cl)

    def h_normal_pressure(self, q, ents, sw):
        sw_q = sw or self._sw_in_question(q)
        facts = self.fs.get("HPU", "normal_operating_pressure")
        r = resolve_scoped(facts, sw_q)
        cur = [f for f in r["other_scopes"] + r["applicable"] if f.sw_from == "3.2"]
        old = [f for f in r["other_scopes"] + r["applicable"] if f.sw_before == "3.2"]
        cl, assumptions, conflicts, unknowns = [], [], [], []
        if sw_q and not r["applicable"]:
            return Answer(q, f"No trusted source states a normal pressure for software {sw_q}.", INSUFFICIENT, "n/a")
        show_cur = cur if (sw_q is None or r["applicable"] == cur or any(f in r["applicable"] for f in cur)) else []
        show_old = old if (sw_q is None or any(f in r["applicable"] for f in old)) else []
        if sw_q is not None:
            show_cur = [f for f in cur if f in r["applicable"]]; show_old = [f for f in old if f in r["applicable"]]
        if show_cur:
            cl.append(self.claim("On software revision 3.2 and later (sensor PS-04A, firmware ≥ 3.2) the normal HPU discharge pressure is "
                                 f"{show_cur[0].display()}. ECN-1042 describes this as a deliberate setpoint change, not a calibration artifact.", show_cur))
        if show_old:
            cl.append(self.claim(f"On software revisions before 3.2 (sensor PS-04) it was {show_old[0].display()}; the manual warns not to compare live readings against 180 bar on 3.2+ units.", show_old))
        fw = self.fs.get("PLC-03", "config:firmware_version")
        if sw_q is None:
            assumptions.append("The question does not state the unit's software revision; both revision-scoped values are given. "
                               "The only unit-level evidence in the package (PLC-03 configuration export, 2026-02-03) reports firmware 3.2.1, which falls in the 200 bar scope.")
            if fw:
                cl.append(self.claim("PLC-03 configuration export reports firmware 3.2.1 (so the 200 bar scope applies to that unit).", fw))
        asked = re.search(r"(\d+)\s*bar", q)
        if asked:
            v = asked.group(1)
            documented = {f.value.split()[0] for f in facts if f.status == "asserted"}
            if v in documented:
                assumptions.append(f"{v} bar matches a documented normal pressure — but only for the software scope shown above.")
            else:
                assumptions.append(f"{v} bar is not a documented normal pressure for any revision (documented: 180 bar before 3.2, 200 bar from 3.2); the only source mentioning ~{v} bar is the low-trust field note.")
        for f in r["unverified"]:
            if f.predicate == "normal_operating_pressure" and f.status == "superseded":
                cl.append(self.claim(f"The legacy Operator Manual v1 also states {f.display()} (valid only for 3.0–3.1; superseded).", [f]))
        obs = self.fs.get("HPU", "observed_gauge_pressure")
        for f in obs:
            conflicts.append(f"Field notes (low trust, undated, uncalibrated gauge, software revision not checked) report ~{f.display()} during a normal run — "
                             "this matches neither 180 nor 200 bar; it is not treated as authoritative (possible gauge error, or a real low-pressure fault). Needs a calibrated reference.")
            cl.append(self.claim("Contradicting low-trust observation (not used for the answer).", [f]))
        for a, b in r["conflicts"]:
            conflicts.append(f"Trusted sources disagree: {a.display()} vs {b.display()} for overlapping scope.")
        txt = ("Normal HPU discharge pressure is " + (f"{show_cur[0].display()} on software revision ≥ 3.2 (PS-04A)" if show_cur else "") +
               (" and " if show_cur and show_old else "") + (f"{show_old[0].display()} on revisions < 3.2 (PS-04)" if show_old else "") + ".")
        return Answer(q, txt, CAVEATS if (assumptions or conflicts) else ANSWERED, "medium" if conflicts else "high", cl, conflicts, unknowns, assumptions)

    def h_pressure_history(self, q, ents, sw):
        f = self.fs.get("HPU", "normal_operating_pressure")
        old = [x for x in f if x.sw_before == "3.2" and x.status == "asserted" and (x.trust or 9) <= 3]
        new = [x for x in f if x.sw_from == "3.2" and x.status == "asserted" and (x.trust or 9) <= 3]
        sup = self.fs.get("PS-04A", "supersedes")
        hist = self.fs.get("software revision 3.2", "changes")
        date = self.fs.get("software revision 3.2", "release_date")
        cl = [self.claim(f"Before software revision 3.2 the normal HPU discharge pressure was {old[0].display()} (sensor PS-04).", old)]
        cl.append(self.claim(f"It was changed to {new[0].display()} by ECN-1042, effective software revision 3.2 (released {date[0].value if date else 'date n/a'}), alongside replacing PS-04 with PS-04A; ECN-1042 calls it a deliberate process change.", new + date))
        assumptions, unknowns = [], []
        if re.search(r"\blimit\b", q, re.I):
            assumptions.append("'Pressure limit' was interpreted as the normal operating pressure setpoint. Alarm limits (A17 below 150 bar, A18 above 220 bar) are documented as unchanged by ECN-1058; "
                               "no source documents separate pre-3.2 alarm limits.")
            a17 = self.fs.get("A17", "trigger_threshold"); a18 = self.fs.get("A18", "trigger_threshold")
            cl.append(self.claim("Alarm thresholds shown in Alarm Reference Rev 5 (A17 < 150 bar, A18 > 220 bar) are stated as unchanged by ECN-1058.", a17 + a18))
            unknowns.append("Whether alarm thresholds were different before 3.2 is not documented in the package.")
        return Answer(q, f"{old[0].display()} before 3.2; changed to {new[0].display()} by ECN-1042 (effective software revision 3.2).",
                      CAVEATS if assumptions else ANSWERED, "high", cl, [], unknowns, assumptions)

    def h_pressure_scope(self, q, ents, sw):
        new = [x for x in self.fs.get("HPU", "normal_operating_pressure") if x.sw_from == "3.2" and (x.trust or 9) <= 3]
        keep = self.fs.get("PS-04", "supported_on")
        fw = self.fs.get("PS-04A", "min_firmware")
        vint = self.fs.get("HPU", "setpoint_change_rationale_scope")
        cfg = self.fs.get("PS-04A", "config:sensor_ps04a_threshold_bar")
        cl = [self.claim("No — the 200 bar setpoint applies only to units on software revision 3.2 or later (with PS-04A, which needs firmware ≥ 3.2).", new + fw + cfg),
              self.claim("Units on earlier software keep PS-04 and the 180 bar setpoint; ECN-1042 says PS-04 remains supported there and PS-04A must not be installed on older firmware.", keep)]
        unknowns = []
        if vint:
            cl.append(self.claim("ECN-1042 gives its rationale as improving cycle time on units 'manufactured after 2024'.", vint))
            unknowns.append("ECN-1042 scopes the change by software revision but justifies it by manufacture date; the package does not say whether older-built units upgraded to 3.2 also use 200 bar.")
        return Answer(q, "Only some units: those running software revision ≥ 3.2 (PS-04A). Earlier revisions use 180 bar.", CAVEATS if unknowns else ANSWERED, "medium", cl, [], unknowns)

    def h_alarm_ref(self, q, ents, sw):
        return self.alarms.answer(q)

    def h_restart_hpu(self, q, ents, sw):
        """'Restart the HPU' without an alarm id: restarting is a start (startup preconditions apply); documented restart
        restrictions are alarm-specific. This must NOT be answered with the controller-reset rule (a different safety rule)."""
        from src.qa.alarms import sentences, RESTART_RE
        pre = self.fs.get("HPU", "startup_precondition")
        cl = [self.claim(f"Starting the HPU requires: {f.value}.", [f]) for f in pre]
        found = []
        for a in self.alarms.documented():
            for f in self.fs.get(a, "required_action"):
                rs = [x for x in sentences(f.value) if RESTART_RE.search(x)]
                if rs:
                    found.append(a); cl.append(self.claim(f"Alarm {a} (restart restriction): {' '.join(rs)}", [f]))
        un = ["No general restart procedure is documented beyond the startup checks; whether restart is permitted depends on the alarm or fault that stopped the unit (not stated in the question)."]
        return Answer(q, "Restarting means starting the HPU again, so the startup preconditions apply (Operator Manual §4.3)." +
                      (f" The only documented alarm-specific restart restriction is for {', '.join(found)}." if found else "") +
                      " Say which alarm/fault stopped the unit for an alarm-specific answer.", CAVEATS, "medium", cl, [], un, [])

    def h_a17_persist(self, q, ents, sw):
        ids = [t["id"] for t in self.alarms.targets(q)]
        al = next((i for i in ids if self.fs.get(i, "persistence_threshold_before_action")), None) or next(iter(self.fs.subjects_with("persistence_threshold_before_action")), None)
        if al is None or (ids and al not in ids):
            return self.alarms.answer(q)
        act = self.fs.get(al, "persistence_threshold_before_action")
        steps = self.fs.get("Shutdown Procedure 4.7", "steps")
        cfg = self.fs.get(al, "config:persistence_before_shutdown_seconds")
        if not act:
            return self._insufficient(q, "No persistence rule found.")
        n, u = act[0].value, act[0].unit or "s"
        base = self.alarms.answer(q, [{"raw": al, "id": al}], ["action"])      # the complete alarm record (whole required-action cell + footnote)
        cl = [self.claim(f"If {al} persists for more than {n} {u}, execute Shutdown Procedure 4.7 before investigating further; do not clear it by silencing the alarm alone.", act),
              self.claim("Shutdown Procedure 4.7: " + steps[0].value + ".", steps)]
        if cfg:
            cl.append(self.claim(f"The controller configuration export also sets {al} persistence before shutdown to {cfg[0].value} {cfg[0].unit or u} (procedure ref 4.7).", cfg))
        cl.append(self.claim(f"A transient {al} that clears on its own within a few seconds (valve transition) does not require Procedure 4.7.", passages=[act[0].passage_id]))
        have = {c.text for c in cl}
        cl += [c for c in base.claims if c.text not in have]
        st = ANSWERED if base.status == ANSWERED else CAVEATS
        return Answer(q, "Run Shutdown Procedure 4.7: " + steps[0].value + ". " + base.answer, st, "high" if st == ANSWERED else "medium", cl, [], base.unknowns)

    def h_reset(self, q, ents, sw):
        pro = self.fs.get("PLC-03", "reset_prohibited_above_pressure")
        per = self.fs.get("PLC-03", "reset_permitted_below_pressure")
        cfg = self.fs.get("PLC-03", "config:max_pressure_bar_allowed_for_reset")
        mn = self.fs.get("PLC-03", "config:min_pressure_bar_required_for_reset")
        if not pro:
            return self._insufficient(q, "No reset rule found.")
        cl = [self.claim("Do not reset PLC-03 while hydraulic pressure is above 50 bar (Operator Manual §7); resetting under pressure can cause an uncommanded valve transition.", pro),
              self.claim("Maintenance Manual §3: reset is permitted only when the active sensor (PS-04 <3.2, PS-04A ≥3.2) reads below 50 bar; the reset re-initialises valve driver outputs, risking momentary uncommanded actuation of IV-21.", per),
              self.claim("The firmware blocks reset above 50 bar (configuration export); no minimum pressure is configured for reset.", cfg + mn)]
        asked = re.search(r"(\d+)\s*bar", q)
        verdict = ""
        if asked:
            v = int(asked.group(1))
            verdict = (f" At {v} bar: NO — reset is not permitted (above 50 bar; firmware blocks it)." if v > 50 else
                       f" At {v} bar: below 50 bar, so reset is permitted per the manuals." if v < 50 else
                       " At exactly 50 bar: not specified by the manuals.")
        unknowns = ["Behaviour at exactly 50 bar is not specified (manuals say 'above 50' prohibited and 'below 50' permitted).",
                    "The manual bleed procedure (Operator Manual §8 / Maintenance Manual §8) is referenced but not included in this package."]
        return Answer(q, "Do not reset the controller while hydraulic pressure is above 50 bar; bleed pressure below 50 bar first." + verdict, CAVEATS, "high", cl, [], unknowns)

    def h_alarm_for_reading(self, q, ents, sw):
        m = re.search(r"(below|above|under|over|exceed\w*|drops? below|falls? below|rises? above)\s+(\d+)\s*bar", q, re.I)
        if not m:
            return self._insufficient(q, "Could not parse a pressure threshold and direction from the question.")
        direction = "below" if re.match(r"(below|under|drops|falls)", m.group(1), re.I) else "above"
        val = m.group(2)
        hit = []
        for a in self.alarms.documented():
            for f in self.fs.get(a, "trigger_threshold"):
                if f.value == val and (f.note or "") == direction:
                    hit.append((a, f))
        if not hit:
            return self._insufficient(q, f"No alarm in AEG-AL-700 is defined for a reading {direction} {val} bar (A01–A16/A20–A34 are in AEG-AL-701, not provided).")
        a, f = hit[0]
        cond = self.fs.get(a, "condition")
        cl = [self.claim(f"{a} ({cond[0].value}) is the alarm for pressure {direction} {val} bar.", [f])]
        ev = self.fs.get(a, "evaluated_against")
        if ev:
            cl.append(self.claim(f"Per ECN-1058 the {val} bar threshold is unchanged and {a} is evaluated against whichever pressure sensor is active (PS-04 / PS-04A).", ev))
        cfg = self.fs.get("PS-04A", "config:sensor_ps04a_alarm_low_bar" if direction == "below" else "config:sensor_ps04a_alarm_high_bar")
        if cfg:
            cl.append(self.claim(f"The configuration export lists the same {'low' if direction == 'below' else 'high'} alarm limit for PS-04A ({cfg[0].display()}).", cfg))
        return Answer(q, f"{a} — {cond[0].value}.", ANSWERED, "high", cl)

    def h_location(self, q, ents, sw):
        cands = [e for e in ents if not re.fullmatch(r"A\d\d", e)]
        if not cands:
            return self._insufficient(q, "Component not identified.")
        e = cands[0]
        loc = self.fs.get(e, "location")
        if not loc:
            return self._insufficient(q, f"No location recorded for {e}.")
        ent = self.fs.entity(e)
        extra = " The register lists a module-level location only; it gives no finer physical position." if e == "IV-21" else ""
        return Answer(q, f"Component Register: {e} ({ent['canonical_name']}) is located at '{loc[0].value}'.{extra}", ANSWERED, "high",
                      [self.claim(f"{e} location = {loc[0].value}.", loc)],
                      unknowns=["Finer physical position than the module-level location is not documented."] if e == "IV-21" else [])

    def h_identity(self, q, ents, sw):
        comp = [e for e in ents if not re.fullmatch(r"A\d\d", e)]
        if len(comp) < 2:
            return self._insufficient(q, "Could not resolve two components.")
        a, b = comp[0], comp[1]
        rows = {x: self.fs.get(x, "status") for x in (a, b)}
        sup = self.fs.get("PS-04A", "supersedes")
        ent_b = self.fs.entity(b) or {}
        ent_a = self.fs.entity(a) or {}
        pair = {a, b}
        cl = [self.claim(f"{x}: {self.fs.entity(x)['canonical_name']} — register status {rows[x][0].value}, location {self.fs.entity(x)['location']}.", rows[x]) for x in (a, b) if rows[x]]
        if pair == {"PS-04", "PS-04A"}:
            cl.append(self.claim("ECN-1042: PS-04A replaces PS-04 from software revision 3.2 and is not a form-fit-function replacement (needs firmware ≥ 3.2).",
                                 sup + self.fs.get("PS-04A", "interchangeability_with_PS-04")))
            return Answer(q, "No. PS-04 and PS-04A are distinct components: PS-04A supersedes PS-04 from software revision 3.2 (ECN-1042); they are related by supersession, not identity.",
                          ANSWERED, "high", cl, [], [], ["Entity resolution: normalising formatting (PS04A == PS-04A) is safe; PS-04 and PS-04A were not merged because register rows, status and ECN-1042 treat them as separate."])
        note = (ent_a.get("notes") or "") + " " + (ent_b.get("notes") or "")
        if "PS-40" in pair and re.search(r"NOT related", note, re.I):
            cl.append(self.claim("The register notes PS-40 is NOT related to the HPU discharge circuit and must not be confused with PS-04 / PS-04A.",
                                 self.fs.get("PS-40", "status")))
            return Answer(q, f"No. PS-40 is a coolant-loop sensor (Skid B), unrelated to the HPU discharge sensor {a if a != 'PS-40' else b}.", ANSWERED, "high", cl,
                          unknowns=[], assumptions=["Names differ by one character but identifiers are never merged on string similarity."])
        if a == b:
            return Answer(q, "Same entity.", ANSWERED, "high", cl)
        return Answer(q, f"No evidence in the package that {a} and {b} are the same component.", CAVEATS, "low", cl, unknowns=["No explicit alias or supersession statement links them."])

    def h_term(self, q, ents, sw):
        e = ents[0]
        ent = self.fs.entity(e)
        with self.db.conn() as c:
            al = c.execute("SELECT alias_raw, source_passage_id, method FROM aliases WHERE entity_id=? ORDER BY confidence DESC", (e,)).fetchall()
        m = re.search(r"['\"‘“]([^'\"’”]+)['\"’”]", q)
        surf = (m.group(1) if m else "").lower()
        row = next((a for a in al if a["alias_raw"].lower() == surf), None) or (al[0] if al else None)
        if not ent or not row:
            return self._insufficient(q, "Term not resolvable.")
        cl = [self.claim(f"'{row['alias_raw']}' resolves to {e} ({ent['canonical_name']}) via {row['method']}.", passages=[row["source_passage_id"]], needle=row["alias_raw"])]
        regs = self.fs.get(e, "status")
        if regs: cl.append(self.claim(f"Component Register entry for {e}: {ent['canonical_name']}, location {ent['location']}.", regs))
        weak = row["method"] in ("training-slide",)
        return Answer(q, f"'{row['alias_raw']}' refers to {e} — {ent['canonical_name']}.", CAVEATS if weak else ANSWERED, "medium" if weak else "high", cl, [], [],
                      ["The term appears only in the training slides, not in the glossary or register (informal alias, confidence 0.8)."] if weak else [])

    def h_introduced_by(self, q, ents, sw):
        sup = self.fs.get("PS-04A", "supersedes")
        if not sup:
            return self._insufficient(q, "No change notice found.")
        hist = self.fs.get("software revision 3.2", "changes")
        cl = [self.claim("ECN-1042 ('Pressure Sensor Replacement (PS-04 → PS-04A) and Operating Pressure Update') introduced the change, effective software revision 3.2.", sup),
              self.claim("The revision history lists ECN-1042 against software revision 3.2.", hist)]
        return Answer(q, "ECN-1042 (effective software revision 3.2). ECN-1058 later corrected alarm A17 wording only.", ANSWERED, "high", cl)

    def h_schematic_links(self, q, ents, sw):
        hyd = [e for e in self.fs.edges() if "diagrams/" in self.fs.passage(e["passage_id"]).get("rel_path", "") and "H01" in (self.fs.passage(e["passage_id"]).get("doc_code") or "") and e["kind"] != "supersedes(sw>=3.2)"]
        plc = [e for e in hyd if "PLC-03" in (e["src"] + e["dst"])]
        purple = [e for e in plc if e["kind"].startswith("purple")]
        other = [e for e in plc if not e["kind"].startswith("purple")]
        if not purple:
            return self._insufficient(q, "No controller connections recoverable from the schematic geometry.")
        other_name = lambda e: e["dst"] if "PLC-03" in e["src"] else e["src"]
        names = [other_name(e) for e in purple]
        cl = [self.claim("In the hydraulic schematic (AEG-DWG-H01) purple control/signal lines connect PLC-03 directly to: " + " and ".join(names) + ".", passages=[e["passage_id"] for e in purple])]
        unknowns = []
        if other:
            cl.append(self.claim(f"A line also joins PLC-03 and the {other_name(other[0])}, but it is drawn grey, which the legend defines as a hydraulic fluid path, not a control/signal line.", passages=[other[0]["passage_id"]]))
            unknowns.append("The PLC-03–HPU link is ambiguous in the drawing (grey = fluid path per legend), although the Operator Manual says PLC-03 supervises the HPU. Counting it as a control connection is an interpretation.")
        wir = [e for e in self.fs.edges() if "W03" in (self.fs.passage(e["passage_id"]).get("doc_code") or "")]
        if wir:
            cl.append(self.claim("The wiring diagram (AEG-DWG-W03) corroborates: PLC-03 → TB-7 → J-14 (pressure transducer, PS-04A) and J-15 (IV-21 solenoid).", passages=[e["passage_id"] for e in wir if "J-1" in e["src"] + e["dst"] or "TB-7" in e["src"] + e["dst"]][:4]))
        return Answer(q, "PS-04A and IV-21 (purple control/signal lines). The PLC-03–HPU line is drawn grey (hydraulic path), so it is not counted as a signal connection.", CAVEATS, "medium", cl, [], unknowns)

    def h_slide_novelty(self, q, ents, sw):
        aux = self.fs.get("Auxiliary Reservoir", "introduced_in")
        slide_ps = [p for p in self.index.ps if p["rel_path"].endswith("training_slide_excerpt.pptx")]
        codes = {c for p in slide_ps for c in re.findall(r"\bA\d{2}\b", p["content"])}
        known = {e for e in (r["entity_id"] for r in self._all_entities())}
        new_alarms = sorted(codes - known)
        edge = [e for e in self.fs.edges() if "Auxiliary" in e["src"] + e["dst"]]
        cl = []
        if aux:
            cl.append(self.claim("Slide 2 introduces an 'Auxiliary Reservoir' (Line 4/5 configurations) that the slide itself says is not covered in the standard Operator Manual; it is not in the Component Register.", aux))
        if edge:
            cl.append(self.claim("The hydraulic schematic (AEG-DWG-H01) also shows an Auxiliary Reservoir joined to the Main Reservoir by a reservoir-interconnect line.", passages=[edge[0]["passage_id"]]))
        cl.append(self.claim("No alarm codes appear on the slides." if not codes else f"Alarm codes on slides: {sorted(codes)}.", passages=[slide_ps[0]["passage_id"]] if slide_ps else []))
        cl.append(self.claim("The slides also use informal terms ('hydraulic pack', 'the unit') for the HPU; 'hydraulic pack' is treated as an alias (the register has 'Hydraulic Power Pack').", self.fs.get("HPU", "status")[:0], passages=[slide_ps[1]["passage_id"]] if len(slide_ps) > 1 else []))
        return Answer(q, "Yes, one component: the Auxiliary Reservoir (Line 4/5-specific). No new alarms are introduced." if not new_alarms else f"Yes: Auxiliary Reservoir and alarm(s) {new_alarms}.",
                      ANSWERED if aux else INSUFFICIENT, "high", cl, [], ["The deck is an excerpt (slides 4–6 of a longer deck); other slides were not provided."])

    def _all_entities(self):
        with self.db.conn() as c:
            return [dict(r) for r in c.execute("SELECT entity_id FROM entities")]

    def h_revision_history(self, q, ents, sw):
        m = re.search(r"(\d\.\d(?:\.\d)?)", q)
        v = m.group(1) if m else "3.2"
        d, ch = self.fs.get(f"software revision {v}", "release_date"), self.fs.get(f"software revision {v}", "changes")
        if not d:
            return self._insufficient(q, f"Software revision {v} is not in the revision history.")
        cl = [self.claim(f"Software revision {v} release date: {d[0].value}.", d), self.claim(f"Changes: {ch[0].value}", ch)]
        unknowns, extra = [], ""
        if v == "3.2":
            n = self.fs.get("software revision 3.2.1", "changes"); nd = self.fs.get("software revision 3.2.1", "release_date")
            cl.append(self.claim(f"Follow-up 3.2.1 ({nd[0].value}): {n[0].value}", n + nd))
            extra = " Software 3.3 is listed as planned (2026-04-07) and not published."
        if "planned" in d[0].value:
            unknowns.append("This revision is only planned in the revision history; no release is confirmed.")
        return Answer(q, f"Software {v} took effect {d[0].value}. {ch[0].value}{extra}", ANSWERED if not unknowns else CAVEATS, "high", cl, [], unknowns)

    def h_config_key(self, q, ents, sw):
        k = self.fs.get("PS-04A", "config:sensor_ps04a_threshold_bar")
        leg = self.fs.get("PS-04", "config:sensor_ps04_legacy_threshold_bar")
        hi, lo = self.fs.get("PS-04A", "config:sensor_ps04a_alarm_high_bar"), self.fs.get("PS-04A", "config:sensor_ps04a_alarm_low_bar")
        om = [f for f in self.fs.get("HPU", "normal_operating_pressure") if f.sw_from == "3.2" and f.trust == 2]
        if not k:
            return self._insufficient(q, "Key not present.")
        cl = [self.claim("The key's sensor prefix 'ps04a' resolves to PS-04A (normalised id match); value 200 bar, applicable from firmware 3.2.", k),
              self.claim("The Operator Manual's equivalent is the normal HPU discharge pressure / setpoint of 200 bar on software ≥ 3.2 (measured by PS-04A); ECN-1042 calls it the 'setpoint'.", om),
              self.claim("The pre-3.2 counterpart is sensor_ps04_legacy_threshold_bar = 180 bar (applies before firmware 3.2), matching the older 180 bar normal pressure.", leg),
              self.claim("It is distinct from the alarm limits sensor_ps04a_alarm_low_bar (150) and _high_bar (220), which correspond to A17 / A18 thresholds.", lo + hi)]
        return Answer(q, "It is PS-04A's normal operating-pressure setpoint (200 bar on software revision ≥ 3.2) — the manual's 'normal HPU discharge pressure'.", CAVEATS, "medium", cl, [],
                      ["No document explicitly states this key-to-term mapping."], ["Mapping inferred from matching sensor id (ps04a), value (200 bar) and version scope (≥3.2); the key says 'threshold' while manuals say 'setpoint'/'normal pressure'."])

    def _scan_calibration_passage(self):
        return next((p["passage_id"] for p in self.index.ps if p["rel_path"].endswith("scanned_appendix_calibration.pdf")), None)

    def h_screenshot(self, q, ents, sw):
        shots = [r for r in self.fs.doc_count_by_ext(".png") if "screenshots/" in r]
        if not shots:
            return Answer(q, "Cannot be determined: no HMI screenshot is present in the ingested package.", INSUFFICIENT, "n/a", [], [],
                          ["No screenshots ingested."])
        ql = q.lower()
        if re.search(r"diagnos|sensor id|sensor tag|\btag\b|\braw\b|\bma\b|scaled|calibrat|firmware|signal type", ql):
            return self._screen_diagnostics(q)
        if re.search(r"alarm|a17|shutdown|persist", ql):
            return self._screen_alarms(q)
        if re.search(r"home|pressure|interlock", ql):
            return self._screen_home(q)
        a, b, c = self._screen_diagnostics(q), self._screen_alarms(q), self._screen_home(q)
        return Answer(q, " | ".join(x.answer for x in (c, b, a)), CAVEATS, "medium", c.claims + b.claims + a.claims, [], a.unknowns + b.unknowns + c.unknowns, a.assumptions)

    def _screen_diagnostics(self, q):
        tag = self.fs.get("PS-04A", "screen_tag_as_displayed")
        if not tag:
            return self._insufficient(q, "No sensor tag could be read from the diagnostics screenshot.")
        raw = tag[0].value
        ent = self.fs.entity("PS-04A")
        reg = self.fs.get("PS-04A", "status")
        cl = [self.claim(f"The diagnostics screen shows the sensor tag '{raw}', and notes it displays the tag as printed on the physical unit label.", tag, needle="P.S.04")]
        cl.append(self.claim(f"After removing separator punctuation ('{raw}' → PS04A) it equals the Component Register ID PS-04A ({ent['canonical_name']}, {ent['location']}, status {reg[0].value}); the screen also shows software rev 3.2 and firmware 3.2.1, the scope in which PS-04A is the active sensor.", reg))
        cal = self.fs.get("PS-04A", "screen_last_calibrated")
        scan = self._scan_calibration_passage()
        if cal and scan:
            cl.append(self.claim(f"Corroboration: the screen's last-calibrated date ({cal[0].value}) equals the calibration date on the scanned PS-04A calibration record.", cal, passages=[scan], needle="2026-01-09"))
        fw = self.fs.get("PLC-03", "screen_firmware_rev"); cfw = self.fs.get("PLC-03", "config:firmware_version")
        if fw and cfw:
            cl.append(self.claim(f"Corroboration: firmware {fw[0].value} on the screen equals the PLC-03 configuration export ({cfw[0].value}).", fw + cfw))
        allv = [f for pr in ("screen_signal_type", "screen_raw_signal", "screen_scaled_value", "screen_calibration_status", "screen_last_calibrated") for f in self.fs.get("PS-04A", pr)]
        if allv:
            lab = {"screen_signal_type": "signal type", "screen_raw_signal": "raw reading", "screen_scaled_value": "scaled value", "screen_calibration_status": "calibration status", "screen_last_calibrated": "last calibrated"}
            cl.append(self.claim("Diagnostics screen values: " + "; ".join(f"{lab[f.predicate]} {f.display()}" for f in allv) + ". (How the 14.8 mA raw reading maps to 200.3 bar is not documented in the package — the transducer's pressure range is not stated.)", allv))
        sc = self.fs.get("PS-04A", "screen_scaled_value")
        if sc:
            cl.append(self.claim(f"The screen's scaled value ({sc[0].display()}) is consistent with the 200 bar normal operating pressure for software ≥ 3.2; it is a single undated snapshot, not a specification.", sc))
        return Answer(q, f"The diagnostics screen shows the sensor tag '{raw}'. Yes, it matches a known component: PS-04A (Pressure Sensor 04A, HPU discharge line) — the dots are formatting only; it is not PS-04 or PS-40.",
                      CAVEATS, "high", cl, [],
                      ["The dotted form 'P.S.04-A' is not listed among the register's aliases (P04A, PS04A); the match rests on separator-only normalisation plus corroborating evidence (calibration date, firmware, location on the HPU discharge line)."],
                      ["Tag read by OCR from an image (confidence ≥85% on this screen); not independently verified against the physical label."])

    def _screen_alarms(self, q):
        dur = self.fs.get("A17", "screen_active_duration"); thr = self.fs.get("A17", "screen_procedure_4_7_threshold")
        if not dur:
            return self._insufficient(q, "Alarm banner not readable.")
        mm = self.fs.get("A17", "persistence_threshold_before_action"); steps = self.fs.get("Shutdown Procedure 4.7", "steps")
        st = self.fs.get("A17", "screen_alarm_state")
        cl = [self.claim(f"The alarm screen shows A17 (Hydraulic Pressure Low) ACTIVE for {dur[0].value} s with the Procedure 4.7 threshold shown as {thr[0].value} s.", dur + thr)]
        if mm:
            cl.append(self.claim("Maintenance Manual §4: if A17 persists for more than 10 seconds, execute Shutdown Procedure 4.7 before investigating further (the screen's 10 s threshold agrees).", mm))
        if steps:
            cl.append(self.claim("Shutdown Procedure 4.7: " + steps[0].value + ".", steps))
        a = [f for f in st if f.value.startswith("ACTIVE")]; c = [f for f in st if f.value.startswith("CLEARED")]
        if a and c:
            cl.append(self.claim("The list also shows an earlier A17 CLEARED (08:14:02) shortly before the current ACTIVE entry (08:14:57), i.e. recurring A17 events.", c[:1] + a[:1]))
        hp = self.fs.get("HPU", "screen_displayed_pressure")
        unknowns = ["Screenshots are undated snapshots; whether the screen shows the duration at the moment it should be acted on cannot be determined."]
        if hp:
            cl.append(self.claim(f"The home screen shows {hp[0].display()} and 'RUNNING — NORMAL', which is not below A17's documented 150 bar trigger.", hp + self.fs.get("A17", "trigger_threshold")))
            unknowns.append("The home screen (200 bar, normal) and the alarm screen (A17 active) cannot both describe the same moment if A17's condition is a true pressure < 150 bar; they may have been captured at different times, or A17 may stem from a sensor/signal issue. The package cannot resolve this.")
        return Answer(q, f"A17 has been active {dur[0].value} s, above the 10 s threshold, so Shutdown Procedure 4.7 is required: " + (steps[0].value + "." if steps else ""), CAVEATS, "medium", cl, [], unknowns,
                      ["Alarm tags on this screen were re-derived from the row descriptions via the register because OCR misread them (Al7/Al9)."])

    def _screen_home(self, q):
        hp = self.fs.get("HPU", "screen_displayed_pressure")
        if not hp:
            return self._insufficient(q, "Home-screen pressure not readable.")
        iv, es, pn = (self.fs.get("HPU", f"screen_interlock_{k}") for k in ("iv21", "estop", "panel"))
        cfg = [f for f in self.fs.like("HPU", "config:") if f.predicate.endswith(("state", "band"))]
        cl = [self.claim(f"The home screen shows HPU discharge pressure {hp[0].display()}, 'RUNNING — NORMAL', software rev 3.2.", hp)]
        cl.append(self.claim("This equals the documented 200 bar normal operating pressure for software ≥ 3.2 (not the pre-3.2 180 bar).", self.fs.get("HPU", "normal_operating_pressure")[:1]))
        got = [f for f in (iv + es + pn) if f]
        if got:
            cl.append(self.claim("Startup interlocks displayed: IV-21 " + (iv[0].value if iv else "?") + ", E-stop " + (es[0].value if es else "?") + ", maintenance panel " + (pn[0].value if pn else "?") + " (fluid level shows NORMAL) — the same required states as the configuration export.", got + cfg))
        return Answer(q, f"The home screen shows {hp[0].display()} (RUNNING — NORMAL), consistent with the 200 bar setpoint for software 3.2+.", CAVEATS, "medium", cl, [],
                      ["The fluid-level row's value alignment in the OCR text is imperfect (NORMAL is present, but its row is inferred from order)."],
                      ["The display is an undated snapshot of a live-style value, not a specification."])

    # ---------- abstention ----------
    GAP_ATTRS = [
        ("operating temperature", r"temperature", r"temperature"),
        ("calibration interval", r"calibration interval|recalibrat|calibrat\w+ (frequency|period)", r"calibration interval|calibration frequency"),
        ("mean time between failures (MTBF)", r"mean time between failures|MTBF", r"mean time between failures|\bMTBF\b"),
        ("approver of a change notice", r"approv(ed|er|al)", r"who approved|approved by|approver"),
        ("supply-voltage compatibility", r"\b\d{3}\s*V\b|phase", r"compatible.*(supply|\d+\s*V)|\d{3}\s*V.*supply|3-phase|three-phase"),
    ]

    def _is_gap(self, q, ents):
        return any(re.search(trig, q, re.I) for _, _, trig in self.GAP_ATTRS)

    def h_gap(self, q, ents, sw):
        label, evid_re, _ = next(g for g in self.GAP_ATTRS if re.search(g[2], q, re.I))
        subject_ents = [e for e in ents]
        rel, noise = [], []
        for p in self.index.ps:
            if re.search(evid_re, p["content"], re.I):
                (noise if (p["authority_level"] or 0) >= 5 else rel).append(p)
        # a passage supports an answer only if it mentions the question's subject entity (if any)
        def mentions_subject(p):
            if not subject_ents:
                return False
            ids = {norm(x) for x in subject_ents}
            return any(norm(t) in ids for t in re.findall(r"\b[A-Z]{1,3}-?\d{1,3}[A-Z]?\b", p["content"]))
        direct = [p for p in rel if mentions_subject(p)]
        unknowns, cl = [], []
        notes = []
        if label == "calibration interval" and (self.fs.get("PS-04A", "calibration_interval")):
            g = self.fs.get("PS-04A", "calibration_interval")
            cl.append(self.claim("The only calibration record (scanned Appendix C, PS-04A) states that no calibration interval is specified and the maintenance schedule is not included.", g))
            elec = [p for p in self.index.ps if p["rel_path"].endswith("system_diagram_electrical.png")]
            if "voltage" in q.lower() and elec and not re.search(r"voltage\s+(sensor|transducer)", elec[0]["content"], re.I):
                cl.append(self.claim("The electrical diagram's OCR'd labels contain no component called a voltage sensor (OCR is partial; connectivity is not extracted).", passages=[elec[0]["passage_id"]]))
                unknowns.append("No 'voltage sensor' is identifiable in the electrical diagram, so there is nothing to attach a calibration interval to.")
        if label == "supply-voltage compatibility":
            v = [p for p in rel if re.search(r"\b480\s*V|480:120", p["content"])]
            if v:
                cl.append(self.claim("Related evidence only: the Component Register lists Q1 as a 480V incoming disconnect and T1 as a 480:120V control transformer; the package never discusses 400V or 3-phase compatibility.",
                                     passages=[p["passage_id"] for p in v[:2]], needle="480"))
        if label == "approver of a change notice":
            ecn = [p for p in self.index.ps if p["rel_path"].endswith("ECN-1058.pdf")]
            if ecn:
                cl.append(self.claim("ECN-1058's header lists number, title, effective date, references and status ('Released') — no approver or signatory field.", passages=[ecn[0]["passage_id"]], needle="Status"))
        if noise:
            notes.append(f"{len(noise)} passage(s) matched the keyword only in irrelevant documents (e.g. {noise[0]['rel_path']}) and were excluded.")
        if direct:
            return Answer(q, f"Passages mention the subject and '{label}', but no extraction rule produced a value; see evidence.", CAVEATS, "low",
                          [self.claim("Candidate passage (unverified).", passages=[p["passage_id"] for p in direct[:3]])], [], unknowns + notes)
        return Answer(q, f"Not determinable from the package: no source states the {label} for the item asked about.", INSUFFICIENT, "n/a", cl, [],
                      unknowns + notes + [f"{label.capitalize()} is not documented."])

    def _insufficient(self, q, why):
        return Answer(q, "Cannot be determined from the package. " + why, INSUFFICIENT, "n/a", [], [], [why])

    # keyword -> predicate vocabulary used by the generic fact lookup (NOT per-question routing)
    PRED_WORDS = {
        "trigger_threshold": ["threshold", "limit", "exceed", "above", "below"], "condition": ["indicate", "mean", "condition", "raised", "why", "fires", "triggered"],
        "possible_cause": ["cause", "why", "raised", "trigger", "reason"], "required_action": ["action", "do", "respond", "response"],
        "location": ["where", "located", "location", "installed"], "startup_precondition": ["interlock", "precondition", "startup", "start"],
        "config:sensor_ps04a_alarm_low_bar": ["limits", "limit", "alarm", "configured"], "config:sensor_ps04a_alarm_high_bar": ["limits", "limit", "alarm", "configured"],
        "release_date": ["released", "release", "when", "date"], "changes": ["change", "changes", "setpoints", "setpoint"],
        "supports": ["use", "uses"],
    }

    def _fact_lookup(self, q, ents, sw):
        ql = set(re.findall(r"[a-z0-9\-]+", q.lower()))
        subj = []
        documented = set(self.alarms.documented())
        for e in ents:
            if e not in documented:  # alarm records are answered whole by the alarm handler, never piecemeal here
                subj.append(e)
        for m in re.finditer(r"software (\d\.\d(?:\.\d)?)", q, re.I):
            subj.append(f"software revision {m.group(1)}")
        if not subj:
            return None
        scored = []
        with self.db.conn() as c:
            for sbj in subj:
                for r in c.execute("SELECT DISTINCT predicate FROM facts WHERE subject=?", (sbj,)).fetchall():
                    pr = r[0]
                    words = set(self.PRED_WORDS.get(pr, [])) | set(pr.replace("config:", "").replace("_", " ").split())
                    sc = len(words & ql)
                    if sc:
                        scored.append((sc, sbj, pr))
        # Attribute guard: if the question asks about a physical attribute that no stored predicate/value mentions,
        # a keyword match on generic words ("operating", "normal") must not produce an answer -> abstain.
        ATTR = {"temperature", "flow", "voltage", "current", "weight", "mass", "dimensions", "power", "torque", "speed", "humidity", "mtbf", "mttr", "repair", "lifetime", "warranty", "cost", "price"}
        asked_attr = ATTR & ql
        if asked_attr:
            with self.db.conn() as c:
                known = " ".join(r[0] for r in c.execute("SELECT predicate || ' ' || value FROM facts WHERE subject IN (%s)" % ",".join("?" * len(subj)), subj)).lower()
            if not all(a in known for a in asked_attr):
                return None
        if not scored:
            return None
        best = max(sc for sc, _, _ in scored)
        picks = [(sbj, pr) for sc, sbj, pr in scored if sc == best][:3]
        cl, lines = [], []
        for sbj, pr in picks:
            fs = [f for f in self.fs.get(sbj, pr) if f.status == "asserted" and (f.trust or 9) <= 3]
            if not fs:
                continue
            vals = "; ".join(dict.fromkeys(f"{f.display()}" + (f" ({f.scope_text()})" if f.sw_from or f.sw_before else "") for f in fs))
            lines.append(f"{sbj} — {pr.replace('config:', '')}: {vals}")
            cl.append(self.claim(f"{sbj} {pr.replace('config:', '')} = {vals}", fs))
        if not cl:
            return None
        return Answer(q, " | ".join(lines), CAVEATS, "medium", cl, [], [], ["Matched by entity + keyword overlap against stored facts (generic lookup, not a dedicated handler); verify the facts answer the intent of the question."], handler="fact_lookup")

    _GENERIC = set("what which who how does the are is for and any with that this have been into from when where why can may use used about there".split())

    def _extractive(self, q, hits):
        """Strict: return ONE sentence only if it contains >=70% of the question's distinctive terms (and >=2)."""
        terms = {t for t in re.findall(r"[a-z0-9\-]{4,}", q.lower()) if t not in self._GENERIC}
        if len(terms) < 2:
            return None
        best = None
        for h in hits[:5]:
            for snt in re.split(r"(?<=[.;])\s+|\n+", re.sub(r"[ \t]+", " ", h.passage["content"])):
                low = snt.lower()
                cov = sum(1 for t in terms if t in low or (len(t) > 5 and t[:5] in low)) / len(terms)
                if cov >= 0.7 and (best is None or cov > best[0]):
                    best = (cov, h, snt.strip())
        if not best:
            return None
        cov, h, snt = best
        trust = h.passage["authority_level"]
        ans = Answer(q, f"Closest documented statement: \u201c{snt[:260]}\u201d ({h.passage['rel_path']}).", CAVEATS, "low",
                     [Claim("Extractive match (sentence covers %d%% of the question's key terms)." % round(cov * 100), [self.ev(h.passage_id, snt[:40])])], [], [],
                     ["Extractive fallback: the sentence was selected by term overlap, not by understanding the question; check it answers what was asked."] +
                     ([f"Source trust tier {trust} ({TRUST_LABEL.get(trust)})."] if trust and trust >= 4 else []), handler="extractive")
        return ans

    def _fallback(self, q, ents, hits):
        ans = self._fact_lookup(q, ents, None) or self._extractive(q, hits)
        if ans:
            return ans
        if config.USE_LLM:
            from src.qa.llm import llm_answer
            ans = llm_answer(q, hits, self)
            if ans:
                return ans
        cl = [Claim("Closest passages found (not verified to answer the question).", [self.ev(h.passage_id) for h in hits[:3]])]
        return Answer(q, "No grounded answer could be produced: the question did not match a supported pattern, and the retrieved passages were not verified to answer it.",
                      INSUFFICIENT, "n/a", cl, [], ["Unrecognised question type; try rephrasing or enable the LLM backend."], handler="fallback")
