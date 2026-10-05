"""Builds entities / aliases / facts / edges from ingested passages. Deterministic, rule-based.
Every fact stores the passage that supports it; rules that fail to match are REPORTED, not skipped silently."""
import json
import re
from collections import Counter
from typing import Dict, List
from src.database import DatabaseManager
from src.knowledge.aliases import norm


def _ws(s: str) -> str:
    return re.sub(r"\s+", " ", s)


class _Ctx:
    def __init__(self, db: DatabaseManager):
        self.db = db
        with db.conn() as c:
            self.docs = {r["rel_path"]: dict(r) for r in c.execute("SELECT * FROM documents")}
            self.passages: Dict[str, List[dict]] = {}
            for r in c.execute("SELECT * FROM passages ORDER BY passage_id"):
                d = dict(r)
                d["metadata"] = json.loads(d["metadata"] or "{}")
                self.passages.setdefault(r["doc_id"], []).append(d)
        self.facts, self.entities, self.aliases, self.edges, self.unmatched = [], {}, [], [], []
        self.integrity: List[str] = []

    def doc(self, suffix):
        for rel, d in self.docs.items():
            if rel.endswith(suffix):
                return d
        return None

    def find(self, suffix, pattern, flags=re.I):
        """first passage in doc matching regex -> (passage, match) or (None, None)"""
        d = self.doc(suffix)
        if not d:
            return None, None
        for p in self.passages.get(d["doc_id"], []):
            m = re.search(pattern, _ws(p["content"]), flags)
            if m:
                return p, m
        return None, None

    def fact(self, p, subject, predicate, value, unit=None, sw_from=None, sw_before=None, status="asserted",
             method="rule", conf=0.95, note=None, trust=None):
        d = next(x for x in self.docs.values() if x["doc_id"] == p["doc_id"])
        self.facts.append((subject, predicate, str(value), unit, sw_from, sw_before, status,
                           trust if trust is not None else d["authority_level"], p["passage_id"], p["doc_id"], method, conf, note))

    def rule(self, name, suffix, pattern, fn, flags=re.I):
        p, m = self.find(suffix, pattern, flags)
        if p is None:
            self.unmatched.append(f"{name} ({suffix})")
            return
        fn(p, m)


def build_knowledge_layer(db: DatabaseManager) -> dict:
    x = _Ctx(db)
    _entities_from_register(x)
    _facts_from_text(x)
    _facts_from_structured(x)
    _facts_from_screens(x)
    _edges(x)
    with db.conn() as c:
        for t in ("facts", "edges", "aliases", "entities"):
            c.execute(f"DELETE FROM {t}")
        for e in x.entities.values():
            c.execute("INSERT OR REPLACE INTO entities VALUES (?,?,?,?,?,?)", e)
        for a in x.aliases:
            c.execute("INSERT OR IGNORE INTO aliases VALUES (?,?,?,?,?,?)", a)
        c.executemany("""INSERT INTO facts (subject,predicate,value,unit,sw_from,sw_before,status,trust,passage_id,doc_id,
                         method,confidence,note) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""", x.facts)
        c.executemany("INSERT INTO edges (src,dst,kind,passage_id,method,confidence) VALUES (?,?,?,?,?,?)", x.edges)
        c.commit()
    return {"entities": len(x.entities), "aliases": len(x.aliases), "facts": len(x.facts), "edges": len(x.edges),
            "rules_unmatched": x.unmatched, "integrity_warnings": x.integrity}


def _footnotes(passages):
    """Footnotes = text lines starting with '* ', continued over following lines until a line ends a sentence and the next starts a new paragraph."""
    out = []
    for p in passages:
        lines = p["content"].split("\n")
        for i, ln in enumerate(lines):
            if ln.startswith("* "):
                buf, j = [ln[2:].strip()], i
                while not (lines[j].rstrip().endswith((".", ")." )) and (j + 1 >= len(lines) or lines[j + 1][:1].isupper())):
                    j += 1
                    if j >= len(lines):
                        break
                    buf.append(lines[j].strip())
                out.append((p, _ws(" ".join(buf))))
    return out


def _add_alias(x, alias, entity, p, method, conf):
    if alias and alias.strip() not in ("—", "-"):
        x.aliases.append((norm(alias), entity, alias.strip(), p["passage_id"] if p else None, method, conf))


