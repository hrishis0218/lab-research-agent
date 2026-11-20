# PR: autonomous research library and consent-gated AI workspace

Base: `feature/ui-index-credentials` · Head: `codex/react-workspace`

The workspace now discovers existing/new PDFs automatically, identifies bibliographic metadata, organises attachments reversibly and prepares local page-level hybrid search. A private sidecar preserves the original index and embeddings. Current PDF paths resolve through stable IDs; journalled moves, collisions, restart recovery and undo/restore/resume are integrated. Metadata has explicit provenance and provisional states. Image-only pages receive local OCR with scientific-value warnings.

React exposes readiness, bibliography/excerpts/PDF pages, import, local history, evidence export and advanced organisation controls. Gemini/OpenAI settings use Windows Credential Manager, dynamically discovered models and explicit persistent consent. Generated citations and quotations are checked against the retrieved snapshot; these checks do not establish independent scientific truth.

Actual library: 416 attachments = 405 unique files + 11 copies; all 405 are searchable. All 416 file hashes and all 14,453 original passage/vector rows were verified unchanged. A real renamed article passed PDF-open, undo and resume with identical bytes; six actual retrieved quotes matched their original pages. Bibliography: 236 automatic matches, 169 explicitly provisional records. Two misleading historical aliases were rejected and preserved for review.

Validation: 33 Python tests, strict TypeScript/Vite build and four Chromium workflows pass; npm audit has zero advisories. Fixtures/screenshots are synthetic. Cloud traffic was mocked in tests; no live inference was run because the user explicitly chose to keep cloud processing off. Live cloud acceptance and full v1 scientific-release validation remain open. See docs/V1_IMPLEMENTATION_PLAN.md.
