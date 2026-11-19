# v1 implementation plan

## Baseline and constraints
Branch: `codex/react-workspace`, based on `feature/ui-index-credentials` at `f77688a`. Phase 2.4 Python scripts, fallback branches, original PDFs and the live SQLite schema/embeddings are unchanged. No data migration, source mutation, provider request or credential capture has been performed.

Existing code: Streamlit entry point, CPU embedding/FTS5 passage retrieval, citation audits, PDF audit and cached Crossref enrichment. Initial backend exposed only health; frontend was empty. Existing retrieval invokes schema creation on search; the new adapter deliberately opens SQLite with URI `mode=ro` and `query_only=ON`, reusing the passage schema and duplicate-similarity helper without calling that entry point. Sources and PDF paths remain behind a local service interface.

## Milestones
- [x] **M0 baseline/safety:** read instructions/spec/history/schema; create dedicated branch; run original 14 tests; add isolated fixtures and PowerShell launcher; inspect staged data/secret patterns; fingerprint and integrity-check the live database. No migration means no database backup/restore operation was needed or attempted.
- [x] **M1 shell/integration:** React/Vite/TypeScript, responsive independently collapsible navigation/reference panels, themes, keyboard composer, local keyword evidence retrieval, searchable indexed library, actual population counts, exact citation excerpts and page links, metadata provenance/unavailable states, PDF.js canvas/navigation, new-tab links and evidence CSV export. FastAPI supplies typed contracts and read-only document/search APIs. Missing DB has an honest empty state; synthetic demo is explicit and isolated.
- [ ] **M2 complete library/indexing:** browse unindexed files, persistent folder configuration/picker, incremental jobs/progress/cancel/retry, byte duplicate groups, safe reconciliation of stale paths and preserved embeddings. Read-only discovery counts are done; full indexing is not.
- [ ] **M3 AI/providers/persistence:** provider catalogue and consent, Windows Credential Manager, adapters, saved conversations/source snapshots, collections and semantic/hybrid retrieval without implicit downloads. Current conversations are session-only; cloud AI is off.
- [ ] **M4 document intelligence:** validated metadata/DOIs and rename preview, then per-operation approved journal/rollback/path updates. Existing CLI audit/enrichment remains separate.
- [ ] **M5 scientific release validation:** atomic claim/quote checks, experimental comparisons, reviewed evidence categories, hand-labelled retrieval evaluation, larger-corpus latency/memory study and release/demo checklist. Current CSV exports exact retrieved excerpts and explicitly marks entailment unassessed.

## Acceptance and test results — 2026-11-19
- Original suite: **14 passed** before implementation.
- Final Python suite: **20 passed**, including synthetic API integration, preserved database SHA256, unavailable DB, PDF root restrictions, validation, blocked external Host headers, Windows `.mjs` MIME mapping and the 416-on-disk / 262-indexed reconciliation scenario. Existing `fitz` and Starlette/httpx deprecation warnings remain.
- TypeScript strict typecheck + Vite production build: **passed**. Initial UI JS ~243 kB (76 kB gzip); PDF renderer ~452 kB loads on demand; worker is local.
- Playwright Chromium: **3 passed**. Desktop 1366x768 and 1920x1080 cover library filtering, real synthetic PDF painting/page navigation, citations, dark/light, independent panels, keyboard submission, preserved draft and CSV download; mobile 390x844 covers responsive bounds, panel dismissal and API failure without lost input. Desktop workflows assert no HTTP requests leave localhost and no browser exceptions.
- Visual QA: inspected light 1366, dark 1920 and rendered-PDF 1366 screenshots; examples in `docs/screenshots` contain synthetic content only. Fixed Windows registry mapping `.mjs` to text/plain, which initially prevented the PDF worker from loading. Tests now assert no render alert and a non-empty canvas, rather than just visible controls.
- npm audit: **0 vulnerabilities** after upgrading PDF.js to its patched current release.
- Live read-only smoke check: **416** resolved PDF paths, **262** indexed records, **177** indexed paths found on disk, **239** on-disk unindexed paths, **85** missing/stale indexed paths; **14,453** passages, all with embeddings. These reflect the final read-only scan, superseding an earlier PowerShell file enumeration. No inference is made about document identity or exact-byte duplicates.
- Live SQLite `quick_check`: **ok**. SHA256 before/after API/UI development: `662e8d9292f694348613c29e074c8457f7398eed338f7dc069a9eadb110be75c` (unchanged).
- Single-run live smoke timings: statistics ~0.50 s; keyword query `annealing`, six passages ~0.27 s; backend working set ~80 MB after smoke checks. These are observations, not a complete 8 GB performance/quality certification.

## Next coherent milestone and risks
M2 should begin with a read-only identity audit explaining the 85 stale paths, before proposing any migration. Add a separate job/state database for discovery and progress, test incremental indexing against isolated fixtures and preserve existing vectors. The user must approve any live schema/path migration and each original-file rename/move/delete operation. Provider activation and confidential source uploads require explicit approval.

The v1 product is **not complete**. Full-text PDF selection/search/highlights, persistent chats, providers, hybrid retrieval, duplicate-file grouping, indexing jobs, validated bibliographic metadata, rename/rollback and scientific support verification remain outstanding. Do not represent retrieved passages as independently verified scientific answers. See `REACT_DEVELOPMENT.md` for reproducible launch, demo and tests.
