"""Ingestion pipeline: extract -> persist (atomic per document) -> build knowledge layer."""
import logging
import os
import time
import json
from typing import Dict, Any
from src import config
from src.database import DatabaseManager
from src.extractors.pdf_extractor import PDFExtractor
from src.extractors.docx_extractor import DOCXExtractor
from src.extractors.html_extractor import HTMLExtractor
from src.extractors.excel_extractor import ExcelExtractor
from src.extractors.pptx_extractor import PPTXExtractor
from src.extractors.json_extractor import JSONExtractor
from src.extractors.png_extractor import PNGExtractor
from src.extractors.screenshot_extractor import ScreenshotExtractor

log = logging.getLogger("aegis.ingest")


def _setup_logging(path: str):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    if not logging.getLogger().handlers:
        logging.basicConfig(filename=path, filemode="a", level=logging.INFO,
                            format="%(asctime)s - %(levelname)s - %(message)s")


class IngestionPipeline:
    def __init__(self, db_path: str = config.DB_PATH, log_path: str = config.LOG_PATH):
        _setup_logging(log_path)
        self.db = DatabaseManager(db_path)
        pdf, ex = PDFExtractor(), ExcelExtractor()
        self.shot = ScreenshotExtractor()
        self.extractors = {".pdf": pdf, ".docx": DOCXExtractor(), ".html": HTMLExtractor(), ".htm": HTMLExtractor(),
                           ".xlsx": ex, ".xls": ex, ".pptx": PPTXExtractor(), ".json": JSONExtractor(),
                           ".png": PNGExtractor()}

    def run(self, raw_data_dir: str = config.RAW_DIR, build_knowledge: bool = True) -> Dict[str, Any]:
        t0 = time.time()
        stats: Dict[str, Any] = {"processed_files": [], "failed_files": [], "ocr_failed_files": [],
                                 "empty_text_files": [], "unsupported_files": [], "ocr_used_files": [],
                                 "per_file_seconds": {}}
        if not os.path.isdir(raw_data_dir):
            raise FileNotFoundError(raw_data_dir)
        for root, _, files in os.walk(raw_data_dir):
            for fn in sorted(files):
                path = os.path.join(root, fn)
                rel = os.path.relpath(path, raw_data_dir)
                ext = os.path.splitext(fn)[1].lower()
                if ext not in self.extractors:
                    stats["unsupported_files"].append(rel)
                    log.warning("unsupported file type: %s", rel)
                    continue
                f0 = time.time()
                try:
                    ex = self.extractors[ext]
                    if ext == ".png" and (rel.replace("\\", "/").startswith("screenshots/") or fn.lower().startswith("screen_")):
                        ex = self.shot
                    doc = ex.extract(path, raw_data_dir)
                    if doc.metadata.get("ocr_errors"):
                        stats["ocr_failed_files"].append({"file": rel, "errors": doc.metadata["ocr_errors"]})
                    if doc.metadata.get("ocr_pages") or doc.file_type == "png":
                        stats["ocr_used_files"].append(rel)
                    if not any(p.content.strip() for p in doc.passages):
                        stats["empty_text_files"].append(rel)
                        log.warning("no text extracted: %s", rel)
                        continue
                    d = doc.model_dump(exclude={"passages"})
                    self.db.save_ingested_data(d, [p.model_dump() for p in doc.passages])
                    stats["processed_files"].append(rel)
                    log.info("ingested %s (%d passages)", rel, len(doc.passages))
                except Exception as e:  # one bad file must not abort the run
                    stats["failed_files"].append({"file": rel, "error": f"{type(e).__name__}: {e}"})
                    log.error("failed %s: %s", rel, e)
                stats["per_file_seconds"][rel] = round(time.time() - f0, 3)
        stats["ingest_seconds"] = round(time.time() - t0, 3)
        if build_knowledge:
            from src.knowledge.build import build_knowledge_layer
            t1 = time.time()
            stats["knowledge"] = build_knowledge_layer(self.db)
            stats["knowledge_seconds"] = round(time.time() - t1, 3)
        stats["documents"] = self.db.count("documents")
        stats["passages"] = self.db.count("passages")
        stats["total_seconds"] = round(time.time() - t0, 3)
        with self.db.conn() as c:
            c.execute("INSERT INTO ingestion_runs (seconds, stats) VALUES (?,?)", (stats["total_seconds"], json.dumps(stats)))
        return stats


if __name__ == "__main__":
    import sys
    s = IngestionPipeline().run(sys.argv[1] if len(sys.argv) > 1 else config.RAW_DIR)
    print(json.dumps({k: v for k, v in s.items() if k != "per_file_seconds"}, indent=2))
