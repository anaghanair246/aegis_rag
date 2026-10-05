import json, pytest
from src.knowledge.aliases import norm, sw_in_scope
from src.qa.facts import FactStore, resolve_scoped
from src.qa import llm as L
from src.qa.models import INSUFFICIENT, ANSWERED, CAVEATS


def test_alias_resolution_policy(real_env):
    c = real_env["index"].canon
    assert c.entities("what is PS04A") == ["PS-04A"]          # formatting variance merged
    assert c.entities("PS-04 sensor") == ["PS-04"]            # PS-04 must NOT match inside PS-04A / merge
    assert "PS-40" in c.entities("the P40 sensor") and "PS-04" not in c.entities("the P40 sensor")
    assert c.entities("the HP unit") == ["HPU"] and c.entities("Hydraulic Power Pack") == ["HPU"]
    assert norm("PS 04-a") == "PS04A"


def test_version_scope_logic():
    assert sw_in_scope("3.1", None, "3.2") and not sw_in_scope("3.2", None, "3.2") and sw_in_scope("3.2.1", "3.2", None)


def test_conflict_and_scope_resolution(real_env):
    fs = FactStore(real_env["db"]).get("HPU", "normal_operating_pressure")
    r = resolve_scoped(fs)
    assert not r["conflicts"]  # 180 vs 200 are version-scoped, not conflicts
    assert {f.display() for f in r["applicable"]} == {"180 bar", "200 bar"}
    assert all(f.trust >= 4 or f.status != "asserted" for f in r["unverified"])
    r31 = resolve_scoped(fs, "3.1"); r32 = resolve_scoped(fs, "3.2")
    assert {f.display() for f in r31["applicable"]} == {"180 bar"} and {f.display() for f in r32["applicable"]} == {"200 bar"}
    assert len(r31["applicable"]) >= 2  # corroborated by OM and ECN-1042


def test_conflict_detected_for_overlapping_scopes():
    from src.qa.facts import Fact
    mk = lambda v, t: Fact(1, "X", "p", v, "bar", None, None, "asserted", t, "p", "d", None, 1.0)
    assert resolve_scoped([mk("1 bar", 2), mk("2 bar", 2)])["conflicts"]


def test_retrieval_finds_gold(real_env):
    hits = real_env["index"].search("Which alarm for pressure below 150 bar", k=5)
    assert any("alarm_reference" in h.passage["rel_path"] for h in hits)
    hits = real_env["index"].search("normal discharge pressure of the HP unit", k=5)
    assert any("operator_manual" in h.passage["rel_path"] for h in hits)


def test_authority_rerank_demotes_legacy(real_env):
    ix = real_env["index"]
    top = ix.search("normal HPU discharge pressure", k=8, rerank=True)
    paths = [h.passage["rel_path"] for h in top]
    assert paths.index("manuals/operator_manual.pdf") < paths.index("manuals/legacy_manual_v1.html") if "manuals/legacy_manual_v1.html" in paths else True


def test_index_rebuild_no_stale_vectors(real_env, tmp_path):
    from src.retrieval.index import HybridIndex
    db = real_env["db"]
    with db.conn() as c:
        c.execute("DELETE FROM documents WHERE rel_path LIKE '%safety_data_sheet%'"); c.commit()
    ix = HybridIndex(db, str(tmp_path / "i.pkl"))
    assert all("safety_data_sheet" not in p["rel_path"] for p in ix.ps)
    assert ix.mat.shape[0] == len(ix.ps) == len(ix.ids)


# ---------- answers ----------
@pytest.mark.parametrize("q,status,must", [
    ("What must be true before starting the Hydraulic Power Unit?", ANSWERED, "IV-21"),
    ("What does alarm A17 indicate, and what are its possible causes?", ANSWERED, "150 bar"),
    ("Is PS-04 the same component as PS-04A?", ANSWERED, "No"),
    ("What action is required if alarm A17 persists for more than 10 seconds?", ANSWERED, "4.7"),
])
def test_answers_and_citations(real_env, q, status, must):
    a = real_env["engine"].ask(q)
    assert a.status == status and must in a.answer + " ".join(c.text for c in a.claims)
    assert a.claims and all(c.evidence for c in a.claims)
    ids = set(real_env["index"].ids)
    assert all(e.passage_id in ids for c in a.claims for e in c.evidence)   # citations are real passages


@pytest.mark.parametrize("q", [
    "What is the maximum continuous operating temperature of PS-04A?",
    "Who approved engineering bulletin ECN-1058?",
    "What is the mean time between failures for the isolation valve IV-21?",
    "Is the Aegis Series-7 HCS compatible with a 3-phase 400V supply?",
    "What is the normal pressure for PS-40?",
])
def test_abstains_on_unanswerable(real_env, q):
    a = real_env["engine"].ask(q)
    assert a.status == INSUFFICIENT and a.unknowns


def test_sds_noise_never_answers_equipment_questions(real_env):
    a = real_env["engine"].ask("What is the maximum continuous operating temperature of PS-04A?")
    assert "210" not in a.answer and all("safety_data_sheet" not in e.source for c in a.claims for e in c.evidence)


def test_revision_specific_answers(real_env):
    e = real_env["engine"]
    a = e.ask("What is the normal operating pressure for the HPU?", sw="3.1")
    assert "180 bar" in a.answer and "200 bar" not in a.answer
    a = e.ask("What is the normal operating pressure for the HPU?", sw="3.2")
    assert "200 bar" in a.answer and "180 bar" not in a.answer


def test_low_trust_conflict_is_surfaced_not_adopted(real_env):
    a = real_env["engine"].ask("What is the current normal operating pressure for the HPU, and under what conditions does that apply?")
    assert a.status == CAVEATS and any("175" in c for c in a.conflicts) and "175" not in a.answer


