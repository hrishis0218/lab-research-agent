# React workspace development

The v1 workspace runs entirely on localhost. It opens the existing Phase 2 index in SQLite read-only mode; it does not index, migrate, re-embed or rename anything. The Streamlit application and old branches remain available.

## Start on Windows

Prerequisites: Node.js 22+ (Vite 7 requires 22.12+), npm, and the existing Conda `labagent` environment.

From the repository root:

```powershell
.\scripts\dev.ps1
```

This installs minimal API dependencies, runs `npm ci`, builds React, then serves both UI and API at **http://127.0.0.1:8000**. Later starts may use `-SkipInstall`. Ctrl+C stops the server. Do not expose the server on a public interface.

Defaults: `data/library.sqlite3` and `$HOME\Desktop\all pdf papers`. To select alternatives before starting:

```powershell
$env:LAB_DATABASE = 'D:\research\library.sqlite3'
$env:LAB_PDF_FOLDER = 'D:\research\papers'
.\scripts\dev.ps1 -SkipInstall
```

For frontend hot reload, run the backend on port 8000 and `npm run dev --prefix frontend` in a second terminal; Vite proxies `/api` locally. Production serves the Vite build directly from FastAPI.

## Demo and tests

```powershell
conda run -n labagent python -m unittest discover -s tests
npm run build --prefix frontend
npx --prefix frontend playwright install chromium
npm run test:e2e --prefix frontend
```

Playwright starts an isolated synthetic server on port 8001 with `scripts/serve_demo.py`. Its PDFs are explicitly marked synthetic and stored only in ignored `data/demo`; the live index is never used by browser tests. Stop any unrelated server on port 8001 before testing. Screenshots are in ignored `frontend/test-results`.

For a colleague demonstration without private research: `conda run --no-capture-output -n labagent python -m scripts.serve_demo`, then visit port 8001. Search **annealing**, select S1, read its exact excerpt, open PDF, advance to page 2, toggle themes/panels, then export the session from Evidence.

## Implemented milestone

- React/TypeScript three-pane responsive shell with light/dark themes and keyboard composer.
- Live library search/filter, separate filesystem/index/unindexed/missing counts.
- Read-only FTS5 retrieval with configurable passage limit, max two passages per document and near-identical passage suppression. This is keyword retrieval, not hybrid search or independent support verification.
- Citation-specific metadata/quoted passage, PDF.js page rendering/navigation and original PDF link; viewer code loads only on demand.
- Local evidence CSV export with spreadsheet formula escaping.
- Typed API contracts; PDFs are served by document ID only and constrained to the configured root, including resolved symlinks.

## Limitations and next work

M2–M5 remain open. Indexing jobs, audited duplicate groups, semantic retrieval, secure provider configuration, model-generated scientific answers, persistent conversations, collections, validated metadata, rename/rollback and claim/experiment comparison tools are not delivered in this milestone. The UI labels these limits; no inactive provider controls collect keys. Session conversations disappear on reload; theme persists locally. Abstracts are explicitly unavailable until extraction is validated. Indexed titles/authors may be unvalidated PDF metadata.

Missing indexed paths must be reconciled through a reviewed identity/path plan before migration. Do not assume that the difference between indexed count and on-disk count equals unindexed files. Stats use resolved, case-normalised paths; they do not identify byte duplicates. Missing DB returns empty states; an incompatible existing schema returns an API error and requires diagnosis, never automatic recreation.

The PDF canvas currently provides page navigation, rather than selectable text, in-PDF search or passage highlights. No measured retrieval-quality claim is made: hand-labelled questions and a performance study are required before release. Browser fixtures verify plumbing only. Existing dependency deprecation warnings for legacy `fitz` and Starlette/httpx remain; Phase 2 code has not been modified.
