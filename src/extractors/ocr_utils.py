"""OCR helpers. OCR output is NEVER trusted verbatim: raw text is kept in metadata and a
conservative ID-normalisation (PS-O4A -> PS-04A, 1/0 -> I/O) is applied to the indexed text."""
import re
from typing import Tuple
import pytesseract
from PIL import Image, ImageOps

_ID_FIX = [
    (re.compile(r"\b(PS|IV|TB|PLC|P)[-\s]?([0O]\d?[0-9OA]*)\b"), None),
]


def normalize_ocr_ids(text: str) -> str:
    def fix_tag(m):
        prefix, rest = m.group(1), m.group(2)
        rest = rest.replace("O", "0").replace("o", "0")
        return f"{prefix}-{rest}"
    out = re.sub(r"\b(PS|IV|TB|PLC)-([0-9OoA]{1,4}[A-Za-z]?)\b", fix_tag, text)
    out = re.sub(r"\b1/0\b", "I/O", out)
    out = re.sub(r"\bSerles\b", "Series", out)
    out = re.sub(r"\bAegls\b", "Aegis", out)
    # document codes: letter O inside the numeric tail -> 0 (AEG-DWG-E0O2 -> AEG-DWG-E02)
    out = re.sub(r"\b(AEG-[A-Z]{2,3}-[A-Z]?)([0-9O]{2,3})\b", lambda m: m.group(1) + m.group(2).replace("O", "0"), out)
    # heuristic (low confidence): OCR renders a rotated 'TB-7' as '¥B-7' / 'ya-7'
    out = re.sub(r"(?<![A-Za-z])[¥YyVv]B-(\d)\b", r"TB-\1", out)
    return out


def ocr_image(img: Image.Image) -> Tuple[str, float]:
    """Returns (text, mean word confidence 0-100). Raises on tesseract failure."""
    g = ImageOps.autocontrast(img.convert("L"))
    if min(g.size) < 1400:
        g = g.resize((g.width * 2, g.height * 2))
    text = pytesseract.image_to_string(g)
    data = pytesseract.image_to_data(g, output_type=pytesseract.Output.DICT)
    confs = [float(c) for c, t in zip(data["conf"], data["text"]) if str(t).strip() and float(c) >= 0]
    return text.strip(), (sum(confs) / len(confs) if confs else 0.0)
