import os
from typing import List
import pdfplumber
from pdf2image import convert_from_path
from src.extractors.base import BaseExtractor, ExtractedDocument, ExtractedPassage
from src.extractors.ocr_utils import normalize_ocr_ids, ocr_image
from src.extractors.diagram import extract_topology


class PDFExtractor(BaseExtractor):
    def __init__(self, min_text_len_per_page: int = 30, ocr_dpi: int = 200):
        self.min_text = min_text_len_per_page
        self.dpi = ocr_dpi

    def extract(self, file_path: str, raw_data_dir: str) -> ExtractedDocument:
        rel = self.rel_path(file_path, raw_data_dir)
        doc_id = self.generate_doc_id(file_path, raw_data_dir)
        doc = ExtractedDocument(doc_id=doc_id, filename=os.path.basename(file_path), file_path=file_path,
                                rel_path=rel, file_type="pdf")
        ocr_errors: List[str] = []
        ocr_pages: List[int] = []
        header_text = ""
        try:
            pdf = pdfplumber.open(file_path)
        except Exception as e:
            raise RuntimeError(f"PDF open failed: {e}") from e
        with pdf:
            for n, page in enumerate(pdf.pages, start=1):
                text = (page.extract_text() or "").strip()
                method, conf = "text", None
                if len(text) < self.min_text:
                    try:
                        img = convert_from_path(file_path, dpi=self.dpi, first_page=n, last_page=n)[0]
                        raw, conf = ocr_image(img)
                        if raw:
                            text, method = normalize_ocr_ids(raw), "ocr"
                            ocr_pages.append(n)
                    except Exception as e:  # recorded, surfaced in pipeline stats; never silent
                        ocr_errors.append(f"page {n}: {e}")
                if not text:
                    continue
                if n == 1:
                    header_text = text
                doc.passages.append(ExtractedPassage(
                    passage_id=f"{doc_id}_p{n}", doc_id=doc_id, content=text, page_number=n,
                    section_title=f"Page {n}", extraction_method=method, ocr_confidence=conf,
                    metadata={"raw_ocr_differs": method == "ocr"}))
                if method == "text":
                    # tables -> row-level passages (header-aware) so table cells keep their column meaning
                    try:
                        for ti, tbl in enumerate(page.extract_tables() or [], start=1):
                            if not tbl or len(tbl) < 2:
                                continue
                            hdr = [(c or "").replace("\n", " ").strip() for c in tbl[0]]
                            for ri, row in enumerate(tbl[1:], start=1):
                                cells = [(c or "").replace("\n", " ").strip() for c in row]
                                if not any(cells):
                                    continue
                                body = " | ".join(f"{h or f'Col{i+1}'}: {v}" for i, (h, v) in enumerate(zip(hdr, cells)) if v)
                                doc.passages.append(ExtractedPassage(
                                    passage_id=f"{doc_id}_p{n}_t{ti}r{ri}", doc_id=doc_id,
                                    content=f"[Table {ti}, row {ri}] {body}", page_number=n,
                                    section_title=f"Page {n} table {ti}", extraction_method="table"))
                    except Exception as e:
                        doc.metadata.setdefault("table_errors", []).append(f"page {n}: {e}")
                    # vector diagram topology
                    try:
                        nodes, edges, legend = extract_topology(page)
                        for ei, e in enumerate(edges, start=1):
                            doc.passages.append(ExtractedPassage(
                                passage_id=f"{doc_id}_p{n}_edge{ei}", doc_id=doc_id,
                                content=(f"[Diagram connection] '{e['a']}' is connected to '{e['b']}' by a "
                                         f"{e['color']} line = {e['meaning']}."),
                                page_number=n, section_title="Diagram topology", is_visual_element=True,
                                extraction_method="vector", metadata=e))
                    except Exception as e:
                        doc.metadata.setdefault("diagram_errors", []).append(f"page {n}: {e}")
        doc.metadata["ocr_pages"] = ocr_pages
        if ocr_errors:
            doc.metadata["ocr_errors"] = ocr_errors
        return self.finalize(doc, header_text)