def _entities_from_register(x: _Ctx):
    d = x.doc("component_register.xlsx")
    if not d:
        x.unmatched.append("component_register missing"); return
    for p in x.passages[d["doc_id"]]:
        r = p["metadata"].get("row_cells", {})
        eid = r.get("Component ID (as printed)")
        if not eid:
            continue
        x.entities[eid] = (eid, "alarm" if re.fullmatch(r"A\d\d", eid) else "component", r.get("Common Name"),
                           r.get("Location"), r.get("Status"), r.get("Notes"))
        _add_alias(x, eid, eid, p, "register-id", 1.0)
        _add_alias(x, r.get("Common Name"), eid, p, "register-name", 1.0)
        for a in (r.get("Known Aliases") or "").split(";"):
            _add_alias(x, a, eid, p, "register-alias", 1.0)
        x.fact(p, eid, "location", r.get("Location"), method="structured", conf=1.0)
        x.fact(p, eid, "status", r.get("Status"), method="structured", conf=1.0)
    # aliases evidenced by sentences (not in register)
    x.rule("OM alias sentence", "operator_manual.pdf", r"Hydraulic Unit or\s*the HP unit",
           lambda p, m: [_add_alias(x, a, "HPU", p, "manual-sentence", 0.95) for a in ("Hydraulic Unit", "HP unit")])
    x.rule("slide alias", "training_slide_excerpt.pptx", r"hydraulic pack",
           lambda p, m: _add_alias(x, "hydraulic pack", "HPU", p, "training-slide", 0.8))
    x.rule("wiring alias", "wiring_diagram.pdf", r"HPU discharge pressure transducer described elsewhere as (PS-04A)",
           lambda p, m: (_add_alias(x, "PRESSURE XDCR", "PS-04A", p, "wiring-note", 0.9),
                         _add_alias(x, "Connector J-14", "PS-04A", p, "wiring-note", 0.9),
                         x.edges.append(("TB-7", "PS-04A", "wiring_designation_of", p["passage_id"], "rule", 0.9))))
    # config-key aliasing: sensor_ps04a_* -> PS-04A by normalised id inside key name
    d = x.doc("configuration_export.json")
    if d:
        p = next((q for q in x.passages[d["doc_id"]] if q["section_title"] == "sensors"), None)
        if p:
            for k in p["metadata"]["leaves"]:
                m = re.search(r"sensor_(ps\d+[a-z]?)_", k)
                if m:
                    for eid in x.entities:
                        if norm(eid) == m.group(1).upper():
                            _add_alias(x, m.group(1), eid, p, "config-key-normalisation", 0.9)


