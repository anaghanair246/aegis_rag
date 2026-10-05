import hashlib
import os
import re
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from src import config

# Anchored patterns (the earlier version matched 'rev' inside words such as 'prevent').
DOC_CODE_RE = re.compile(r"\b(AEG-(?:OM|MM|AL|CR|GL|DWG)-[A-Z]?\d{2,3}(?:-[A-Z]\d{2})?|ECN-\d{3,5}|HF32-SDS-\d+)\b")
REV_RE = re.compile(r"(?<![Ss]oftware )\b(?:Revision|Rev\.?)\s+(\d+(?:\.\d+)*[A-Za-z]?)\b")
APPLIES_RE = re.compile(r"[Aa]pplies to software revisions?\s+([0-9.]+(?:\s+(?:and|or)\s+[0-9.]+)?(?:\s+and later)?(?:\s+only)?)")


class ExtractedPassage(BaseModel):
    passage_id: str
    doc_id: str
    content: str
    page_number: Optional[int] = None
    section_title: Optional[str] = None
    revision_id: Optional[str] = None
    authority_level: Optional[int] = None
    is_visual_element: bool = False
    extraction_method: str = "text"  # text | table | ocr | vector | structured
    ocr_confidence: Optional[float] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ExtractedDocument(BaseModel):
    doc_id: str
    filename: str
    file_path: str
    rel_path: str = ""
    file_type: str
    doc_code: Optional[str] = None
    revision_id: Optional[str] = None
    applies_to: Optional[str] = None
    authority_level: Optional[int] = None
    passages: List[ExtractedPassage] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class BaseExtractor(ABC):
    @staticmethod
    def rel_path(file_path: str, raw_data_dir: str) -> str:
        return os.path.normpath(os.path.relpath(file_path, start=raw_data_dir)).replace("\\", "/")

    @classmethod
    def generate_doc_id(cls, file_path: str, raw_data_dir: str) -> str:
        """Stable across machines/roots: hash of the dataset-relative path (so
        duplicate filenames in different folders do not collide)."""
        return hashlib.sha256(cls.rel_path(file_path, raw_data_dir).encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def trust_for(rel_path: str) -> Optional[int]:
        parts = rel_path.split("/")
        if parts[-1] in config.TRUST_OVERRIDES:
            return config.TRUST_OVERRIDES[parts[-1]]
        return config.TRUST_BY_FOLDER.get(parts[0]) if len(parts) > 1 else None

    @staticmethod
    def header_metadata(text: str) -> Dict[str, Optional[str]]:
        """Revision / doc code come ONLY from explicit header text; otherwise None (unknown)."""
        head = text[:600]
        # A doc code counts only if it is in the title line or in an explicit "Document <CODE>" statement;
        # codes merely *mentioned* later (e.g. "see ECN-1042") identify other documents.
        code = DOC_CODE_RE.search(text[:160])
        if not code:
            m = re.search(r"Document\s+(" + DOC_CODE_RE.pattern.strip("\\b") + r")", head)
            code = re.match(r"(.*)", m.group(1)) if m else None
        rev = REV_RE.search(head)
        app = APPLIES_RE.search(text[:1200])
        return {
            "doc_code": (code.group(1) if code else None),
            "revision_id": rev.group(1) if rev else None,
            "applies_to": app.group(1).strip() if app else None,
        }

    def finalize(self, doc: ExtractedDocument, header_text: str) -> ExtractedDocument:
        md = self.header_metadata(header_text)
        doc.doc_code, doc.revision_id, doc.applies_to = md["doc_code"], md["revision_id"], md["applies_to"]
        doc.authority_level = self.trust_for(doc.rel_path)
        for p in doc.passages:
            p.revision_id = doc.revision_id
            p.authority_level = doc.authority_level
        return doc

    @abstractmethod
    def extract(self, file_path: str, raw_data_dir: str) -> ExtractedDocument: ...
