# Aegis Series-7 HCS — Knowledge Ingestion & Evidence-Grounded Q&A

<h1 align="center">
## 🚀 Live Demo

👉 **[TRY THE LIVE AEGIS Q&A APP →](https://aegisrag-g65yxpjn4yewr2tjxh2fu9.streamlit.app/) **

Offline-by-default RAG-style system: heterogeneous docs → provenance-preserving knowledge layer (SQLite) →
hybrid retrieval → **rule-routed, fact-grounded answers** with claims, evidence, conflicts and "could not determine".
Every number below was measured by the scripts in this repo; see `eval/results*.md`.
</h1>
## Quick start
```bash
pip install -r requirements.txt            # also needs system tesseract + poppler (pdftoppm)
python pipeline.py data/raw                # ingest + knowledge layer + index  (~14 s on this dataset, OCR dominates)
python -m pytest -q                        # 77 tests (incl. full run on the real dataset)
python -m eval.run_eval                    # writes eval/results.{json,md}
streamlit run app/streamlit_app.py         # UI (not launched in the build sandbox)
python -c "from src.qa.engine import *; from src.database import DatabaseManager as D; print(QAEngine(D('data/aegis_rag.db')).ask('Is PS-04 the same as PS-04A?').answer)"
```
Config: env vars in `.env.example` (`src/config.py`). Troubleshooting: `tesseract`/`pdftoppm` missing → OCR errors are
recorded per file in the ingestion stats (`ocr_failed_files`), never silent; delete `data/index.pkl` to force an index rebuild.

## Architecture
```
raw files ─► extractors (pdf|docx|html|xlsx/xls|pptx|json|png|hmi-screenshot) ─► passages + doc metadata ──┐  (atomic per-doc txn, re-ingest = replace)
   OCR (tesseract) only for scanned pages / PNG;  vector-geometry parser for PDF diagrams    ▼
                                                              SQLite: documents, passages
                                              knowledge builder (rules) ─► entities, aliases, facts(version-scoped), edges
                                                              │                              │
                  HybridIndex (BM25 + TF-IDF, alias tokens, trust rerank, dedupe)          FactStore
                                                              └──────────► QAEngine ◄──────────┘
                       intent router → handler → Answer{claims+evidence, conflicts, unknowns, assumptions, status}
                                  └ unmatched → fact_lookup → extractive → (optional LLM, validated) → abstain
                                                              ▼
                                            Streamlit UI  /  eval harness  /  CLI
```
Deterministic vs model-based: **everything is deterministic/rule-based except** tesseract OCR (a model) and the optional LLM
fallback (off by default, unverified). Rationale: facts in this corpus are few, safety-relevant and version-scoped; rules give
exact provenance and cannot invent a unit or value. Cost: coverage is limited to patterns I wrote (see Limitations).

## Representation (see `src/database.py`)
`documents` (doc_code, revision_id, applies_to, authority_level) · `passages` (page/slide/sheet-row, extraction_method, ocr_confidence,
is_visual_element) · `entities`/`aliases` (method + confidence + source passage) · `facts` (subject, predicate, value, unit,
**sw_from/sw_before scope**, status asserted|superseded|unverified|gap, trust, passage_id) · `edges` (diagram connectivity, colour→legend meaning).
* **Revision / doc code**: only from explicit header text (anchored regexes), else NULL. `firmware_version` in JSON is *not* a document revision.
* **Authority**: no document states one, so it is a *documented policy by folder* (`config.TRUST_BY_FOLDER`): ECN 1 > manuals/reference/config/diagrams 2 > scan/slides 3 > legacy v1 & field notes 4 > SDS 5.
* **Newer ≠ authoritative**: scope is by software revision. 180 bar (<3.2) and 200 bar (≥3.2) are *both* true in their scopes; legacy v1 says 180 but is marked superseded; the 175 bar field note is surfaced as an unverified contradiction, never adopted.

## Entity resolution decisions
Merged only on explicit evidence (register aliases, "all three terms refer to the same assembly", wiring-note "described elsewhere as PS-04A"). Formatting variants (`PS04A`, `P04A`) normalise. **Not merged**: PS-04 vs PS-04A (supersedes edge, ECN says not form-fit-function), PS-04/PS-04A vs PS-40 (one char apart; register says unrelated). `hydraulic pack` is an alias from the training slide only (confidence 0.8, answers carry a caveat). `sensor_ps04a_threshold_bar` → PS-04A normal-pressure setpoint is an **inference** (id + value + version scope) and is labelled as such.

## Diagrams: OCR ≠ understanding
* Vector PDFs (hydraulic, wiring): topology recovered **from geometry** (shapes, line endpoints, stroke colour → the drawing's own legend). Result: purple control lines PLC-03↔PS-04A, PLC-03↔IV-21; the PLC-03↔HPU line is *grey* (= hydraulic path per legend), so it is reported as ambiguous rather than counted.
* Raster electrical PNG: OCR of **labels only** (incl. a rotated low-contrast `TB-7 REF: PRESSURE XDCR LOOP` via extra pass). Connectivity is **not** extracted. No vision model was used.

## HMI screenshots (Q13 and related)
`screen_03_diagnostics.png` shows the tag **`P.S.04-A`** (the screen says it is the tag "as printed on the physical unit label"). It resolves to register entity **PS-04A** by *separator-only normalisation* — not listed in the register's aliases, so the answer is `ANSWERED_WITH_CAVEATS` and says so; corroborated by matching last-calibrated date (2026-01-09, scanned record), firmware 3.2.1 (config export) and sw rev 3.2. `PS-04` is still never matched by `P.S.04-A` (a boundary bug that would have matched both was found by a test and fixed).
`screen_02_alarms.png`: A17 ACTIVE for 14 s vs the 10 s threshold → Shutdown Procedure 4.7 required (Maintenance Manual §4, cited). The answer also flags what it cannot resolve: the home screen shows 200 bar "NORMAL" while A17 (<150 bar) is active — likely different capture times, undetermined.
OCR approach: invert+binarise; 2× pass for small text and native-scale sparse pass for the large hero value (`200 bar` was read as `2 00 b` otherwise).

## Alarm records (procedure-aware path, `src/qa/alarms.py`)
An alarm table row is stored and answered as ONE record (condition, causes, required action as a whole cell, `*` footnote, section references). Questions are split into **facets** — meaning / causes / action / restart — detected generically (no alarm ids or questions hardcoded); only the asked facets are answered, always from the whole record, and unasked facets are never mixed in. Status/confidence come from facet coverage: all asked facets documented → `ANSWERED`; a gap (e.g. the referenced manual section is in the package but contains no replacement steps; footnote unresolved) → `ANSWERED_WITH_CAVEATS`; nothing documented → `INSUFFICIENT_EVIDENCE`.
Guards on every answer that touches an alarm: **completeness** (an action answer must contain the full stored cell, else it is repaired and downgraded) and **cross-contamination** (a stop/restart instruction may only be stated if the cited evidence is that same alarm's record; otherwise the draft is discarded and rebuilt). Build-time **integrity check** compares every table cell against the independent page text layer and flags rows visible in text but missing from the table (`integrity_warnings`, currently empty on the real dataset).
Unverifiable ids (`A-1042`, `A05`) abstain with a specific explanation (not in AEG-AL-700; ranges A01–A16/A20–A34 live in AEG-AL-701, not provided; a same-number document such as ECN-1042 is a change notice, never an alarm). "Restart the HPU" is no longer routed to the controller-reset rule.
**Source-fidelity note:** in the supplied AEG-AL-700 Rev 5, A19's required action is only "Replace sensor per Maintenance Manual Section 6." The "Stop the HPU. Do not restart until pressure relief is verified." text is **A18's** row (verified on the rendered page, raw table, and a search of all 20 documents). The system therefore reports no stop/restart instruction for A19 and says so. A synthetic multi-instruction table test proves a multi-sentence cell survives PDF → fact → answer intact if a document does contain one.

## Results (measured; details and per-question table in `eval/results.md`)
| Set | What it is | n | end-to-end correct | halluc. | false abstain | abstain recall |
|---|---|---|---|---|---|---|
| dev | the 23 assignment questions (router built/tuned on these) | 23 | 1.00 | 0.00 | 0 | 1.00 |
| para | my paraphrases, first run untuned: **0.389** (`results_run1_untuned`); after fixes: | 18 | 0.944 | 0.00 | 1 | 1.00 |
| scr | 6 HMI-screenshot Qs written *with* the screenshot handler; 2 failed first run (a routing bug and a missing value), fixed after seeing them → **tuned, not held-out** | 6 | 1.00 | 0.00 | 0 | 1.00 |
| alarm | 10 alarm facet / restart / unverified-id Qs written *with* the alarm fix (includes leak checks: A18 wording must never appear in A19 answers) → **tuned, not held-out** | 10 | 1.00 | 0.00 | 0 | 1.00 |
| held | fresh 15 Qs, first run before generic fallbacks: **0.267** (`results_run3_heldout`); after fallbacks (now tuned-on, *not* held-out): | 15 | 0.667 (0.467 before the alarm fix; H3/H7/H10 are alarm questions) | 0.00 | 3 | 1.00 |

**Honest reading:** the 1.00 on dev is *not* evidence of generalisation. The only unbiased generalisation numbers are the first untuned runs (0.389, 0.267): the router is brittle to phrasing; failures were *abstentions*, not wrong answers (hallucination 0 in every run, by the checker's definition). Retrieval (Hit@5 dev 0.94 / para 0.64 / held 0.57 for the default config) is weak; the alias-expansion and rerank layers helped dev but **not** held-out (see table in results) — I did not verify they are net-positive. Answer layer success comes from the fact store, not retrieval.
Latency: p50 total ≈ 6 ms per query (no LLM; ~13 ms on screenshot questions); ingestion 13.5 s for 20 files (OCR dominates).

## Known limitations / risks
1. **Screenshots are OCR-only and undated.** Row/value alignment on the HMI panels is imperfect (e.g. the fluid-level row), alarm tags are re-derived from descriptions, and the screens are treated as `observed` facts that can corroborate or contradict but never feed the specification answer. The 14.8 mA → 200.3 bar scaling is not documented, so it is not verified.
2. Rule handlers are hand-fit to this corpus; unseen phrasings fall to generic lookup/extractive (low confidence) or abstain. Held-out correct 0.27 → 0.47 only after generic fallbacks (tuned on that set).
3. Eval set is small, authored by me; metrics are regex/gold-passage based. **No human or LLM-judge evaluation.** Citation *document precision* is 0.50–0.62 because answers cite corroborating docs not in my minimal gold sets — not necessarily errors.
4. "Hallucination" = forbidden-pattern hit or number+unit absent from cited evidence; it does not detect wrong reasoning with correct numbers.
5. Embeddings: **TF-IDF, not dense** (no model download possible in the sandbox). `AEGIS_EMBEDDER` is *not implemented*; a dense model is future work and untested.
6. LLM path (`src/qa/llm.py`) never ran against a live model; only mock-client tests (validation rejects fabricated ids, uncited claims, ungrounded numbers).
7. OCR residue: electrical drawing code read as `AEG-DWG-E002` (true: E02); doc_code for OCR docs is left NULL. `TB-7` fix relies on a heuristic character-repair rule.
8. Source inconsistencies noted, not resolved: revision history lists OM Rev 3 / MM Rev 2 for sw 3.2, while the supplied manuals are OM Rev 4 / MM Rev 3 (later revisions; not necessarily contradictory). ECN-1042 scopes the 200 bar change by software ≥3.2 but justifies it for "units manufactured after 2024" — applicability to older-built units is flagged unknown.
9. Streamlit UI code was written but **not launched/verified** in this environment. Index is a pickle (trusted local file only).

## Verification status
Run & passing here: 77 pytest tests (extractors, ids, rollback, re-ingestion, OCR failure, corrupt/unsupported files, real-dataset ingestion, topology, aliasing, scoping, conflicts, citations, abstention, LLM validation with mocks), full ingestion, eval. **Not verified:** Streamlit launch, live LLM, dense embeddings, `.xls` on real data (tested on a synthetic file).

## Assignment compliance
| Requirement | Status |
|---|---|
| 1 ingest all formats | ✅ PDF, scanned PDF, HTML, XLSX(+XLS tested synthetically), DOCX, PNG (diagram + HMI screenshots), JSON, PPTX — 20/20 files, 0 failures |
| 2 documented schema | ✅ above + `src/database.py` |
| 3 explicit deterministic vs model steps | ✅ |
| 4 alias/ID resolution + justification | ✅ |
| 5 conflicts / version-scoped facts explicit | ✅ (`resolve_scoped`, answers' conflicts/assumptions) |
| 6 provenance per fact | ✅ passage → doc/page/slide/row on every claim |
| 7 query interface w/ answer, claims, evidence, unknowns | ✅ Python API + Streamlit (UI unverified) |
| 8 eval harness, quantitative | ✅ with the caveats above |
| Architecture design report | ✅ `docs/ARCHITECTURE.md` |