def _facts_from_text(x: _Ctx):
    OM, MM, AL = "operator_manual.pdf", "maintenance_manual.pdf", "alarm_reference.pdf"
    x.rule("OM normal 200", OM, r"reaches (\d+) bar\. This is the normal operating pressure for software revision 3\.2 and later",
           lambda p, m: x.fact(p, "HPU", "normal_operating_pressure", m.group(1), "bar", sw_from="3.2",
                               note="measured by PS-04A"))
    x.rule("OM normal 180", OM, r"On revisions prior to 3\.2, normal discharge pressure was (\d+) bar, measured by the original (PS-04)",
           lambda p, m: x.fact(p, "HPU", "normal_operating_pressure", m.group(1), "bar", sw_before="3.2",
                               note="measured by PS-04"))
    def startup(p, m):
        for v in ("Hydraulic fluid level is within the normal band on the sight glass",
                  "Isolation valve IV-21 is OPEN", "emergency stop circuit is RESET",
                  "Do not start the Hydraulic Power Unit with the maintenance access panel removed"):
            if v.lower() in _ws(p["content"]).lower():
                x.fact(p, "HPU", "startup_precondition", v.replace("Do not start the Hydraulic Power Unit with the maintenance access panel removed",
                       "Maintenance access panel must be installed (do not start with it removed)"))
    x.rule("OM startup", OM, r"Before starting, verify", startup)
    x.rule("OM reset", OM, r"Do not reset the PLC-03 controller while hydraulic pressure is above (\d+) bar",
           lambda p, m: x.fact(p, "PLC-03", "reset_prohibited_above_pressure", m.group(1), "bar",
                               note="reason: uncommanded valve transition; bleed below 50 bar first (OM §8 procedure)"))
    x.rule("MM reset", MM, r"Controller reset is only permitted when pressure.*?reads below (\d+) bar",
           lambda p, m: x.fact(p, "PLC-03", "reset_permitted_below_pressure", m.group(1), "bar",
                               note="reads on active sensor (PS-04 <3.2, PS-04A >=3.2); reset re-initialises valve driver outputs -> possible uncommanded IV-21 actuation"))
    x.rule("MM A17 persist", MM, r"persists for more than (\d+) seconds, execute Shutdown Procedure (4\.7)",
           lambda p, m: x.fact(p, "A17", "persistence_threshold_before_action", m.group(1), "s",
                               note="transient A17 may clear by itself; action = Shutdown Procedure " + m.group(2)))
    x.rule("MM shutdown steps", MM, r"Shutdown Procedure 4\.7: (.*?)\. (?:Alarm|\d|$)|Shutdown Procedure 4\.7: ([^.]*(?:\([^)]*\))?[^.]*)\.",
           lambda p, m: x.fact(p, "Shutdown Procedure 4.7", "steps",
                               (m.group(1) or m.group(2)).strip()))
    x.rule("MM troubleshooting", MM, r"Troubleshooting: Low Discharge Pressure",
           lambda p, m: [x.fact(p, "HPU", "low_discharge_pressure_check", v) for v in
                         ("Isolation valve IV-21 is closed or partially closed", "Hydraulic fluid level is low",
                          "Pressure sensor (PS-04 / PS-04A) signal invalid or out of calibration (see A19)")])
    # alarm reference table rows
    d = x.doc(AL)
    if d:
        foots = _footnotes([p for p in x.passages[d["doc_id"]] if p["extraction_method"] != "table"])
        row_ids, tok = set(), lambda t: Counter(re.findall(r"[a-z0-9]+(?:\.[0-9]+)*", t.lower()))
        for p in x.passages[d["doc_id"]]:
            m = re.match(r"\[Table \d+, row \d+\] Alarm: (A\d{2,4}) \| Condition: (.*?) \| Panel", _ws(p["content"]))
            if not m:
                continue
            a, cond = m.group(1), m.group(2)
            row_ids.add(a)
            x.fact(p, a, "condition", cond, method="table")
            t = re.search(r"(below|above) (\d+) bar", cond)
            if t:
                x.fact(p, a, "trigger_threshold", t.group(2), "bar", note=t.group(1), method="table")
            c = re.search(r"Possible Cause\(s\): (.*?) \| Required", _ws(p["content"]))
            if c:
                for cause in re.split(r"\s*\d\.\s+", c.group(1)):
                    if cause.strip():
                        x.fact(p, a, "possible_cause", cause.strip(), method="table")
            ra = re.search(r"Required Action: (.*)$", _ws(p["content"]))
            if ra:
                action = ra.group(1).strip()
                # The WHOLE cell is one fact: sentences are never stored/selected individually, so an instruction cannot be dropped.
                x.fact(p, a, "required_action", action, method="table")
                for r in re.finditer(r"(Maintenance|Operator) Manual,? (?:AEG-[A-Z]+-\d+,? )?Section (\d+)|Section (\d+) of the (Maintenance|Operator) Manual", action):
                    kind, n = (r.group(1), r.group(2)) if r.group(1) else (r.group(4), r.group(3))
                    x.fact(p, a, "required_action_reference", f"{kind} Manual Section {n}", method="table")
                if action.endswith("*"):  # footnote marker -> link the footnote text that qualifies the action
                    if foots:
                        fp, ft = foots[0]
                        x.fact(fp, a, "required_action_footnote", ft, method="table", note="footnote marked * on the required-action cell")
                    else:
                        x.unmatched.append(f"footnote for {a} required action")
                # integrity: every word of the action/cause cells must also exist in the page's independent text layer
                page_txt = " ".join(q["content"] for q in x.passages[d["doc_id"]] if q["extraction_method"] != "table" and q["page_number"] == p["page_number"])
                for label, cell in (("required_action", action), ("possible_cause", c.group(1) if c else "")):
                    missing = tok(cell.replace("*", "")) - tok(page_txt)
                    if missing:
                        x.integrity.append(f"{a} {label}: words not found in page text layer: {sorted(missing)}")
        for pt in (q for q in x.passages[d["doc_id"]] if q["extraction_method"] != "table"):
            for aid in re.findall(r"(?m)^(A\d{2,4})\s+\S", pt["content"]):
                if aid not in row_ids:
                    x.integrity.append(f"{aid} appears as a table row in the page text but no table-row passage was extracted")
    x.rule("AL external alarm ranges", AL, r"Alarms (A\d\d[–-]A\d\d(?: and A\d\d[–-]A\d\d)*).*?(AEG-AL-\d+), which is not part of this package",
           lambda p, m: x.fact(p, "AEG-AL-700", "external_alarm_ranges", m.group(1), note=f"documented in {m.group(2)}, not part of this package"))
    # ECNs
    x.rule("ECN1042 supersede", "ECN-1042.pdf", r"pressure sensor PS-04 is replaced by pressure sensor PS-04A",
           lambda p, m: x.fact(p, "PS-04A", "supersedes", "PS-04", sw_from="3.2", note="Effective software revision 3.2; ECN-1042"))
    x.rule("ECN1042 setpoint", "ECN-1042.pdf", r"setpoint is revised from (\d+) bar to (\d+) bar",
           lambda p, m: (x.fact(p, "HPU", "normal_operating_pressure", m.group(2), "bar", sw_from="3.2",
                                note="deliberate process change, not a calibration artifact (ECN-1042)"),
                         x.fact(p, "HPU", "normal_operating_pressure", m.group(1), "bar", sw_before="3.2",
                                note="prior setpoint per ECN-1042")))
    x.rule("ECN1042 not FFF", "ECN-1042.pdf", r"not a form-fit-function replacement",
           lambda p, m: (x.fact(p, "PS-04A", "interchangeability_with_PS-04", "NOT form-fit-function; requires firmware >= 3.2"),
                         x.fact(p, "PS-04A", "min_firmware", "3.2")))
    x.rule("ECN1042 vintage", "ECN-1042.pdf", r"Series-7 units manufactured after (\d{4})",
           lambda p, m: x.fact(p, "HPU", "setpoint_change_rationale_scope", f"units manufactured after {m.group(1)}",
                               note="rationale text; applicability is otherwise scoped by software revision >= 3.2 -> ambiguity for older-built units"))
    x.rule("ECN1042 PS-04 supported", "ECN-1042.pdf", r"PS-04 remains installed and supported on units running software revisions prior to 3\.2",
           lambda p, m: x.fact(p, "PS-04", "supported_on", "software revisions prior to 3.2", sw_before="3.2"))
    x.rule("ECN1058 correction", "ECN-1058.pdf", r"evaluated against whichever pressure sensor is active",
           lambda p, m: x.fact(p, "A17", "evaluated_against", "active pressure sensor for the installed software revision (PS-04 before 3.2, PS-04A from 3.2)",
                               note="ECN-1058 documentation correction; threshold logic unchanged"))
    x.rule("ECN1058 setpoint unchanged", "ECN-1058.pdf", r"does not change the operating pressure setpoint",
           lambda p, m: x.fact(p, "HPU", "setpoint_note", "ECN-1058 does not change the setpoint established in ECN-1042"))
    # legacy / low-trust / secondary
    x.rule("legacy 180", "legacy_manual_v1.html", r"Normal HPU discharge pressure is (\d+) bar",
           lambda p, m: x.fact(p, "HPU", "normal_operating_pressure", m.group(1), "bar", sw_from="3.0", sw_before="3.2",
                               status="superseded", note="legacy manual v1; applies to sw 3.0 and 3.1 only"))
    x.rule("site note 175", "site_survey_notes.docx", r"read about (\d+) bar during a normal run",
           lambda p, m: x.fact(p, "HPU", "observed_gauge_pressure", m.group(1), "bar", status="unverified",
                               note="uncalibrated local gauge, no date, software revision not checked; contradicts both 180 and 200 bar"))
    x.rule("calib span", "scanned_appendix_calibration.pdf", r"Span reference target is (\d+) bar",
           lambda p, m: x.fact(p, "PS-04A", "calibration_span_reference", m.group(1), "bar", conf=0.85,
                               note="OCR source; calibration date 2026-01-09; PS-04 span target was 180 bar (historical)"))
    x.rule("calib interval gap", "scanned_appendix_calibration.pdf", r"No calibration interval is specified for PS-04A",
           lambda p, m: x.fact(p, "PS-04A", "calibration_interval", "NOT SPECIFIED in package", status="gap", conf=0.85))
    x.rule("slide aux reservoir", "training_slide_excerpt.pptx", r"Auxiliary Reservoir",
           lambda p, m: x.fact(p, "Auxiliary Reservoir", "introduced_in", "training slide + hydraulic schematic only",
                               note="Line 4/5-specific; not in Operator Manual, Maintenance Manual or Component Register"))
    # revision history rows
    d = x.doc("revision_history.xlsx")
    if d:
        for p in x.passages[d["doc_id"]]:
            r = p["metadata"].get("row_cells", {})
            if "Software Revision" in r:
                v = r["Software Revision"]
                x.fact(p, f"software revision {v}", "release_date", r.get("Release Date"), method="structured", conf=1.0)
                x.fact(p, f"software revision {v}", "changes", r.get("Summary of Changes"), method="structured", conf=1.0,
                       note="related: " + (r.get("Related Documents") or ""))


