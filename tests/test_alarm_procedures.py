"""Regression tests for alarm meaning / cause / action / restart answering.

NOTE on the source of truth: in the supplied AEG-AL-700 Rev 5, A19's required action is ONLY
"Replace sensor per Maintenance Manual Section 6." The text "Stop the HPU. Do not restart until pressure relief is
verified." belongs to A18's row. Tests below assert the documents' content; the mechanism that preserves a multi-sentence
cell (and restart restrictions) is proven separately on a synthetic alarm table (test_synthetic_*)."""
import re
import pytest
from src.database import DatabaseManager
from src.knowledge.build import build_knowledge_layer
from src.qa.alarms import find_alarm_ids, sentences
from src.qa.engine import QAEngine
from src.qa.facts import FactStore
from src.qa.models import ANSWERED, CAVEATS, INSUFFICIENT, Answer
from src.retrieval.index import HybridIndex

STOP = re.compile(r"stop the hpu|do not restart", re.I)
text_of = lambda a: a.answer + " " + " ".join(c.text for c in a.claims)


def cell(real_env, alarm):
    return FactStore(real_env["db"]).get(alarm, "required_action")[0].value.replace("*", "").strip()


def documented(real_env):
    return real_env["engine"].alarms.documented()


def cites_alarm_row(a, alarm_no):
    return any(e.source.endswith("alarm_reference.pdf") and f"Alarm: {alarm_no}" in e.quote for c in a.claims for e in c.evidence)


# ---- Test 1: meaning ----
def test_t1_alarm_meaning(real_env):
    a = real_env["engine"].ask("What does alarm A19 mean?")
    assert a.handler == "alarm_ref" and a.status == ANSWERED
    assert "Pressure sensor signal invalid" in a.answer
    assert cites_alarm_row(a, "A19") and all(c.evidence for c in a.claims)
    t = text_of(a).lower()
    assert "replace sensor" not in t and "wiring" not in t and "drift" not in t and not STOP.search(t)   # nothing invented / no other facets


# ---- Test 2: complete action (as documented) ----
def test_t2_alarm_action_is_complete_and_supported(real_env):
    a = real_env["engine"].ask("What action is required for A19?")
    assert a.handler == "alarm_ref"
    assert cell(real_env, "A19") in a.answer                                  # whole cell, not a fragment
    assert "Maintenance Manual Section 6" in a.answer and cites_alarm_row(a, "A19")
    assert not STOP.search(text_of(a))                                        # A18's instruction must NOT leak into A19
    assert any("no stop-the-unit or restart instruction" in u for u in a.unknowns)
    assert any("contains no 'replace' procedure" in u for u in a.unknowns) and a.status == CAVEATS   # referenced section lacks the steps


def test_t2b_alarm_with_multi_instruction_cell_returns_all_of_it(real_env):
    a = real_env["engine"].ask("What action is required for A18?")
    assert "Stop the HPU." in a.answer and "Do not restart until pressure relief is verified." in a.answer
    assert a.status == ANSWERED and cites_alarm_row(a, "A18")


# ---- Test 3: procedure questions go to the alarm path, never generic lookup ----
@pytest.mark.parametrize("tmpl", ["What should I do when alarm {a} occurs?", "What action is required for {a}?", "How do I handle {a}?",
                                  "What is the procedure for alarm {a}?", "How do I resolve {a}?"])
def test_t3_action_questions_route_to_alarm_handler_for_every_documented_alarm(real_env, tmpl):
    for al in documented(real_env):       # generic over the documented alarms: no ids hardcoded
        a = real_env["engine"].ask(tmpl.format(a=al))
        assert a.handler in ("alarm_ref", "a17_persist"), (al, a.handler)
        assert a.handler != "fact_lookup"
        assert re.sub(r"\s+", " ", cell(real_env, al)) in re.sub(r"\s+", " ", text_of(a).replace("*", "")), al
        assert cites_alarm_row(a, al)


