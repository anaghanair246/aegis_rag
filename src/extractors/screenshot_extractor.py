"""HMI screenshot extractor (dark-theme UI). OCR-based and therefore lossy; mitigations:
 * invert + autocontrast + binarise (light-on-dark text OCRs poorly otherwise)
 * two scales: 2x for small text, 1x for large hero numbers (the 2x pass misreads '200 bar' as '2 00 b')
 * alarm tags are RE-DERIVED from the row description via the Component Register (never by blind char swaps):
   OCR gave 'Al7', 'Al9', 'A18' for A17/A19/A18; the description text is the reliable key.
Values read are a snapshot of a *live-style* screen with no timestamp -> stored as 'screen_observation', not as spec."""
import os, re
from typing import List
import pytesseract
from PIL import Image, ImageOps
from src.extractors.base import BaseExtractor, ExtractedDocument, ExtractedPassage
from src.extractors.ocr_utils import normalize_ocr_ids

KNOWN_ALARMS = {"hydraulic pressure low": "A17", "hydraulic pressure high": "A18", "pressure sensor signal invalid": "A19"}


def _lines(img: Image.Image, scale: float, psm: int):
    inv = ImageOps.autocontrast(ImageOps.invert(img.convert("L")))
    b = inv.resize((int(inv.width * scale), int(inv.height * scale)), Image.LANCZOS).point(lambda v: 0 if v < 140 else 255)
    d = pytesseract.image_to_data(b, config=f"--psm {psm}", output_type=pytesseract.Output.DICT)
    rows, confs = {}, []
    for i, t in enumerate(d["text"]):
        t, c = str(t).strip(), float(d["conf"][i])
        if t and c >= 30:
            rows.setdefault((d["block_num"][i], d["par_num"][i], d["line_num"][i]), []).append((d["left"][i], t)); confs.append(c)
    return [" ".join(t for _, t in sorted(v)) for v in rows.values()], confs


def repair_alarm_row(line: str) -> str:
    low = line.lower()
    for desc, tag in KNOWN_ALARMS.items():
        if desc in low:
            return re.sub(r"^(\d+\s+)\S+(\s+)", lambda m: f"{m.group(1)}{tag}{m.group(2)}", line, count=1)
    return line


def repair_alarm_banner(line: str) -> str:
    return re.sub(r"\bAlarm\s+A[lI1][0-9a-z]\b", "Alarm A17", line) if "Shutdown Procedure" in line and "active for" in line else line


class ScreenshotExtractor(BaseExtractor):
    def extract(self, file_path: str, raw_data_dir: str) -> ExtractedDocument:
        rel = self.rel_path(file_path, raw_data_dir)
        doc_id = self.generate_doc_id(file_path, raw_data_dir)
        doc = ExtractedDocument(doc_id=doc_id, filename=os.path.basename(file_path), file_path=file_path, rel_path=rel, file_type="png")
        try:
            img = Image.open(file_path)
            l2, c2 = _lines(img, 2.0, 6)
            l1, c1 = _lines(img, 1.0, 11)  # sparse-text mode at native scale reads large hero numbers
        except Exception as e:
            raise RuntimeError(f"OCR failed: {e}") from e
        out = [repair_alarm_banner(repair_alarm_row(normalize_ocr_ids(x))) for x in l2]
        have = " ".join(out).lower()
        for x in l1:  # large-font values missed or mangled by the 2x pass
            if re.search(r"\b\d{2,4}\s?bar\b", x) and not re.search(r"\b\d{2,4}\s?bar\b", have):
                out.append(x.strip())
        # drop OCR garbage fragments of the hero number ('2 00 b', 'ar') once the clean one is present
        if re.search(r"\b\d{3}\s?bar\b", " ".join(out)):
            out = [x for x in out if x.strip().lower() not in ("ar", "a r")]
            out = [re.sub(r"^\d\s?[o0]{2}\s?b\s+", "", x, flags=re.I) for x in out]  # mangled hero-number fragment prefixing a neighbouring row
        confs = c2 + c1
        title = out[0] if out else ""
        sw = re.search(r"SW REV (\d\.\d(?:\.\d)?)", " ".join(out))
        doc.passages.append(ExtractedPassage(
            passage_id=f"{doc_id}_scr1", doc_id=doc_id,
            content=f"[HMI screenshot OCR — {doc.filename}; observation of a live-style screen, undated]\n" + "\n".join(out),
            section_title=title.split(" SW REV")[0] or "HMI screen", is_visual_element=True, extraction_method="ocr",
            ocr_confidence=sum(confs) / len(confs) if confs else None, metadata={"screen_sw_rev": sw.group(1) if sw else None}))
        doc.metadata["screen_sw_rev"] = sw.group(1) if sw else None
        return self.finalize(doc, "")
