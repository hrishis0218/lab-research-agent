# React workspace development and operation

The application is a local React/TypeScript workspace served by FastAPI on Windows. The normal flow is **add PDFs -> ask questions -> inspect answers/evidence and original pages**. Folder monitoring, bibliographic lookup, safe organisation, OCR when necessary and indexing run automatically.

## Start

Prerequisites: Node.js 22.12+ and the Conda `labagent` environment. From the repository root:

```powershell
.\scripts\dev.ps1
```

Open **http://127.0.0.1:8000**. Later launches can use `-SkipInstall`. Ctrl+C stops the application and its worker. Only one process may own a Smart Library database. Bind to localhost; this build is not an authenticated multi-user server.

Defaults are `data/library.sqlite3` and `$HOME\Desktop\all pdf papers`. Optional startup overrides:

```powershell
$env:LAB_DATABASE = 'D:\research\library.sqlite3'
$env:LAB_PDF_FOLDER = 'D:\research\papers'
.\scripts\dev.ps1 -SkipInstall
```

`LAB_SMART_DATABASE` and `LAB_WORKSPACE_DATABASE` optionally select sidecar and chat/preferences storage. Keep private stores outside Git. The original library is read-only; sidecars contain current identities, paths, jobs, vectors, metadata and move journals. Do not run two workers against the same sidecar. Metadata requests send bibliographic identifiers/titles, not PDF files. Local BGE and OCR language assets may download on first use; document text is processed locally.

## Ordinary use

Add PDFs to any subfolder of the configured library, or drag them onto the Library import area. Imports never overwrite an existing name. Originals' bytes remain unchanged during organisation. Search ready papers while new ones are preparing; duplicates are grouped as attachments, and unreadable/provisional metadata is reported rather than fabricated.

Select a citation to inspect bibliography, abstract, exact excerpt and PDF page. OCR passages carry a visual-check warning. Evidence exports include bibliography, extraction origin and permanent PDF page links. Research turns and source snapshots persist locally.

## Optional cloud answering

Cloud processing is **off by default and currently remains off at the user's request**. Retrieval Only requires no key. To opt in later, Settings supports:

1. Gemini or OpenAI selection; save/replace/forget an API key in Windows Credential Manager. Keys never return in API responses or enter SQLite/browser persistence.
2. Load the provider's actual model catalogue and select a model. Access/capability and quota errors are reported without losing the question; there is no automatic paid fallback.
3. Explicit consent to send the question/selected excerpts and accept possible provider charges, then save preferences. AI On in the composer persists the selected policy. Pricing/quota are unknown unless reported by the provider.

No full PDFs are uploaded. OpenAI responses request `store=false`; provider handling remains subject to their terms. Citation and quotation matching checks source provenance, not independent scientific truth. No live provider test has been performed for this delivery; mock tests are labelled as such.

## Organisation and recovery

Settings lists old/new names and journal status. Undo restores the previous location if its content/hash and destination are safe. Restore original file locations walks the journal backwards; conflicts are reported and never overwritten. Rollback places that content on hold so the worker does not immediately rename it again. Resume organising releases the hold explicitly. No source deletion is performed. Uncertain metadata goes to Needs_Review with a provisional name.

The original Streamlit source/database and all original embeddings remain recoverable. Integrity-checked pre-change database snapshots are in `data/recovery`. Restore file paths through the journal when using the original database; do not reset/rebuild the index. Unavailable historical citations are retained and clearly reported.

## Development and tests

```powershell
conda run -n labagent python -m unittest discover -s tests
npm run build --prefix frontend
npx --prefix frontend playwright install chromium
npm run test:e2e --prefix frontend
```

Playwright starts a completely synthetic, isolated demo at port 8001. The demo disables external metadata/model downloads and uses keyword retrieval; provider UI requests are mocked. No API keys or actual research corpus are required for tests. Run `python -m scripts.serve_demo` inside `labagent` for a colleague demo. Test screenshots are ignored under `frontend/test-results`.

For hot reload, run FastAPI on 8000 and `npm run dev --prefix frontend` separately; Vite proxies `/api`. See [implementation/acceptance results](V1_IMPLEMENTATION_PLAN.md). Provisional metadata, scientific entailment validation, richer version identity, collections and a full release-quality retrieval benchmark remain open work. Monitoring requires the app running; a Windows-service installer is not included.