def test_t3_issue_b_regression_not_fact_lookup(real_env):
    a = real_env["engine"].ask("What should I do when alarm A19 occurs?")
    assert a.handler == "alarm_ref" and "Condition" not in a.answer
    assert "Replace sensor per Maintenance Manual Section 6." in a.answer
    assert not any(STOP.search(c.text) for c in a.claims)       # no unsupported extra steps


def test_t3_issue_a_combined_question_includes_the_action(real_env):
    a = real_env["engine"].ask("What does alarm A19 indicate, and what action is required?")
    assert "Pressure sensor signal invalid" in a.answer and "Replace sensor per Maintenance Manual Section 6." in a.answer


# ---- Test 4: restart ----
def test_t4_restart_after_a19_is_not_authorised_and_not_controller_reset(real_env):
    a = real_env["engine"].ask("Can I restart the HPU after A19?")
    assert a.handler == "alarm_ref" and a.status == INSUFFICIENT
    assert "cannot be confirmed as permitted" in a.answer and "50 bar" not in text_of(a)   # not the controller-reset rule
    assert not re.search(r"\b(you may|you can|is permitted|is allowed|safe to) restart", text_of(a), re.I)
    assert any("not permission to restart" in u for u in a.unknowns)


def test_t4b_restart_restriction_is_stated_where_documented(real_env):
    a = real_env["engine"].ask("Can I restart the HPU after A18?")
    assert "Do not restart until pressure relief is verified." in a.answer and a.status == ANSWERED and cites_alarm_row(a, "A18")


def test_t4c_restart_without_alarm_is_not_answered_with_controller_reset(real_env):
    a = real_env["engine"].ask("Can I restart the HPU?")
    assert a.handler == "restart_hpu" and "50 bar" not in a.answer and a.status == CAVEATS
    assert "A18" in a.answer
    b = real_env["engine"].ask("Can I restart the PLC while the circuit is pressurised at 80 bar?")
    assert b.handler == "reset" and "50 bar" in b.answer                      # genuine controller-reset questions unchanged


# ---- Test 5: causes ----
@pytest.mark.parametrize("q", ["What causes alarm A19?", "What are the possible causes of A19?", "Why would alarm A19 be raised?"])
def test_t5_possible_causes_only(real_env, q):
    a = real_env["engine"].ask(q)
    assert "Sensor wiring fault" in a.answer and "Sensor drift beyond tolerance" in a.answer and a.status == ANSWERED
    assert "Replace sensor" not in text_of(a)                                  # causes are not confused with actions


# ---- Test 6: unsupported alarm identifiers ----
def test_t6_unknown_alarm_abstains_and_does_not_confuse_ecn(real_env):
    a = real_env["engine"].ask("What does alarm A-1042 mean?")
    assert a.status == INSUFFICIENT and a.handler == "alarm_ref"
    assert a.answer.startswith("Cannot be determined") and "A-1042" in a.answer
    assert "ECN-1042" in a.answer and "not an alarm" in a.answer
    assert any("document identifier, not an alarm tag" in u for u in a.unknowns)
    assert not re.search(r"indicates|possible causes|required action", a.answer, re.I)
    assert any("ECN-1042" in e.source or e.doc_code == "ECN-1042" for c in a.claims for e in c.evidence)   # collision is evidenced


def test_t6b_alarm_in_external_range_explains_missing_companion_document(real_env):
    a = real_env["engine"].ask("What does alarm A05 mean?")
    assert a.status == INSUFFICIENT and "companion alarm reference" in " ".join(a.unknowns)
    assert any(e.source.endswith("alarm_reference.pdf") for c in a.claims for e in c.evidence)


def test_t6c_unsupported_question_type_is_a_different_message(real_env):
    a = real_env["engine"].ask("Please compose a poem about hydraulics")
    assert a.status == INSUFFICIENT and a.handler == "fallback" and any("Unrecognised question type" in u for u in a.unknowns)


