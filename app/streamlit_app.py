"""UI only. All logic lives in src/. Run: streamlit run app/streamlit_app.py"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import streamlit as st
from src import config
from src.database import DatabaseManager
from src.retrieval.index import HybridIndex
from src.qa.engine import QAEngine
from src.config import TRUST_LABEL

st.set_page_config(page_title="Aegis Series-7 HCS Q&A", layout="wide")
st.title("Aegis Series-7 HCS — evidence-grounded Q&A")

if not os.path.exists(config.DB_PATH):
    st.error(f"Database not found at {config.DB_PATH}. Run: python pipeline.py data/raw"); st.stop()

@st.cache_resource
def load():
    db = DatabaseManager(config.DB_PATH)
    return db, QAEngine(db, HybridIndex(db))
db, engine = load()

with st.sidebar:
    st.header("Unit context")
    sw = st.text_input("Software revision of the unit (optional)", "", help="Scopes version-dependent answers (e.g. 3.1 vs 3.2).")
    st.caption("Leave empty if unknown — the answer then shows every revision-scoped value.")
    st.markdown("**Statuses**: ANSWERED · ANSWERED_WITH_CAVEATS · CONFLICT · INSUFFICIENT_EVIDENCE")
q = st.text_input("Ask a question about the system", placeholder="What must be true before starting the HPU?")
if q:
    a = engine.ask(q, sw=sw or None)
    color = {"ANSWERED": "green", "ANSWERED_WITH_CAVEATS": "orange", "CONFLICT": "red", "INSUFFICIENT_EVIDENCE": "gray"}.get(a.status, "gray")
    st.markdown(f"### Answer  :{color}[{a.status}]  · confidence: {a.confidence}")
    st.write(a.answer)
    for title, items in (("⚠️ Conflicts / contradictions", a.conflicts), ("❓ Could not determine", a.unknowns), ("Assumptions", a.assumptions)):
        if items:
            st.markdown(f"**{title}**")
            for i in items: st.markdown(f"- {i}")
    st.markdown("### Claims and evidence")
    for i, c in enumerate(a.claims, 1):
        with st.expander(f"{i}. {c.text}", expanded=(i <= 2)):
            for e in c.evidence:
                st.markdown(f"**{e.source}** · {e.doc_code or ''} {('Rev ' + e.revision) if e.revision else ''} · {e.location} · "
                            f"trust: {TRUST_LABEL.get(e.trust, '?')} · extraction: `{e.method}`")
                st.code(e.quote, language=None)
    with st.expander(f"Retrieval trace (handler: {a.handler}) — {a.timings_ms.get('total')} ms"):
        st.dataframe(a.retrieved)
