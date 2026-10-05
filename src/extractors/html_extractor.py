import os
from bs4 import BeautifulSoup
from src.extractors.base import BaseExtractor, ExtractedDocument, ExtractedPassage


class HTMLExtractor(BaseExtractor):
    def extract(self, file_path: str, raw_data_dir: str) -> ExtractedDocument:
        rel = self.rel_path(file_path, raw_data_dir)
        doc_id = self.generate_doc_id(file_path, raw_data_dir)
        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                soup = BeautifulSoup(f.read(), "html.parser")
        except Exception as e:
            raise RuntimeError(f"HTML read failed: {e}") from e
        for t in soup(["style", "script"]):
            t.decompose()
        out = ExtractedDocument(doc_id=doc_id, filename=os.path.basename(file_path), file_path=file_path,
                                rel_path=rel, file_type="html")
        heading, n, header_parts = "Overview", 0, []
        seen_tables = set()
        for tag in soup.find_all(["h1", "h2", "h3", "p", "li", "tr", "div"]):
            if tag.name == "div" and "banner" not in (tag.get("class") or []) and "warn" not in (tag.get("class") or []):
                continue
            if tag.name == "tr":
                cells = [c.get_text(" ", strip=True) for c in tag.find_all(["td", "th"])]
                if tag.find("th") or not any(cells):
                    continue
                hdr = [c.get_text(" ", strip=True) for c in tag.find_parent("table").find("tr").find_all("th")]
                text = "[Table row] " + " | ".join(f"{h}: {v}" for h, v in zip(hdr, cells)) if hdr else " | ".join(cells)
            else:
                text = tag.get_text(" ", strip=True)
            if not text:
                continue
            if tag.name in ("h1", "h2", "h3"):
                heading = text
            if len(header_parts) < 6 and tag.name != "li":
                header_parts.append(text)
            n += 1
            out.passages.append(ExtractedPassage(passage_id=f"{doc_id}_s{n}", doc_id=doc_id, content=text,
                                                 section_title=heading))
        title = soup.title.get_text(strip=True) if soup.title else ""
        # Header text is taken from the document's own explicit statements (banner/meta), never guessed.
        return self.finalize(out, (title + "\n" + "\n".join(header_parts)))