def test_alarm_id_detection_has_no_false_positives():
    ids = lambda q: [t["id"] for t in find_alarm_ids(q)]
    assert ids("What does alarm A19 mean?") == ["A19"] and ids("alarm A-1042") == ["A1042"] and ids("alarm A 19 meaning") == ["A19"]
    for q in ("Who approved ECN-1058?", "Is PS-04A the same as PS-04?", "AEG-AL-700 Rev 5", "Hydraulic Power Unit A 19 mm", "IV-21 open"):
        assert ids(q) == [], q


# ---- Test 7: startup preserved ----
def test_t7_startup_requirements_preserved(real_env):
    a = real_env["engine"].ask("What must be true before starting the HPU?")
    assert a.handler == "startup" and a.status == ANSWERED
    t = a.answer.lower()
    assert "sight glass" in t and "iv-21 is open" in t and "emergency stop circuit is reset" in t and "maintenance access panel" in t   # all four requirements
    assert any(e.source.endswith("operator_manual.pdf") for c in a.claims for e in c.evidence) and all(c.evidence for c in a.claims)


# ---- footnotes / extraction integrity ----
def test_footnote_is_linked_to_the_action_it_qualifies(real_env):
    a = real_env["engine"].ask("What action is required for A17?")
    assert "Footnote" in a.answer and "applies only when A17 persists beyond 10 seconds" in a.answer
    assert "*" not in a.answer
    assert any(e.source.endswith("alarm_reference.pdf") for c in a.claims if "Footnote" in c.text for e in c.evidence)


def test_real_extraction_integrity_has_no_warnings(real_env):
    assert real_env["stats"]["knowledge"]["integrity_warnings"] == []


def test_integrity_check_detects_a_truncated_cell_and_a_lost_row(tmp_path):
    db = DatabaseManager(str(tmp_path / "t.db"))
    doc = {"doc_id": "d", "filename": "alarm_reference.pdf", "file_path": "x", "rel_path": "reference/alarm_reference.pdf", "file_type": "pdf", "authority_level": 2}
    page = "Alarm Reference\nA19 Pressure sensor RED 1. Wiring Stop the HPU. Do not\nA20 Other alarm RED 1. x y"      # text layer has full wording + a row A20
    rows = [{"passage_id": "d_p1", "doc_id": "d", "content": page, "page_number": 1, "extraction_method": "text"},
            {"passage_id": "d_t1", "doc_id": "d", "page_number": 1, "extraction_method": "table",
             "content": "[Table 1, row 1] Alarm: A19 | Condition: Pressure sensor signal invalid | Panel Indication: RED | Possible Cause(s): 1. Wiring | Required Action: Stop the HPU. Do not restart until verified."}]
    db.save_ingested_data(doc, rows)
    w = build_knowledge_layer(db)["integrity_warnings"]
    assert any("A19 required_action" in x and "restart" in x for x in w)           # words in the cell absent from the page text layer
    assert any("A20" in x and "no table-row passage" in x for x in w)               # a row visible in text but missing from the table


# ---- the guards ----
def _truncating_handler(engine, a_id="A18"):
    def h(q, ents, sw):
        fs = FactStore(engine.db)
        f = fs.get(a_id, "required_action")
        return Answer(q, f"{a_id}: Stop the HPU.", ANSWERED, "high", [engine.claim(f"{a_id}: Stop the HPU.", f)])
    return h


def test_completeness_guard_repairs_a_truncated_action_answer(real_env, monkeypatch):
    e = real_env["engine"]
    monkeypatch.setattr(e, "h_alarm_ref", _truncating_handler(e))
    a = e.ask("What action is required for A18?")
    assert "Do not restart until pressure relief is verified." in a.answer
    assert any("Completeness check" in x for x in a.assumptions) and a.status == CAVEATS