def test_reset_threshold_answer(real_env):
    a = real_env["engine"].ask("Under what circumstances must the controller not be reset?")
    assert "50 bar" in a.answer


# ---------- LLM path (mock client; live model UNVERIFIED) ----------
class _Msg:
    def __init__(self, t): self.content = [type("B", (), {"type": "text", "text": t})()]
class _Client:
    def __init__(self, t): self.messages = self; self.t = t
    def create(self, **kw): return _Msg(self.t)


def _hits(real_env): return real_env["index"].search("normal pressure of HPU", k=4)

def test_llm_valid_response_accepted(real_env):
    h = _hits(real_env); pid = next(x.passage_id for x in h if "operator_manual" in x.passage["rel_path"])
    r = json.dumps({"status": "ANSWERED", "answer": "200 bar", "claims": [{"text": "Normal pressure is 200 bar", "passage_ids": [pid]}], "conflicts": [], "unknowns": []})
    a = L.llm_answer("q", h, real_env["engine"], client=_Client(r))
    assert a.status == "ANSWERED" and a.handler == "llm"

@pytest.mark.parametrize("claims,why", [
    ([{"text": "x", "passage_ids": ["fake_id"]}], "fabricated"),
    ([{"text": "x", "passage_ids": []}], "without citation"),
    ([{"text": "It is 999 bar", "passage_ids": "PID"}], "ungrounded"),
])
def test_llm_invalid_responses_rejected(real_env, claims, why):
    h = _hits(real_env); pid = h[0].passage_id
    for c in claims:
        if c["passage_ids"] == "PID": c["passage_ids"] = [pid]
    r = json.dumps({"status": "ANSWERED", "answer": "a", "claims": claims})
    a = L.llm_answer("q", h, real_env["engine"], client=_Client(r))
    assert a.status == INSUFFICIENT and why in a.unknowns[0]


# ---------- HMI screenshots ----------
def test_alarm_tag_repair_from_description():
    from src.extractors.screenshot_extractor import repair_alarm_row, repair_alarm_banner
    assert repair_alarm_row("1 Al7 Hydraulic Pressure Low CLEARED 08:14:02").startswith("1 A17 ")
    assert repair_alarm_row("2 Alg9 Pressure Sensor Signal Invalid CLEARED").startswith("2 A19 ")
    assert repair_alarm_row("4 Als Hydraulic Pressure High INACTIVE --").startswith("4 A18 ")
    assert repair_alarm_row("5 Xyz Unknown thing ACTIVE") == "5 Xyz Unknown thing ACTIVE"   # unknown description: never guessed
    assert "Alarm A17 active for" in repair_alarm_banner("Alarm Al7 active for 00:00:14 — Shutdown Procedure 4.7 threshold: 00:00:10")


def test_real_screenshots_ocr_key_values(real_env):
    with real_env["db"].conn() as c:
        t = {r[0].split("/")[-1]: r[1] for r in c.execute("SELECT rel_path, content FROM passages p JOIN documents d USING(doc_id) WHERE rel_path LIKE 'screenshots/%'")}
    assert "200 bar" in t["screen_01_home.png"] and "OPEN" in t["screen_01_home.png"] and "RESET" in t["screen_01_home.png"]
    assert "A17 Hydraulic Pressure Low ACTIVE" in t["screen_02_alarms.png"] and "A19" in t["screen_02_alarms.png"] and "A18" in t["screen_02_alarms.png"]
    assert "P.S.04-A" in t["screen_03_diagnostics.png"] and "14.8 mA" in t["screen_03_diagnostics.png"] and "200.3 bar" in t["screen_03_diagnostics.png"]


def test_dotted_tag_resolves_by_formatting_only(real_env):
    c = real_env["index"].canon
    assert c.entities("P.S.04-A") == ["PS-04A"]
    assert c.entities("P.S.04") == ["PS-04"]            # still not merged with PS-04A
    assert "PS-40" not in c.entities("P.S.04-A")


def test_screen_values_are_observations_not_spec(real_env):
    fs = FactStore(real_env["db"])
    assert all(f.status == "observed" for f in fs.like("HPU", "screen_") + fs.like("PS-04A", "screen_") + fs.like("A17", "screen_"))
    for sw, expect in (("3.1", "180 bar"), ("3.2", "200 bar")):
        a = real_env["engine"].ask("What is the normal operating pressure for the HPU?", sw=sw)
        assert expect in a.answer
        assert not any("screen_0" in e.source for c in a.claims for e in c.evidence)   # the HMI never feeds the specification answer


def test_q13_diagnostics_sensor_id(real_env):
    a = real_env["engine"].ask("What sensor ID appears on the diagnostics screenshot, and does it match a known component")
    assert a.status == CAVEATS and "P.S.04-A" in a.answer and "PS-04A" in a.answer
    srcs = {e.source for c in a.claims for e in c.evidence}
    assert {"screenshots/screen_03_diagnostics.png", "reference/component_register.xlsx", "scans/scanned_appendix_calibration.pdf", "configuration/configuration_export.json"} <= srcs
    assert any("not listed among the register" in u for u in a.unknowns)       # alias is inferred, not registered -> disclosed


def test_alarm_screen_requires_procedure_and_flags_inconsistency(real_env):
    a = real_env["engine"].ask("On the HMI alarm screen, has A17 been active long enough to require shutdown?")
    assert "Procedure 4.7" in a.answer and "14 s" in a.answer
    assert any("cannot both describe the same moment" in u for u in a.unknowns)
    assert any("maintenance_manual" in e.source for c in a.claims for e in c.evidence)
