"""Central configuration. Override via environment variables (see .env.example)."""
import os

DB_PATH = os.environ.get("AEGIS_DB", "data/aegis_rag.db")
RAW_DIR = os.environ.get("AEGIS_RAW", "data/raw")
LOG_PATH = os.environ.get("AEGIS_LOG", "logs/ingestion.log")

# Retrieval parameters
TOP_K = int(os.environ.get("AEGIS_TOP_K", "8"))
BM25_WEIGHT = float(os.environ.get("AEGIS_BM25_W", "0.6"))
TFIDF_WEIGHT = float(os.environ.get("AEGIS_TFIDF_W", "0.4"))
RERANK = os.environ.get("AEGIS_RERANK", "1") == "1"

# Optional LLM (answer-polishing only; every claim is still built from stored facts).
LLM_MODEL = os.environ.get("AEGIS_LLM_MODEL", "claude-sonnet-4-6")
USE_LLM = os.environ.get("AEGIS_USE_LLM", "0") == "1"

# TRUST POLICY -- assigned from the task description's trust levels by FOLDER, not
# extracted from document text (no source document states an "authority level").
# Lower number = more authoritative. This is a documented policy decision.
TRUST_BY_FOLDER = {
    "engineering_bulletins": 1,  # controlled change notices
    "manuals": 2,                # official manuals (legacy_manual_v1 overridden below)
    "reference": 2,
    "configuration": 2,          # machine export: authoritative for what the unit is set to
    "diagrams": 2,
    "screenshots": 3,            # live-style HMI captures: undated, OCR-derived observations, not spec
    "scans": 3,                  # scanned, "uncontrolled copy", OCR noise
    "extra": 3,                  # training material restates manuals
    "low_trust": 4,              # field notes, no revision control
    "noise": 5,                  # irrelevant reference
}
TRUST_OVERRIDES = {"legacy_manual_v1.html": 4}  # superseded export
TRUST_LABEL = {1: "change-notice", 2: "official", 3: "secondary", 4: "low-trust/superseded", 5: "irrelevant"}
