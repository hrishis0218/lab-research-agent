# Lab Research Agent v1.0 architecture

## Goals

A local-first scientific literature workspace for PDF ingestion, verified document metadata, hybrid retrieval, cited answers, evidence evaluation, comparison tables, and safe document organisation.

## Components

- **Frontend (planned):** React with a collapsible library sidebar, central conversation, and contextual right-hand reference/PDF pane.
- **Backend (initial):** FastAPI running on 127.0.0.1:8000; serves data to the future frontend. Only `/api/health` exists today.
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

## Next milestone

Implement a read-only document metadata and duplicate audit, using file hashes and conservative metadata extraction. Write a CSV proposal; do not rename files or rewrite the existing index.
