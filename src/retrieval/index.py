"""Hybrid retrieval: BM25 (lexical) + TF-IDF cosine (local 'embedding'), alias-canonicalised,
metadata-aware rerank, near-duplicate suppression. Index is a derived artefact rebuilt from the DB
whenever the passage-set hash changes (so no stale vectors survive re-ingestion).

Embedding choice: no network/HF access was available in the build environment, so the default 'embedder'
is sparse TF-IDF (word 1-2grams). A dense model can be plugged in via AEGIS_EMBEDDER=sbert:<model> (requires
sentence-transformers + model download) -- NOT verified here; see README."""
import hashlib
import os
import pickle
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional
import numpy as np
from rank_bm25 import BM25Okapi
from sklearn.feature_extraction.text import TfidfVectorizer
from src import config
from src.database import DatabaseManager
from src.knowledge.aliases import norm

STOP = set("the a an of to in on is are was were be for and or by with as at it its this that what which who does do did "
           "from per not under must before after than then".split())
_TOK = re.compile(r"[a-z0-9]+(?:[.\-][a-z0-9]+)*")


def tokenize(text: str) -> List[str]:
    return [t for t in _TOK.findall(text.lower()) if t not in STOP]


@dataclass
class Hit:
    passage_id: str
    score: float
    bm25: float = 0.0
    tfidf: float = 0.0
    boost: float = 1.0
    passage: dict = field(default_factory=dict)


class AliasCanonicalizer:
    """Appends ENT_<id> tokens when an alias surface form appears, so 'HP unit', 'Hydraulic Power Pack' and
    'HPU' all retrieve passages that use any other form. Only aliases from the DB (evidence-backed)."""
    def __init__(self, db: DatabaseManager):
        with db.conn() as c:
            rows = c.execute("SELECT alias_raw, entity_id, confidence FROM aliases").fetchall()
        self.items = sorted({(r["alias_raw"], r["entity_id"]) for r in rows if r["confidence"] >= 0.8 and len(r["alias_raw"]) >= 3},
                            key=lambda x: -len(x[0]))

    def entities(self, text: str) -> List[str]:
        """Entity ids whose evidence-backed alias appears in `text` (ordered by first appearance)."""
        low = text.lower()
        found = {}
        for alias, ent in self.items:
            a_low = alias.lower()
            n = re.sub(r"[\s_\-./]+", "", a_low)
            if len(n) <= 5 or re.fullmatch(r"[a-z]{1,3}\d+[a-z]?", n):
                pat = r"(?<![a-z0-9])" + r"[\s\-_.]*".join(re.escape(ch) for ch in re.sub(r"[\s\-_.]+", "", a_low)) + r"(?![a-z0-9]|[\-_.][a-z](?![a-z0-9]))"  # 'PS-04-A' is PS-04A, not PS-04
                m = re.search(pat, low)
            else:
                i = low.find(a_low)
                m = i >= 0 and type("M", (), {"start": lambda self, i=i: i})()
            if m and ent not in found:
                found[ent] = m.start()
        return sorted(found, key=found.get)

    def canonicalize(self, text: str) -> str:
        extra = ["ent_" + norm(e).lower() for e in self.entities(text)]
        return text + " " + " ".join(sorted(set(extra)))


