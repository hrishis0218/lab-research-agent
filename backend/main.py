"""Local-only v1 workspace API. Existing index is opened read-only."""
from pathlib import Path
import mimetypes
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from backend.library import Library
from backend.models import LibraryStats, DocumentSummary, DocumentDetail, SearchResult


def create_app(library: Library | None = None, automatic: bool | None = None) -> FastAPI:
    # Windows registry MIME mappings may label .mjs as text/plain, breaking PDF.js workers.
    mimetypes.init()
    mimetypes.add_type('application/javascript', '.mjs')
    automatic = library is None if automatic is None else automatic
    service = library or Library()
    @asynccontextmanager
    async def lifespan(app):
        nonlocal service
        if automatic:
            from backend.smart_library import SmartLibrary
            model = None
            from backend.documents.crossref import fetch_crossref, flatten_record
            def lookup(doi):
                return flatten_record(fetch_crossref(doi, timeout=5))
            service = SmartLibrary(service, Path(os.environ.get('LAB_SMART_DATABASE', str(service.database)+'.smart.sqlite3')), embedder=model, metadata_lookup=lookup)
            def load_model():
                from fastembed import TextEmbedding
                from retrieval import MODEL_NAME
                return TextEmbedding(model_name=MODEL_NAME, threads=2)
            service.model_factory = load_model
            service.start()
        yield
        if automatic:
            service.stop()
    app = FastAPI(title='Lab Research Agent API', version='1.0.0-dev', lifespan=lifespan)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=['127.0.0.1', 'localhost', 'testserver'])
    app.add_api_route('/api/health', health, methods=['GET'])

    @app.get('/api/library/readiness')
    def readiness():
        return service.status() if hasattr(service,'status') else {'states':{},'files':0,'semantic_available':False}

    @app.get('/api/library/stats', response_model=LibraryStats)
    def stats():
        return service.stats()

    @app.get('/api/documents', response_model=list[DocumentSummary])
    def documents(q: str = Query('', max_length=500)):
        return service.documents(q)

    @app.get('/api/documents/{document_id}', response_model=DocumentDetail)
    def detail(document_id: int, page: int = Query(1, ge=1)):
        try:
            return service.detail(document_id, page)
        except FileNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.get('/api/documents/{document_id}/pdf')
    def pdf(document_id: int):
        try:
            path = service.path(document_id)
            return FileResponse(path, media_type='application/pdf', content_disposition_type='inline',
                                headers={'Cache-Control': 'no-store'})
        except FileNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.get('/api/search', response_model=SearchResult)
    def search(q: str = Query(min_length=1, max_length=2000), limit: int = Query(8, ge=1, le=30)):
        return {'sources': service.search(q, limit), 'mode': 'hybrid' if getattr(service,'embedder',None) else 'keyword',
                'notice': 'Retrieved passages only. No scientific answer or entailment verification has been generated.'}

    dist = Path(__file__).resolve().parents[1] / 'frontend/dist'
    if dist.is_dir():
        app.mount('/', StaticFiles(directory=dist, html=True), name='workspace')
    return app


def health() -> dict[str, str]:
    return {'status': 'ok', 'application': 'Lab Research Agent', 'version': '1.0.0-dev'}


app = create_app()
