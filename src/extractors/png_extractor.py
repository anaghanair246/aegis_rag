import os
from PIL import Image
from src.extractors.base import BaseExtractor, ExtractedDocument, ExtractedPassage
from src.extractors.ocr_utils import normalize_ocr_ids
import pytesseract


class PNGExtractor(BaseExtractor):
    """OCR only. This recovers LABELS, not connectivity: topology of raster diagrams is explicitly
    NOT extracted (documented limitation). Rotated / low-contrast labels get extra rotated passes."""
    ANGLES = (0, 8, -8)

    def extract(self, file_path: str, raw_data_dir: str) -> ExtractedDocument:
        rel = self.rel_path(file_path, raw_data_dir)
        doc_id = self.generate_doc_id(file_path, raw_data_dir)
        doc = ExtractedDocument(doc_id=doc_id, filename=os.path.basename(file_path), file_path=file_path,
                                rel_path=rel, file_type="png")
        try:
            img = Image.open(file_path).convert("L")
            from PIL import ImageOps
            img = ImageOps.autocontrast(img)
            seen, lines, confs = set(), [], []
            for ang in self.ANGLES:
                im = img.rotate(ang, expand=True, fillcolor=255) if ang else img
                im = im.resize((im.width * 2, im.height * 2))
                d = pytesseract.image_to_data(im, output_type=pytesseract.Output.DICT)
                cur, buf = None, []
                for i, t in enumerate(d["text"]):
                    t = str(t).strip()
                    c = float(d["conf"][i])
                    if not t or c < (40 if ang == 0 else 75):
                        continue
                    key = (d["block_num"][i], d["par_num"][i], d["line_num"][i])
                    if key != cur and buf:
                        lines.append((ang, " ".join(buf))); buf = []
                    cur = key
                    buf.append(t); confs.append(c)
                if buf:
                    lines.append((ang, " ".join(buf)))
            # extra pass for light-grey rotated labels: binarise hard, rotate, sparse-text mode.
            hard = img.point(lambda v: 0 if v < 235 else 255)
            hard = hard.rotate(-8, expand=True, fillcolor=255).resize((hard.width * 3, hard.height * 3))
            d = pytesseract.image_to_data(hard, config="--psm 11", output_type=pytesseract.Output.DICT)
            toks = [(str(t).strip(), float(c)) for t, c in zip(d["text"], d["conf"]) if str(t).strip() and float(c) >= 40]
            import re as _re
            cand = " ".join(t for t, _ in toks)
            m = _re.search(r"([¥YyVvT]B-\d\s+REF:?[^\n]{3,40})", cand)
            if m:
                lines.append((-8, m.group(1)))
        except Exception as e:
            raise RuntimeError(f"OCR failed: {e}") from e
        uniq, out_lines = set(), []
        import re as _re
        for ang, ln in lines:
            norm = normalize_ocr_ids(ln)
            if ang != 0 and len(_re.findall(r"\b[A-Z]{2,}\b", norm)) < 2:
                continue  # rotated-pass lines are accepted only when clearly label-like
            k = "".join(ch for ch in norm.lower() if ch.isalnum())
            if len(k) < 3 or any(k in u for u in uniq):
                continue
            uniq.add(k); out_lines.append(norm)
        text = "\n".join(out_lines)
        if text:
            doc.passages.append(ExtractedPassage(
                passage_id=f"{doc_id}_img1", doc_id=doc_id,
                content="[OCR of raster diagram: labels only, connectivity NOT recovered]\n" + text,
                section_title="OCR labels", is_visual_element=True, extraction_method="ocr",
                ocr_confidence=sum(confs) / len(confs) if confs else None))
        doc.metadata["topology_recovered"] = False
        out = self.finalize(doc, "")  # identifiers from OCR'd headers are not trusted -> doc_code stays unknown
        doc.metadata["ocr_title_line"] = out_lines[0] if out_lines else None
        return out