class HybridIndex:
    def __init__(self, db: DatabaseManager, index_path: str = "data/index.pkl"):
        self.db, self.index_path = db, index_path
        self.canon = AliasCanonicalizer(db)
        self._load_or_build()

    # ---- build / persist ----
    def _passages(self) -> List[dict]:
        with self.db.conn() as c:
            q = """SELECT p.*, d.filename, d.rel_path, d.doc_code, d.applies_to, d.revision_id AS doc_rev
                   FROM passages p JOIN documents d ON d.doc_id=p.doc_id ORDER BY p.passage_id"""
            return [dict(r) for r in c.execute(q)]

    def _fingerprint(self, ps) -> str:
        h = hashlib.sha256()
        for p in ps:
            h.update((p["passage_id"] + p["content"]).encode())
        for a in self.canon.items:
            h.update(repr(a).encode())
        return h.hexdigest()

    def _load_or_build(self):
        self.ps = self._passages()
        fp = self._fingerprint(self.ps)
        if os.path.exists(self.index_path):
            try:
                with open(self.index_path, "rb") as f:
                    blob = pickle.load(f)
                if blob.get("fp") == fp:
                    self.tfidf, self.mat = blob["tfidf"], blob["mat"]
                    self._finish(); return
            except Exception:
                pass  # corrupt cache -> rebuild
        self.rebuild(fp)

    def _doc_text(self, p) -> str:
        # section/title context is indexed with the body so table rows & slides keep their context
        return self.canon.canonicalize(f"{p['filename']} {p.get('section_title') or ''} {p['content']}")

    def rebuild(self, fp: Optional[str] = None):
        self.ps = self._passages()
        fp = fp or self._fingerprint(self.ps)
        texts = [self._doc_text(p) for p in self.ps]
        self.tfidf = TfidfVectorizer(tokenizer=tokenize, lowercase=False, ngram_range=(1, 2), sublinear_tf=True, token_pattern=None)
        self.mat = self.tfidf.fit_transform(texts)
        os.makedirs(os.path.dirname(os.path.abspath(self.index_path)), exist_ok=True)
        with open(self.index_path, "wb") as f:
            pickle.dump({"fp": fp, "tfidf": self.tfidf, "mat": self.mat, "ids": [p["passage_id"] for p in self.ps]}, f)
        self._finish()

    def _finish(self):
        self.ids = [p["passage_id"] for p in self.ps]
        self.bm25 = BM25Okapi([tokenize(self._doc_text(p)) for p in self.ps])
        self.by_id = {p["passage_id"]: p for p in self.ps}

    # ---- search ----
    @staticmethod
    def _mm(x: np.ndarray) -> np.ndarray:
        lo, hi = float(x.min()), float(x.max())
        return (x - lo) / (hi - lo) if hi > lo else np.zeros_like(x)

    def search(self, query: str, k: int = config.TOP_K, mode: str = "hybrid", rerank: bool = config.RERANK,
               expand_aliases: bool = True, dedupe: bool = True, historical: Optional[bool] = None) -> List[Hit]:
        q = self.canon.canonicalize(query) if expand_aliases else query
        toks = tokenize(q)
        b = np.array(self.bm25.get_scores(toks)) if toks else np.zeros(len(self.ps))
        t = (self.mat @ self.tfidf.transform([q]).T).toarray().ravel()
        if mode == "bm25":
            s = self._mm(b)
        elif mode == "tfidf":
            s = self._mm(t)
        else:
            s = config.BM25_WEIGHT * self._mm(b) + config.TFIDF_WEIGHT * self._mm(t)
        hits = []
        hist = historical if historical is not None else bool(re.search(r"\b(before|prior|legacy|old|previous|earlier|3\.[01]\b|v1)\b", query, re.I))
        for i in np.argsort(-s)[: max(k * 4, 20)]:
            p = self.ps[i]
            boost = 1.0
            if rerank:
                boost *= {1: 1.10, 2: 1.0, 3: 0.92, 4: 0.75, 5: 0.35}.get(p["authority_level"], 0.9)
                if not hist and p["applies_to"] and "3.0" in p["applies_to"]:
                    boost *= 0.7  # superseded manual unless the question is about older revisions
                if p["extraction_method"] == "table" and re.search(r"\b(row|table|list|register|alias)\b", query, re.I):
                    boost *= 1.05
            hits.append(Hit(p["passage_id"], float(s[i]) * boost, float(b[i]), float(t[i]), boost, p))
        hits.sort(key=lambda h: -h.score)
        if dedupe:
            kept, sigs = [], []
            for h in hits:
                sig = set(tokenize(h.passage["content"]))
                if any(len(sig & o) / max(1, len(sig | o)) >= 0.85 for o in sigs):
                    continue
                kept.append(h); sigs.append(sig)
            hits = kept
        return hits[:k]
