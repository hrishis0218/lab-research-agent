# Lab Research Agent v1.0 architecture

## Goals

A local-first scientific literature workspace for PDF ingestion, verified document metadata, hybrid retrieval, cited answers, evidence evaluation, comparison tables, and safe document organisation.

## Components

- **Frontend (M1):** React 19, TypeScript and Vite with independently collapsible navigation/reference panes, local keyword research, library browsing, evidence export, themes and a lazy-loaded PDF.js viewer.
- **Backend (M1):** FastAPI on 127.0.0.1:8000 serves the production UI plus typed health, library statistics, document detail/PDF and keyword search endpoints. Library service connections use SQLite URI `mode=ro` and `query_only`; this avoids the legacy retrieval entry point that creates schema during searches.
- **Documents (planned):** layout-aware PDF parsing; metadata and DOI identification; SHA-256 duplicate detection; proposed renames with preview, confirmation, journal, and rollback.
- **Retrieval (existing):** retain `retrieval.py`, local SQLite FTS5, and BGE-small embeddings while evolving into independently tested services.
- **Evidence (existing/proposed):** preserve `evidence.py`; build claim-to-source evidence tables with verified quotations and appropriate uncertainty.
- **AI providers (existing/proposed):** preserve Gemini and OpenAI; add a provider adapter and secure, OS-managed credential storage before extending to Anthropic or DeepSeek.
- **Storage:** leave `data/library.sqlite3` and all PDF files outside Git. No schema migration in this milestone.

## Safety and migration rules

1. `main` remains the working Streamlit Phase 2.4 application; v1 work lives on `feature/v1-architecture`.
2. Do not overwrite the SQLite database or existing vector embeddings.
3. Never commit research PDFs, credential files, databases, or backups.
4. Do not rename or move any original PDF without preview and explicit approval. Preserve an undoable audit trail.
5. Keep provider/cloud requests opt-in; source text sent to cloud services needs laboratory approval.
6. Test new API endpoints and document parsers against synthetic fixtures before processing the full library.

## Local development

```powershell
conda activate labagent
cd /d "C:\Users\petar\Desktop\Lab Research agent\lab-research-agent"
python -m pip install -r requirements-v1.txt
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Visit http://127.0.0.1:8000/api/health. Streamlit remains available separately at port 8501.

## Document audit and DOI enrichment (v1 development)

The following tools are separate from the Streamlit PDF index and **do not modify any PDF or SQLite database**.

1. `python -m scripts.audit_pdfs "C:\\Users\\petar\\Desktop\\all pdf papers" --output data/pdf_audit.csv`
2. `python -m scripts.enrich_crossref --input data/pdf_audit.csv --output data/pdf_enriched.csv --limit 25`
3. Review `data/pdf_enriched.csv` using Excel or pandas; `crossref_status` explains whether a DOI was missing, its title matched, a title mismatch needs investigation, or lookup failed.
4. Run the enrichment command again with `--limit 100` to extend coverage. Successful responses are cached in `data/crossref_cache.json`; cached DOIs aren't requested again. The output CSV is regenerated from the original audit on each run.
5. Optionally pass `--email your-address@example.com` for the Crossref polite pool. This sends only the DOI and an optional contact email to Crossref, not PDF content.

Crossref gives authoritative metadata for *its own DOI records* but a DOI extracted from a PDF may belong to a bibliography item. **All results require review before any rename**; `title_match_review` is not an automatic approval. Proposed names are not executed, and collisions are not yet resolved.

## React workspace delivery

See [React development](REACT_DEVELOPMENT.md) for the Windows launcher, isolated demo and tests, and [implementation plan](V1_IMPLEMENTATION_PLAN.md) for current acceptance results. No migration has been applied to the existing index. Search uses near-identical passage suppression; document identity and exact-file duplicate groups remain M2 work.

## Next document-intelligence milestone

Review the Crossref match statistics, improve ambiguous first-page title extraction, then design an explicit preview/confirm/rollback workflow for renaming without breaking the existing index.
