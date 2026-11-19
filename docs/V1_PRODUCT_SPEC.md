# Lab Research Agent v1.0 — Product and engineering specification

## 1. Mission

Build a polished, local-first scientific research workspace for a small physics/materials research laboratory. It must answer questions about the **user's own PDF collection** with verifiable page-level evidence, manage and organise scientific PDFs safely, and remain usable on a Windows laptop with **Intel i5 CPU, 8 GB RAM, no discrete GPU, Python 3.12 in the Conda environment `labagent`**.

The current working Streamlit Phase 2.4 app is a *reference implementation and fallback*, not the final UI. Do not keep piling UI features into `app.py`. Implement a cohesive React frontend and modular FastAPI backend. Prioritise scientific reliability, zero data loss, responsiveness, usability and testability over feature count.

**Repository:** https://github.com/hrishis0218/lab-research-agent

**Local repository:** `C:\Users\petar\Desktop\Lab Research agent\lab-research-agent`

**PDF collection:** `C:\Users\petar\Desktop\all pdf papers` (recursively scan subfolders).

**Indexed database:** `data/library.sqlite3` or path configured by `core.py`; the database is not committed to Git. Do not assume this database exists in a cloud clone.

**Current state from local tests/screenshots:** 416 PDFs found during a *read-only audit*, including 11 byte-identical duplicate copies. At a previous point, the search index contained 262 PDF paths and 14,453 passages, all with embeddings. These are two separate populations; don't imply that all audited PDFs are indexed. Their counts can change.

## 2. Product requirements and screens

### Global shell / navigation
- Responsive desktop-first layout inspired by effective scholarly research tools, without copying a proprietary site's styling or content.
- **Left rail**: compact/collapsible navigation for new conversation, conversations/history, PDF library, collections, experiment comparison, settings, and library status. Collapsed mode keeps useful icons and tooltips. Independently resizable only if robust.
- **Middle**: readable, width-constrained conversational content, user questions, model-generated answers, inline interactive citation chips, comparison tables, independent scroll region, fixed bottom composer with multiline input.
- **Right reference pane**: hidden until a source is selected; resizable, collapsible, reference-specific. First render accurate bibliographic metadata and extracted abstract (explicitly show “unavailable” instead of inventing one), direct quote and page reference, then open a PDF viewer in the same pane on click. Include open-in-new-tab control.
- Show a beautiful empty state, loading/progress states, meaningful error feedback, light/dark mode, keyboard navigation, good contrast and proper spacing. No giant uniformly styled source buttons.
- Preserve input and selected source when collapsing panels. Avoid jumping/refreshing the entire page on common interactions.
- User should not need to manually paste paths, API keys or select model on every restart.

### Local library and documents
- Browse, search and sort all discovered PDF files, separately showing **on-disk**, **indexed**, **unindexed**, **failed** and **exact duplicate copies**; never conflate them.
- Folder picker (or persistent folder setting) and recursive discovery, incremental indexing with progress, cancel/retry where feasible. New and unchanged files should be handled separately.
- PDF extraction: evaluate layout-aware blocks, reading order, columns, hyphenation and Unicode; retain original source text + cleaned text and page anchors. Do **not** silently “fix” scientific equations or numbers; visibly flag uncertain OCR/text.
- Extract title, authors, year, journal, DOI, abstract, keywords when available. Prefer validated DOI/Crossref metadata; distinguish source provenance and confidence; flag incomplete/malformed titles. Recognise books, preprints and theses.
- Detect exact duplicates by SHA-256 and bibliographic duplicates by verified DOI/title and provenance; multiple PDF versions of the same paper must not count as independent evidence.
- **Rename manager**: preview old/new filename, metadata, confidence, collisions and affected index paths; require explicit approval before any rename/move/delete; prevent overwrites; journal changes and support rollback; update index paths consistently. Never rename source PDFs as a side effect of indexing or importing.
- Keep original PDFs local. Clearly disclose when selected text is sent to an external model or metadata service.

