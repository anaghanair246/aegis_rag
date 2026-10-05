import json, os, shutil, sqlite3
import docx, openpyxl, pytest
from pptx import Presentation
from src.database import DatabaseManager
from src.extractors.base import BaseExtractor
from src.extractors.html_extractor import HTMLExtractor
from src.extractors.json_extractor import JSONExtractor
from src.extractors.docx_extractor import DOCXExtractor
from src.extractors.excel_extractor import ExcelExtractor
from src.extractors.pptx_extractor import PPTXExtractor
from src.extractors.png_extractor import PNGExtractor
from src.extractors.pdf_extractor import PDFExtractor
from src.extractors.ocr_utils import normalize_ocr_ids
from src.ingest import IngestionPipeline
from tests.conftest import RAW


@pytest.fixture
def tmp_dir(tmp_path):
    d = tmp_path / "raw"; d.mkdir(); return str(d)


def test_html_extractor_revision_only_from_explicit_header(tmp_dir):
    p = os.path.join(tmp_dir, "a.html")
    open(p, "w").write("<html><body><h1>Manual</h1><p>We must prevent leaks.</p></body></html>")
    d = HTMLExtractor().extract(p, tmp_dir)
    assert d.revision_id is None  # 'prevent' must not yield a revision (old regex bug)
    open(p, "w").write("<html><body><h1>Manual AEG-OM-700, Revision 7</h1></body></html>")
    d = HTMLExtractor().extract(p, tmp_dir)
    assert d.revision_id == "7" and d.doc_code == "AEG-OM-700"


def test_excel_xlsx_and_xls(tmp_dir):
    x = os.path.join(tmp_dir, "s.xlsx")
    wb = openpyxl.Workbook(); ws = wb.active; ws.title = "H"; ws.append(["ID", "Val"]); ws.append(["PS-04", "200 bar"]); wb.save(x)
    d = ExcelExtractor().extract(x, tmp_dir)
    assert d.file_type == "xlsx" and "ID: PS-04" in d.passages[0].content and "Sheet: H" in d.passages[0].content
    import xlwt
    xl = os.path.join(tmp_dir, "s.xls")
    w = xlwt.Workbook(); sh = w.add_sheet("L"); sh.write(0, 0, "ID"); sh.write(0, 1, "Val"); sh.write(1, 0, "IV-21"); sh.write(1, 1, "open"); w.save(xl)
    d = ExcelExtractor().extract(xl, tmp_dir)
    assert d.file_type == "xls" and "ID: IV-21" in d.passages[0].content


def test_docx_tables_and_headings(tmp_dir):
    p = os.path.join(tmp_dir, "d.docx")
    d = docx.Document(); d.add_heading("Section One", 1); d.add_paragraph("Body text."); t = d.add_table(rows=2, cols=2)
    t.cell(0, 0).text, t.cell(0, 1).text, t.cell(1, 0).text, t.cell(1, 1).text = "Term", "Def", "HPU", "Power unit"; d.save(p)
    out = DOCXExtractor().extract(p, tmp_dir)
    assert any(x.section_title == "Section One" and x.content == "Body text." for x in out.passages)
    assert any("Term: HPU | Def: Power unit" in x.content for x in out.passages)  # tables not dropped


def test_pptx_table_and_slide_number(tmp_dir):
    p = os.path.join(tmp_dir, "p.pptx")
    prs = Presentation(); s = prs.slides.add_slide(prs.slide_layouts[5]); s.shapes.title.text = "Title"
    prs.save(p)
    out = PPTXExtractor().extract(p, tmp_dir)
    assert out.passages[0].page_number == 1 and "Title" in out.passages[0].content


def test_json_structures(tmp_dir):
    for name, data in (("o.json", {"a": {"b": 1}}), ("l.json", [1, {"x": 2}]), ("s.json", 5)):
        p = os.path.join(tmp_dir, name); json.dump(data, open(p, "w"))
        assert JSONExtractor().extract(p, tmp_dir).passages
    p = os.path.join(tmp_dir, "bad.json"); open(p, "w").write("{oops")
    with pytest.raises(RuntimeError):
        JSONExtractor().extract(p, tmp_dir)


def test_firmware_version_is_not_a_document_revision():
    d = JSONExtractor().extract(f"{RAW}/configuration/configuration_export.json", RAW)
    assert d.revision_id is None and d.metadata["firmware_version"] == "3.2.1"


def test_doc_ids_stable_across_roots_and_no_filename_collision(tmp_path):
    ids = []
    for root in ("r1", "r2"):
        for sub in ("a", "b"):
            f = tmp_path / root / sub / "doc.json"; f.parent.mkdir(parents=True, exist_ok=True); f.write_text("{}")
        ids.append({s: BaseExtractor.generate_doc_id(str(tmp_path / root / s / "doc.json"), str(tmp_path / root)) for s in "ab"})
    assert ids[0] == ids[1]            # stable across roots
    assert ids[0]["a"] != ids[0]["b"]  # same filename, different folder -> different id


