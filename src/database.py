import json
import os
import sqlite3
from typing import Any, Dict, List

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
  doc_id TEXT PRIMARY KEY, filename TEXT NOT NULL, file_path TEXT NOT NULL, rel_path TEXT NOT NULL,
  file_type TEXT NOT NULL, doc_code TEXT, revision_id TEXT, applies_to TEXT, authority_level INTEGER,
  extraction_meta TEXT, ingested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS passages (
  passage_id TEXT PRIMARY KEY, doc_id TEXT NOT NULL, content TEXT NOT NULL, page_number INTEGER,
  section_title TEXT, revision_id TEXT, authority_level INTEGER, is_visual_element INTEGER DEFAULT 0,
  extraction_method TEXT, ocr_confidence REAL, metadata TEXT,
  FOREIGN KEY (doc_id) REFERENCES documents(doc_id) ON DELETE CASCADE);
CREATE INDEX IF NOT EXISTS idx_passages_doc ON passages(doc_id);
CREATE TABLE IF NOT EXISTS entities (
  entity_id TEXT PRIMARY KEY, kind TEXT, canonical_name TEXT, location TEXT, status TEXT, notes TEXT);
CREATE TABLE IF NOT EXISTS aliases (
  alias_norm TEXT NOT NULL, entity_id TEXT NOT NULL, alias_raw TEXT, source_passage_id TEXT, method TEXT, confidence REAL,
  PRIMARY KEY (alias_norm, entity_id));
CREATE TABLE IF NOT EXISTS facts (
  fact_id INTEGER PRIMARY KEY AUTOINCREMENT, subject TEXT NOT NULL, predicate TEXT NOT NULL,
  value TEXT NOT NULL, unit TEXT, sw_from TEXT, sw_before TEXT, status TEXT DEFAULT 'asserted',
  trust INTEGER, passage_id TEXT NOT NULL, doc_id TEXT NOT NULL, method TEXT, confidence REAL, note TEXT,
  FOREIGN KEY (passage_id) REFERENCES passages(passage_id) ON DELETE CASCADE);
CREATE INDEX IF NOT EXISTS idx_facts_sp ON facts(subject, predicate);
CREATE TABLE IF NOT EXISTS edges (
  edge_id INTEGER PRIMARY KEY AUTOINCREMENT, src TEXT, dst TEXT, kind TEXT, passage_id TEXT, method TEXT, confidence REAL);
CREATE TABLE IF NOT EXISTS ingestion_runs (
  run_id INTEGER PRIMARY KEY AUTOINCREMENT, started TIMESTAMP DEFAULT CURRENT_TIMESTAMP, seconds REAL, stats TEXT);
"""


class DatabaseManager:
    def __init__(self, db_path: str = "data/aegis_rag.db"):
        self.db_path = db_path
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        with self.conn() as c:
            c.executescript(SCHEMA)

    def conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.db_path)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys = ON;")
        return c

    def save_ingested_data(self, document: Dict[str, Any], passages: List[Dict[str, Any]]):
        """Atomic: document row + ALL passages commit together or not at all.
        Re-ingestion replaces the doc's passages (and, via cascade, its facts)."""
        c = self.conn()
        try:
            c.execute("BEGIN")
            c.execute("DELETE FROM documents WHERE doc_id=?", (document["doc_id"],))  # cascade clears stale passages/facts
            c.execute(
                """INSERT INTO documents (doc_id, filename, file_path, rel_path, file_type, doc_code, revision_id,
                   applies_to, authority_level, extraction_meta) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (document["doc_id"], document["filename"], document["file_path"], document.get("rel_path", ""),
                 document["file_type"], document.get("doc_code"), document.get("revision_id"),
                 document.get("applies_to"), document.get("authority_level"),
                 json.dumps(document.get("metadata", {}))))
            for p in passages:
                c.execute(
                    """INSERT INTO passages (passage_id, doc_id, content, page_number, section_title, revision_id,
                       authority_level, is_visual_element, extraction_method, ocr_confidence, metadata)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (p["passage_id"], p["doc_id"], p["content"], p.get("page_number"), p.get("section_title"),
                     p.get("revision_id"), p.get("authority_level"), 1 if p.get("is_visual_element") else 0,
                     p.get("extraction_method"), p.get("ocr_confidence"), json.dumps(p.get("metadata", {}))))
            c.commit()
        except Exception:
            c.rollback()
            raise
        finally:
            c.close()

    def count(self, table: str) -> int:
        assert table in {"documents", "passages", "facts", "entities", "aliases", "edges"}
        with self.conn() as c:
            return c.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]

    def get_document_count(self): return self.count("documents")
    def get_passage_count(self): return self.count("passages")