def _facts_from_structured(x: _Ctx):
    d = x.doc("configuration_export.json")
    if not d:
        x.unmatched.append("configuration_export missing"); return
    for p in x.passages[d["doc_id"]]:
        L = p["metadata"].get("leaves", {})
        for k, v in L.items():
            if k == "sensors.sensor_ps04a_threshold_bar":
                x.fact(p, "PS-04A", "config:sensor_ps04a_threshold_bar", v, "bar", sw_from="3.2", method="structured", conf=1.0,
                       note="config key; maps (by sensor id + value + version scope; inferred) to the 3.2+ normal operating pressure setpoint")
            elif k == "revision_applicability.sensor_ps04_legacy_threshold_bar.value":
                x.fact(p, "PS-04", "config:sensor_ps04_legacy_threshold_bar", v, "bar", sw_before="3.2", method="structured", conf=1.0)
            elif k in ("sensors.sensor_ps04a_alarm_low_bar", "sensors.sensor_ps04a_alarm_high_bar"):
                x.fact(p, "PS-04A", "config:" + k.split(".")[-1], v, "bar", method="structured", conf=1.0)
            elif k == "alarms.A17.persistence_before_shutdown_seconds":
                x.fact(p, "A17", "config:persistence_before_shutdown_seconds", v, "s", method="structured", conf=1.0)
            elif k == "controller_reset.max_pressure_bar_allowed_for_reset":
                x.fact(p, "PLC-03", "config:max_pressure_bar_allowed_for_reset", v, "bar", method="structured", conf=1.0,
                       note="firmware blocks reset above this")
            elif k == "controller_reset.min_pressure_bar_required_for_reset":
                x.fact(p, "PLC-03", "config:min_pressure_bar_required_for_reset", "null (no minimum configured)", method="structured", conf=1.0)
            elif k.startswith("startup_interlocks."):
                x.fact(p, "HPU", "config:" + k.split(".")[-1], v, method="structured", conf=1.0)
            elif k == "export_metadata.firmware_version":
                x.fact(p, "PLC-03", "config:firmware_version", v, method="structured", conf=1.0, note="at export 2026-02-03")