def test_db_rollback_leaves_no_partial_data(tmp_path):
    db = DatabaseManager(str(tmp_path / "t.db"))
    doc = {"doc_id": "d1", "filename": "f", "file_path": "f", "file_type": "json"}
    good = {"passage_id": "p1", "doc_id": "d1", "content": "x"}
    bad = {"passage_id": "p2", "doc_id": "d1"}  # missing content -> KeyError mid-transaction
    with pytest.raises(Exception):
        db.save_ingested_data(doc, [good, bad])
    assert db.get_document_count() == 0 and db.get_passage_count() == 0


def test_reingestion_removes_stale_passages_and_keeps_old_data_on_failure(tmp_path):
    db = DatabaseManager(str(tmp_path / "t.db"))
    doc = {"doc_id": "d1", "filename": "f", "file_path": "f", "file_type": "json"}
    db.save_ingested_data(doc, [{"passage_id": "p1", "doc_id": "d1", "content": "old"}, {"passage_id": "p2", "doc_id": "d1", "content": "old2"}])
    db.save_ingested_data(doc, [{"passage_id": "p3", "doc_id": "d1", "content": "new"}])
    assert db.get_passage_count() == 1
    with pytest.raises(Exception):
        db.save_ingested_data(doc, [{"passage_id": "p9", "doc_id": "d1"}])  # failing re-ingest must not wipe good data
    assert db.get_passage_count() == 1


def test_corrupt_unsupported_and_empty_files_reported_not_fatal(tmp_path):
    raw = tmp_path / "raw"; (raw / "x").mkdir(parents=True)
    (raw / "x" / "bad.pdf").write_bytes(b"not a pdf")
    (raw / "x" / "note.txt").write_text("hi")
    (raw / "x" / "ok.json").write_text('{"a": 1}')
    s = IngestionPipeline(str(tmp_path / "t.db"), str(tmp_path / "l.log")).run(str(raw), build_knowledge=False)
    assert any("bad.pdf" in f["file"] for f in s["failed_files"])
    assert any("note.txt" in f for f in s["unsupported_files"])
    assert any("ok.json" in f for f in s["processed_files"])


def test_ocr_id_normalisation():
    assert "PS-04A" in normalize_ocr_ids("PS-O4A")
    assert normalize_ocr_ids("AEG-DWG-E0O2") == "AEG-DWG-E002"  # known limitation: OCR 'E02' read as 'E0O2' -> E002 (see README)
    assert "I/O" in normalize_ocr_ids("PLC-03 1/0 RACK")


def test_ocr_failure_is_recorded(monkeypatch):
    import src.extractors.pdf_extractor as m
    monkeypatch.setattr(m, "ocr_image", lambda img: (_ for _ in ()).throw(RuntimeError("tesseract down")))
    d = PDFExtractor().extract(f"{RAW}/scans/scanned_appendix_calibration.pdf", RAW)
    assert d.metadata.get("ocr_errors") and not d.passages


# ---------- real dataset ----------
def test_real_dataset_ingests_everything(real_env):
    s = real_env["stats"]
    assert not s["failed_files"] and not s["unsupported_files"] and not s["empty_text_files"]
    assert s["documents"] == 20 and s["passages"] > 50
    assert s["knowledge"]["rules_unmatched"] == []


def test_real_scan_ocr_recovers_key_values(real_env):
    with real_env["db"].conn() as c:
        t = c.execute("SELECT content FROM passages p JOIN documents d USING(doc_id) WHERE rel_path LIKE '%scanned%'").fetchone()[0]
    assert "PS-04A" in t and "200 bar" in t and "No calibration interval" in t


def test_real_metadata_not_fabricated(real_env):
    with real_env["db"].conn() as c:
        rows = {r["rel_path"]: dict(r) for r in c.execute("SELECT * FROM documents")}
    assert rows["manuals/operator_manual.pdf"]["revision_id"] == "4"
    assert rows["manuals/maintenance_manual.pdf"]["revision_id"] == "3"
    assert rows["reference/component_register.xlsx"]["revision_id"] is None
    assert rows["scans/scanned_appendix_calibration.pdf"]["revision_id"] is None
    assert rows["manuals/legacy_manual_v1.html"]["revision_id"] == "1"
    assert rows["manuals/legacy_manual_v1.html"]["authority_level"] == 4


def test_real_diagram_topology_from_geometry(real_env):
    with real_env["db"].conn() as c:
        edges = [dict(r) for r in c.execute("SELECT * FROM edges WHERE kind LIKE 'purple%'")]
    pairs = {frozenset((e["src"], e["dst"])) for e in edges}
    assert pairs == {frozenset(("PLC-03 (HCS Controller)", "PS-04A")), frozenset(("PLC-03 (HCS Controller)", "IV-21"))}


def test_real_rotated_label_recovered(real_env):
    with real_env["db"].conn() as c:
        t = c.execute("SELECT content FROM passages p JOIN documents d USING(doc_id) WHERE rel_path LIKE '%electrical.png'").fetchone()[0]
    assert "TB-7" in t
