import os
import docx
from docx.table import Table
from docx.text.paragraph import Paragraph
from src.extractors.base import BaseExtractor, ExtractedDocument, ExtractedPassage


class DOCXExtractor(BaseExtractor):
    def extract(self, file_path: str, raw_data_dir: str) -> ExtractedDocument:
        rel = self.rel_path(file_path, raw_data_dir)
        doc_id = self.generate_doc_id(file_path, raw_data_dir)
        try:
            d = docx.Document(file_path)
        except Exception as e:
            raise RuntimeError(f"DOCX open failed: {e}") from e
        out = ExtractedDocument(doc_id=doc_id, filename=os.path.basename(file_path), file_path=file_path,
                                rel_path=rel, file_type="docx")
        heading, n, header_parts = "Overview", 0, []
        # iterate body in document order so tables stay with their section (the old code skipped tables entirely)
        for child in d.element.body.iterchildren():
            tag = child.tag.rsplit("}", 1)[-1]
            if tag == "p":
                p = Paragraph(child, d)
                text = p.text.strip()
                if not text:
                    continue
                if len(header_parts) < 4:
                    header_parts.append(text)
                if p.style is not None and p.style.name.lower().startswith(("heading", "title")):
                    heading = text
                    continue
                n += 1
                out.passages.append(ExtractedPassage(passage_id=f"{doc_id}_p{n}", doc_id=doc_id, content=text,
                                                     section_title=heading))
            elif tag == "tbl":
                t = Table(child, d)
                rows = [[c.text.strip() for c in r.cells] for r in t.rows]
                if len(rows) < 2:
                    continue
                hdr = rows[0]
                for ri, r in enumerate(rows[1:], start=1):
                    body = " | ".join(f"{h or f'Col{i+1}'}: {v}" for i, (h, v) in enumerate(zip(hdr, r)) if v)
                    n += 1
                    out.passages.append(ExtractedPassage(
                        passage_id=f"{doc_id}_t{n}", doc_id=doc_id, content=f"[Table row {ri}] {body}",
                        section_title=heading, extraction_method="table"))
        return self.finalize(out, "\n".join(header_parts))