def _edges(x: _Ctx):
    for d in x.docs.values():
        for p in x.passages.get(d["doc_id"], []):
            if p["extraction_method"] == "vector":
                m = p["metadata"]
                x.edges.append((m["a"], m["b"], f"{m['color']}:{m['meaning']}", p["passage_id"], "vector-geometry", 0.9))
    for f in x.facts:  # supersession edge, provenance = the ECN passage that states it
        if f[0] == "PS-04A" and f[1] == "supersedes":
            x.edges.append(("PS-04A", "PS-04", "supersedes(sw>=3.2)", f[8], "rule", 0.95))


def _facts_from_screens(x: _Ctx):
    """HMI screenshots -> facts with status 'observed' (a live-style, undated snapshot): they can corroborate or
    contradict, but never override documented specification (resolve_scoped excludes non-'asserted' facts)."""
    SC = "screen_0"
    def screen(name):
        d = x.doc(name)
        return (d, x.passages[d["doc_id"]][0]) if d and x.passages.get(d["doc_id"]) else (None, None)
    d, p = screen("screen_03_diagnostics.png")
    if p:
        t = _ws(p["content"])
        m = re.search(r"Tag\s+([A-Za-z]\.?[A-Za-z]\.?\s?-?\d{2}\s?-?[A-Za-z]?)\b", t)
        if m:
            raw = m.group(1).strip()
            for eid in x.entities:
                if norm(eid) == norm(raw):
                    _add_alias(x, raw, eid, p, "screenshot-tag-formatting-normalisation", 0.95)
                    x.fact(p, eid, "screen_tag_as_displayed", raw, status="observed", method="ocr+rule", conf=0.9,
                           note="screen says the tag is shown 'as printed on the physical unit label'; matches register id after removing separators only")
        for pred, pat, unit in (("screen_scaled_value", r"Scaled Value\s+([\d.]+)\s*bar", "bar"), ("screen_raw_signal", r"Raw Reading\s+([\d.]+)\s*mA", "mA"),
                                ("screen_signal_type", r"Signal Type\s+(4-20\s*mA)", None), ("screen_calibration_status", r"Calibration Status\s+([A-Z ]+?)\s+Last", None),
                                ("screen_last_calibrated", r"Last Calibrated\s+(\d{4}-\d{2}-\d{2})", None), ("screen_firmware_rev", r"Firmware Rev\.?\s+([\d.]+)", None)):
            mm = re.search(pat, t)
            if mm:
                subj = "PLC-03" if pred == "screen_firmware_rev" else "PS-04A"
                x.fact(p, subj, pred, mm.group(1).strip(), unit, status="observed", method="ocr+rule", conf=0.85)
            else:
                x.unmatched.append(f"{pred} ({SC}3)")
    else:
        x.unmatched.append("diagnostics screenshot missing")
    d, p = screen("screen_02_alarms.png")
    if p:
        t = _ws(p["content"])
        m = re.search(r"Alarm (A\d\d) active for (\d\d):(\d\d):(\d\d) .*?Shutdown Procedure 4\.7 threshold: (\d\d):(\d\d):(\d\d)", t)
        if m:
            act = int(m.group(2)) * 3600 + int(m.group(3)) * 60 + int(m.group(4)); thr = int(m.group(5)) * 3600 + int(m.group(6)) * 60 + int(m.group(7))
            x.fact(p, m.group(1), "screen_active_duration", act, "s", status="observed", method="ocr+rule", conf=0.85, note=f"HMI banner; Procedure 4.7 threshold shown on screen = {thr} s")
            x.fact(p, m.group(1), "screen_procedure_4_7_threshold", thr, "s", status="observed", method="ocr+rule", conf=0.85)
        else:
            x.unmatched.append("alarm banner (screen_02)")
        for row in re.finditer(r"\b(\d) (A\d\d) (.+?) (CLEARED|ACTIVE|INACTIVE) ([\d:\- ]+?|--)(?= \d A\d\d|\s*Alarm|$)", t):
            x.fact(p, row.group(2), "screen_alarm_state", f"{row.group(4)} (list row {row.group(1)}, time {row.group(5).strip()})", status="observed", method="ocr+rule", conf=0.85)
    d, p = screen("screen_01_home.png")
    if p:
        t = _ws(p["content"])
        m = re.search(r"\b(\d{2,4}) bar\b", t)
        if m:
            x.fact(p, "HPU", "screen_displayed_pressure", m.group(1), "bar", status="observed", method="ocr+rule", conf=0.8, note="home-screen hero value; STATUS: RUNNING — NORMAL; undated")
        else:
            x.unmatched.append("home pressure (screen_01)")
        for lab, pat in (("iv21", r"IV-21 \(Isolation Valve\) (OPEN|CLOSED)"), ("estop", r"Emergency Stop (RESET|LATCHED|\w+)"), ("panel", r"Maintenance Panel (CLOSED|OPEN)")):
            mm = re.search(pat, t)
            if mm:
                x.fact(p, "HPU", f"screen_interlock_{lab}", mm.group(1), status="observed", method="ocr+rule", conf=0.8,
                       note="OCR row alignment of the interlock panel is imperfect for the fluid-level row")
