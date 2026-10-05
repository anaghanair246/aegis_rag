# Architecture design report
**Goal:** answer questions with evidence, expressing conflict and gaps, over a messy, partly contradictory package.
**Core decision:** push intelligence *below* the answer layer. Facts are extracted once, deterministically, with provenance and version scope; answering assembles claims from facts and cannot introduce a value that is not stored.

## Pipeline stages
| # | Stage | Method | Why |
|---|---|---|---|
|1|Extract text/tables|pdfplumber, python-docx/pptx/bs4/openpyxl/xlrd — deterministic|born-digital text is exact; tables become header-aware row passages|
|2|OCR|tesseract (model-based), autocontrast, ID normalisation, confidence stored|only for scanned pages/PNG; raw OCR never trusted for IDs|
|2b|HMI screenshots|invert+binarise, dual-scale OCR, tag re-derivation from descriptions via register; stored as `observed` facts|dark-theme UI defeats default OCR; observations must not override spec|
|3|Diagram topology|PDF vector geometry + legend (deterministic)|topology is in lines/colours, not text|
|4|Metadata|anchored regexes on header; else NULL; trust by folder policy|no fabricated revision/authority|
|5|Knowledge build|named regex rules; unmatched rules are reported|auditable; failure visible (`rules_unmatched`)|
|6|Index|BM25 + TF-IDF (1–2gram), alias tokens, trust-aware rerank, near-dup removal, fingerprint-invalidated cache|no stale vectors after re-ingest|
|7|Answer|router → handler → claims from facts; abstain; generic fallbacks; optional validated LLM|safety-relevant values must be exact|

## Conflict policy
1. Facts carry `sw_from/sw_before`; differing values in different scopes are **not** conflicts.
2. Trusted (tier ≤3) facts with overlapping scope and different values → `CONFLICT` listing both.
3. Low-trust/superseded/unverified facts are shown as context or contradictions, never as the answer.
4. Missing information is a first-class outcome (`INSUFFICIENT_EVIDENCE` + unknowns); keyword hits in irrelevant docs (SDS) are excluded and reported.

## What I chose not to do
Dense embeddings (no model access; unevaluated), cross-encoder rerank (same), vision-model diagram reading (OCR/geometry honestly scoped), LLM-as-judge (no key, would add unverified numbers), screenshot *understanding* beyond OCR (layout/row-value alignment is heuristic).

## Loss / confidence
OCR page conf stored per passage (scan 93 mean, PNG ~89). Fact `confidence` 0.8–1.0 by method. Largest loss: raster diagram connectivity (zero recovered) and phrasing coverage of the router (see eval).