def test_contamination_guard_discards_a_draft_with_another_alarms_instruction(real_env, monkeypatch):
    e = real_env["engine"]; fs = FactStore(e.db)
    def bad(q, ents, sw):                          # A19 answer that borrows A18's instruction, but cites A19's row
        f19 = fs.get("A19", "required_action")
        return Answer(q, "A19: Stop the HPU. Do not restart until pressure relief is verified.", ANSWERED, "high",
                      [e.claim("A19: Stop the HPU. Do not restart until pressure relief is verified.", f19)])
    monkeypatch.setattr(e, "h_alarm_ref", bad)
    a = e.ask("What action is required for A19?")
    assert not STOP.search(a.answer) and "Replace sensor per Maintenance Manual Section 6." in a.answer
    assert any("inconsistent draft" in x for x in a.assumptions)


def test_fact_lookup_never_serves_partial_alarm_records(real_env):
    e = real_env["engine"]
    a = e._fact_lookup("what is the required action", ["A19"], None)
    assert a is None


# ---- mechanism proof on a synthetic alarm table whose A19 cell has several instructions ----
@pytest.fixture(scope="module")
def synthetic(tmp_path_factory):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Table, TableStyle
    from src.ingest import IngestionPipeline
    d = tmp_path_factory.mktemp("syn"); raw = d / "raw" / "reference"; raw.mkdir(parents=True)
    st = getSampleStyleSheet()["BodyText"]; P = lambda t: Paragraph(t, st)
    data = [[P(h) for h in ("Alarm", "Condition", "Panel Indication", "Possible Cause(s)", "Required Action")],
            [P("A17"), P("Hydraulic pressure below 150 bar"), P("RED"), P("1. IV-21 closed"), P("See Section 4 of the Maintenance Manual.")],
            [P("A19"), P("Pressure sensor signal invalid"), P("RED"), P("1. Sensor wiring fault<br/>2. Sensor drift beyond tolerance"),
             P("Stop the HPU. Do not restart until pressure relief is verified. Replace sensor per Maintenance Manual Section 6.")]]
    t = Table(data, colWidths=[40, 100, 60, 130, 150]); t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.black)]))
    SimpleDocTemplate(str(raw / "alarm_reference.pdf"), pagesize=A4).build(
        [Paragraph("Aegis Series-7 HCS Alarm Reference", getSampleStyleSheet()["Title"]), Paragraph("Document AEG-AL-700 | Revision 9 (synthetic fixture)", st), t])
    s = IngestionPipeline(str(d / "t.db"), str(d / "l.log")).run(str(d / "raw"))
    db = DatabaseManager(str(d / "t.db"))
    return QAEngine(db, HybridIndex(db, str(d / "i.pkl"))), s


def test_synthetic_multi_instruction_cell_survives_whole_pipeline(synthetic):
    e, s = synthetic
    assert not s["failed_files"]
    for q in ("What action is required for A19?", "What should I do when alarm A19 occurs?", "What does alarm A19 indicate, and what action is required?"):
        a = e.ask(q)
        for sent in ("Stop the HPU.", "Do not restart until pressure relief is verified.", "Replace sensor per Maintenance Manual Section 6."):
            assert sent in a.answer, (q, sent)
        assert cites_alarm_row(a, "A19") and a.handler == "alarm_ref"
        assert not any("no stop-the-unit or restart instruction" in u for u in a.unknowns)       # the note appears only when truly absent


def test_synthetic_restart_restriction_follows_the_document(synthetic):
    e, _ = synthetic
    a = e.ask("Can I restart the HPU after A19?")
    assert a.status == ANSWERED and "Do not restart until pressure relief is verified." in a.answer
    assert "cannot be confirmed" not in a.answer


def test_synthetic_missing_referenced_section_is_reported(synthetic):
    e, _ = synthetic
    a = e.ask("What action is required for A19?")
    assert any("is not present in the package" in u for u in a.unknowns) and a.status == CAVEATS
