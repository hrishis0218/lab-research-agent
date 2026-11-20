# Autonomous library and cloud AI implementation plan

## Current authority and branch

Work is on `codex/react-workspace`, synchronised with GitHub through `e66a9ee`. The Smart Library foundation was carried forward from `codex/smart-library`. The updated AGENTS.md, V1_PRODUCT_SPEC.md and AUTONOMOUS_LIBRARY_MILESTONE.md govern this work. Automatic reversible organisation inside the configured library is authorised without per-file prompts. The user's subsequent instruction is **keep cloud processing off**; live provider inference is therefore intentionally not enabled or certified.

## Milestones and acceptance

- [x] M0/M1: React/TypeScript/FastAPI shell, source panel, PDF.js, themes, local retrieval and regression fixtures.
- [x] Automatic intake: recursive reconciliation every ten seconds, changed-file hashing, stable attachment identity, exact-copy grouping, persistent jobs, retry/backoff and restart recovery. Metadata identification precedes organisation and text/vector processing; existing ready sources remain searchable.
- [x] Data safety: integrity-checked recovery snapshots made before sidecar changes. The legacy SQLite database is opened read-only; its schema, passage rows and vectors remain unchanged. A sidecar holds current paths, jobs, metadata and journal. Single-worker Windows file locking prevents concurrent recovery/organisation.
- [x] Bibliography: multiline/PDF/first-page title extraction, DOI candidates excluding references, cached Crossref DOI/title search and OpenAlex fallback. Exact-title ambiguity is withheld from verification. Per-field provenance, confidence/match information, abstracts where available, document types and virtual scientific tags are exposed. Missing data stays explicitly unavailable.
- [x] Safe organisation: validated names use year/author/title; provisional identities go to Needs_Review. Windows no-replace rename semantics, deterministic collision suffixes, before/after hashes, durable planned/completed operations, crash reconciliation, undo, restore-all and resume controls. No original PDF content is edited or deleted.
- [x] Local text preparation: page-level excerpts, lazy BGE-small CPU embeddings, keyword fallback, hybrid retrieval and publication/near-identical passage suppression. Unchanged legacy content can reuse original identity/vectors after all indexed passages match the candidate PDF pages.
- [x] OCR fallback: only image-only pages are OCRed locally using Tesseract language data; PDFs are not rewritten. OCR provenance warns about numbers, units and equations. Two formerly unreadable scans are now searchable.
- [x] UI: automatic readiness and refreshed library, searchable papers/duplicates/awaiting-text counts, drag-and-drop import, metadata/DOI/journal/abstract/tags, current PDF links, saved local turns/source snapshots, evidence CSV, advanced organisation history and rollback.
- [x] Provider implementation: Gemini/OpenAI adapters, dynamically discovered models, Windows Credential Manager keys, persistent consent and AI/retrieval toggle. Grounded prompts request known citation IDs and exact quotations; unmatched citations/quotes withhold an answer. This validates strings and provenance, not scientific entailment.
- [ ] Live cloud acceptance: deferred by explicit user choice. No real key is configured and cloud consent/enabled remain false. Both adapters and the React flow were tested with mocked provider responses; no live answering success is claimed.
- [ ] Full v1 release: independent claim evaluation, human-reviewed retrieval benchmark, sophisticated publication/version resolution, selectable/highlighted in-PDF text, collections and full conversation management remain future work. Provisional bibliographic identities still require review; this is not a claim of universally correct metadata.

## Automated validation

- 33 Python tests pass: legacy retrieval/audit/Crossref plus new PDFs, copies, rename/replacement, damaged files, restart, a 416-versus-262/85-stale-record fixture, vector preservation, collisions, Windows locks, interrupted move/undo, source aliases, metadata provenance/reference DOI handling, OCR pipeline, credential persistence mocks, both provider adapters and rejected citations/quotes.
- Strict TypeScript/Vite production build passes.
- Four Playwright Chromium workflows pass: 1366x768, 1920x1080, mobile/error preservation, and saved credential/model/consent/AI answer/citation UI with mocked provider traffic. The isolated demo disables external metadata and embedding downloads; fixtures and screenshots contain synthetic research only.
- Screenshots visually inspected, including synthetic in-pane PDF and the explicitly mocked answer/citation view. npm audit reports zero vulnerabilities.
- Legacy fitz and Starlette/httpx deprecation warnings remain; fallback Streamlit code is preserved.

## Actual local verification — 2026-11-20

This is separate from fixture tests. The real configured library was processed and organised automatically.

- **416 attachments = 405 unique files + 11 exact duplicate copies. All 405 unique files are search-ready; zero remain without readable text.**
- Completed identification pass: **236 bibliographic matches; 169 provisional identities**. Provisional records are labelled and organised conservatively; absent authors/DOIs/abstracts are not invented. Metadata-service failures have circuit breaking/retries.
- **416/416 current PDFs passed SHA-256 comparison** against their recorded original content fingerprints after organisation. Validation took about 10.5 seconds. Seven document records include OCR provenance (including the two previously unsearchable scans).
- Actual verified article: opened by permanent document ID, undone through the API, reopened, organisation resumed and reopened again. All three PDF streams had identical SHA-256.
- Actual research question: six retrieved excerpts all matched the cited original PDF page text. This verifies retrieval/provenance, not scientific entailment or exhaustive research quality.
- **All 14,453 original passage/vector rows matched byte-for-byte in the sidecar.** Original DB SHA256 remains `662e8d9292f694348613c29e074c8457f7398eed338f7dc069a9eadb110be75c`; SQLite quick_check is ok.
- Historical aliases were revalidated against every indexed passage: 25 mappings passed; two misleading older mappings were rejected and retained in review history. Unresolved historical records and original vectors remain preserved, rather than being silently deleted or redirected to a different paper.
- Private machine-readable validation details are in ignored `data/autonomous_validation.json`; no actual PDFs, metadata dumps, credentials or databases are committed.
- Cloud enabled: **false**. No real Gemini/OpenAI request was made. Original acceptance requiring live cloud answers remains explicitly unverified.

## Recovery and operation

Use `scripts/dev.ps1` to build/start the workspace at localhost:8000. Intake starts with FastAPI; there is no index/audit/enrichment button. Leave the app running to monitor additions; this is an application background worker, not an installed Windows service. First-time model/language assets require internet; existing local search works without provider keys or inference access.

Use Settings organisation history for individual undo or original-location restore. Rollback pauses organisation for that content; Resume organising is explicit. Restore destinations are never overwritten; conflicting or modified files require attention. The legacy Streamlit database remains intact; restoring original file locations through the journal makes the old paths recoverable. Disaster-recovery snapshots are under ignored `data/recovery`; do not overwrite the legacy index casually.