### Search and RAG
- Keep functioning SQLite FTS5 and existing `BAAI/bge-small-en-v1.5` embeddings initially. Migrate behind interfaces incrementally; don't force re-embedding or database replacement.
- Hybrid keyword + semantic retrieval, configurable source count (not hard-coded 8), candidate expansion and deduplication across duplicate files and nearly identical passages. Use material-aware relevance without excluding legitimate analogous evidence.
- Optional lightweight reranker after measuring latency on 8 GB; make it disable-able.
- Every answer should link to actual source paper, page, exact excerpt; clicking citation focuses the right source pane. The model must not cite unknown IDs or claim support absent from excerpts. Preserve uncertainty and distinguish experiment, theory, analogy and inference.
- Support **retrieval only** toggle independently of AI model choice.
- Retain conversation turns locally, including the retrieved source snapshot and model/provider used, so old citations remain inspectable.

### AI provider settings
- Adapters for Google Gemini, OpenAI, Anthropic Claude and DeepSeek. Implement capability checks and a model catalogue that can be updated; don't hard-code fictitious or retired model IDs. Provider/model dropdown and automatic fallback only with user-authorised policies.
- Store API credentials in **Windows Credential Manager** via `keyring`, or equivalent OS-managed secret store. Explicit save/replace/forget controls; never put keys in the repository, plaintext configs, logs or chat. Do not expose them via frontend API responses.
- Display whether an API call uses free-tier quota or paid usage *as reported by provider*, and distinguish unknown cost from zero cost. No claims that ChatGPT Plus pays external API bills.
- AI off should work end-to-end with no credentials or network.

### Scientific evidence engine
- Extract atomic claims, classify support as direct experimental, simulation/theory, indirect/analogous, contradictory, or insufficient; preserve processing parameters (material, thickness, temperature, voltage, time, environment, measurement) where cited.
- Never let one AI model merely “grade itself” without source checks. Verify that cited source IDs exist and quoted text actually occurs in source passages; separate string verification from entailment.
- Evidence matrix with paper, page, exact quote, conditions, evidence class, limitations and reviewer notes; export CSV. Link claims to PDF pages.
- Explicitly distinguish causal claims from correlation and flag conditions/uncertainties. A polished-looking answer is not a proof.

## 3. Architecture recommendation

- **Frontend**: React + TypeScript, Vite; choose a cohesive accessible component system (Radix/shadcn or equivalent), CSS variables for themes, TanStack Query for server state; PDF.js for in-pane PDF reading/search/highlights.
- **Backend**: FastAPI, Pydantic models, dependency-injected services; avoid circular imports and implicit global DB connections. Existing Phase 2.4 Python scripts are migration references.
- **Storage**: SQLite with separate/compatible schema migrations and SQLite FTS5. Store indexes and PDF paths locally, not in Git; add migration backups/rollback. Lazy-load embeddings to manage memory. Avoid heavyweight local LLM requirements.
- **Credentials**: OS keyring, provider SDKs behind a common interface; handle rate limiting and failures gracefully.
- **Document parsing**: PyMuPDF (`pymupdf` import preferred over deprecated `fitz` alias) and optional specialised extraction only when empirically beneficial. No mandatory OCR for every document.
- **Desktop packaging**: start as a locally served web app with clear start command/launcher. Consider a compact desktop wrapper only after stability; do not require Electron overhead on an 8 GB laptop.
- **Operating system**: Windows PowerShell + Anaconda, avoiding shell tricks assuming WSL. Make `python -m ...` commands straightforward; allow Node/npm installation where needed.

## 4. Delivery strategy and required milestones

### M0: Baseline and safety
1. Inspect the repo and tests; produce short audit of old structure and known problems.
2. Create a dedicated v1 React branch from the current development branch. Do not merge or delete old branches.
3. Ensure no secret or dataset will be included in commits. Back up DB before migrations. Add a reproducible test/data fixture and local `scripts/dev.ps1` launcher.
4. Read/update this spec and maintain a checked milestone plan. Do not assume old tests cover new functionality.

