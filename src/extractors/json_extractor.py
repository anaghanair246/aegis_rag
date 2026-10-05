import json
import os
from typing import Any, Iterator, Tuple
from src.extractors.base import BaseExtractor, ExtractedDocument, ExtractedPassage


def _leaves(obj: Any, prefix: str = "") -> Iterator[Tuple[str, Any]]:
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _leaves(v, f"{prefix}.{k}" if prefix else k)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _leaves(v, f"{prefix}[{i}]")
    else:
        yield prefix, obj


class JSONExtractor(BaseExtractor):
    def extract(self, file_path: str, raw_data_dir: str) -> ExtractedDocument:
        rel = self.rel_path(file_path, raw_data_dir)
        doc_id = self.generate_doc_id(file_path, raw_data_dir)
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            raise RuntimeError(f"JSON parse failed: {e}") from e
        doc = ExtractedDocument(doc_id=doc_id, filename=os.path.basename(file_path), file_path=file_path,
                                rel_path=rel, file_type="json")
        groups = data.items() if isinstance(data, dict) else [("root", data)]
        for n, (key, val) in enumerate(groups, start=1):
            leaves = list(_leaves(val, key))
            lines = [f"{p} = {json.dumps(v)}" for p, v in leaves]
            doc.passages.append(ExtractedPassage(
                passage_id=f"{doc_id}_k{n}", doc_id=doc_id,
                content=f"[JSON section '{key}' of {doc.filename}]\n" + "\n".join(lines),
                section_title=str(key), extraction_method="structured",
                metadata={"leaves": {p: v for p, v in leaves}}))
        # Only an explicit top-level revision key counts; firmware_version is NOT a document revision.
        if isinstance(data, dict):
            doc.metadata["firmware_version"] = (data.get("export_metadata") or {}).get("firmware_version")
            doc.metadata["export_timestamp"] = (data.get("export_metadata") or {}).get("export_timestamp")
        return self.finalize(doc, "")