### M1: Coherent UI shell
- Implement React/Vite/TypeScript shell, left navigation, centre conversation and right reference panel.
- Read-only FastAPI endpoints for library stats and sources; use mock data when the local DB is not available.
- Source panel metadata, abstract, excerpt, PDF.js viewer, new-tab link; loading and empty states.
- Screenshot/test layout at 1366×768 and 1920×1080, dark/light themes, keyboard use; no giant buttons or broken PDF panes.
- Demo application can be started locally with documented commands. Keep old Streamlit functional.

### M2: Complete library/indexing
- Show audited vs indexed vs unindexed counts; list and filter documents.
- Run safe incremental indexing against configured folder. Keep existing embeddings intact, support errors and status, no accidental duplicate sources.
- Add indexing/progress API, tests for 416-vs-262 discrepancy scenario.

### M3: AI chat + providers
- Gemini and OpenAI adapters first, Anthropic/DeepSeek architecture and adapters when API details verified.
- OS-persisted keys, model selection, retrieval-only toggle, persistent conversations, clickable citations, configurable evidence count.
- Use fake providers in automated tests; do not require paid API calls for CI.

### M4: Document intelligence
- Improve title/abstract extraction, DOI/Crossref metadata, duplicate grouping, document identities, read-only rename preview.
- With explicit approval, add journaled rename/rollback and consistent index path updates; test collisions, copies, cross-folder files and Windows locking.

### M5: Evidence tools and release validation
- Evidence matrix, support categorisation, verified quote/page links, experiment comparison and export.
- Run unit, integration and browser e2e tests. Validate on a small representative local corpus before bulk processing.
- README, troubleshooting, backups/restore, performance benchmark on 8 GB, release checklist and colleague demo.

Within each milestone, implement multiple cohesive features, run tests, review UI visually, fix bugs, commit, and provide a concise milestone outcome. **Avoid one-file-per-chat drip-feed development.** Do not promise immediate completion of all milestones without testing.

## 5. Non-negotiable safeguards

- NO modification, deletion, rename or relocation of `C:\Users\petar\Desktop\all pdf papers` without explicit per-operation approval.
- NO overwriting, deleting or silently migrating existing `data/library.sqlite3` or embeddings; use backup and migration tests.
- NO committing PDFs, databases, API keys or private lab files to GitHub (repository is currently public).
- NO unapproved outbound upload of unpublished/internal source text to any cloud LLM. Crossref requests should involve DOI metadata only.
- NO fabricated sources, page numbers, quotes, authors, DOIs, model pricing or evidence scores.
- Avoid ambiguous “all tests pass” if only synthetic tests ran. Report precisely what ran and what was not tested.
- Do not publish/merge into `main` without explicit user approval. Avoid force pushes and destructive Git commands.
- Work autonomously on routine editing/building/debugging **within these boundaries**; seek approval for destructive operations, new paid services, or sensitive data sharing.

## 6. Acceptance criteria

- Running locally on 8GB Windows, user sees three independently collapsible panels, central chat, metadata-then-PDF right pane; PDF cited page opens both in pane and new tab.
- The application explicitly distinguishes on-disk (416 at last audit) versus currently indexed (262 at last screenshot), and reports changed counts accurately.
- User can choose number of passages, run keyword/semantic/hybrid search, and see duplicate-suppressed source references with page links.
- API key saved once survives Streamlit/React reload and system restart; no plaintext key in repo/log/frontend.
- Search and document browsing work when cloud AI is disabled.
- New UI offers metadata/abstract with confidence, duplicate groups, rename previews, and never mutates source PDFs without approval.
- Tests include Windows-safe SQLite cleanup; all major endpoints, UI workflows and identity/rename logic have automatic regression coverage.
- Original Phase 2.4 remains recoverable and old database intact.
- Provide a colleague-ready demo with sample queries, honest limitations, and a clear changelog.
