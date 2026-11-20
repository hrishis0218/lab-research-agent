"""Local-only v1 workspace API. Existing index is opened read-only."""

from pathlib import Path
import mimetypes
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Query, Request
from pydantic import BaseModel, SecretStr, Field
from typing import Literal
from backend.cloud import CloudAI
from backend import credentials
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from backend.library import Library
from backend.models import LibraryStats, DocumentSummary, DocumentDetail, SearchResult


def create_app(
    library: Library | None = None, automatic: bool | None = None
) -> FastAPI:
    # Windows registry MIME mappings may label .mjs as text/plain, breaking PDF.js workers.
    mimetypes.init()
    mimetypes.add_type("application/javascript", ".mjs")
    automatic = library is None if automatic is None else automatic
    service = library or Library()
    cloud = CloudAI(
        Path(
            os.environ.get(
                "LAB_WORKSPACE_DATABASE", str(service.database) + ".workspace.sqlite3"
            )
        )
    )

    @asynccontextmanager
    async def lifespan(app):
        nonlocal service
        if automatic:
            from backend.smart_library import SmartLibrary

            model = None
            from backend.documents.crossref import fetch_crossref, flatten_record

            def lookup(doi):
                return flatten_record(fetch_crossref(doi, timeout=5))

            service = SmartLibrary(
                service,
                Path(
                    os.environ.get(
                        "LAB_SMART_DATABASE", str(service.database) + ".smart.sqlite3"
                    )
                ),
                embedder=model,
                metadata_lookup=lookup,
                worker_mode=True,
            )

            def load_model():
                from fastembed import TextEmbedding
                from retrieval import MODEL_NAME

                return TextEmbedding(model_name=MODEL_NAME, threads=2)

            if os.environ.get("LAB_DEMO_OFFLINE") != "1":
                service.model_factory = load_model
            service.start()
        yield
        if automatic:
            service.stop()

    app = FastAPI(
        title="Lab Research Agent API", version="1.0.0-dev", lifespan=lifespan
    )
    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"]
    )
    app.add_api_route("/api/health", health, methods=["GET"])

    @app.middleware("http")
    async def local_mutations(request: Request, call_next):
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            origin = request.headers.get("origin")
            if origin and origin not in (
                "http://127.0.0.1:8000",
                "http://127.0.0.1:8001",
                "http://127.0.0.1:8002",
                "http://127.0.0.1:5173",
                "http://localhost:8000",
            ):
                from fastapi.responses import JSONResponse

                return JSONResponse({"detail": "Untrusted origin"}, status_code=403)
        return await call_next(request)

    class Preferences(BaseModel):
        enabled: bool = False
        consent: bool = False
        provider: Literal["Gemini", "OpenAI"] = "Gemini"
        model: str = Field("", max_length=150, pattern=r"^[a-zA-Z0-9_.:/-]*$")

    class KeyRequest(BaseModel):
        provider: Literal["Gemini", "OpenAI"]
        secret: SecretStr

    class Question(BaseModel):
        question: str = Field(min_length=1, max_length=2000)
        limit: int = Field(6, ge=1, le=30)

    @app.get("/api/ai/settings")
    def ai_settings():
        return cloud.settings()

    @app.put("/api/ai/settings")
    def ai_configure(value: Preferences):
        try:
            return cloud.configure(value.model_dump())
        except ValueError as exc:
            raise HTTPException(400, str(exc))

    @app.post("/api/ai/credentials")
    def ai_credentials(value: KeyRequest):
        try:
            credentials.save_key(value.provider, value.secret.get_secret_value())
            return {"saved": True}
        except (ValueError, RuntimeError):
            raise HTTPException(400, "Credential could not be saved securely") from None

    @app.delete("/api/ai/credentials/{provider}")
    def ai_forget(provider: Literal["Gemini", "OpenAI"]):
        try:
            credentials.delete_key(provider)
        except (ValueError, RuntimeError):
            raise HTTPException(
                400, "Credential could not be removed from the OS store"
            ) from None
        return {"forgotten": True}

    @app.get("/api/ai/models")
    def ai_models(provider: Literal["Gemini", "OpenAI"]):
        try:
            return cloud.models(provider)
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(400, str(exc))

    @app.get("/api/history")
    def history():
        return cloud.history()

    @app.post("/api/ask")
    def ask(value: Question):
        sources = service.search(value.question, value.limit)
        try:
            answer = cloud.answer(value.question, sources)
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(400, str(exc))
        turn = {
            "question": value.question,
            "sources": sources,
            "answer": answer,
            "provider": cloud.settings()["provider"] if answer else None,
            "notice": "Generated interpretation; citation/quotation matching is not independent verification. Library preparation may be incomplete.",
        }
        cloud.save_turn(turn)
        return turn

    @app.get("/api/library/organisation")
    def organisation():
        if not hasattr(service, "organiser"):
            return []
        with service.write() as db:
            rows = db.execute(
                "SELECT m.id,m.state,m.created,m.error,m.old,m.new,i.document_id FROM moves m LEFT JOIN identities i ON i.hash=m.hash ORDER BY m.id DESC LIMIT 500"
            ).fetchall()
        return [
            dict(
                id=r["id"],
                document_id=r["document_id"],
                state=r["state"],
                created=r["created"],
                error=r["error"],
                old_name=Path(r["old"]).name,
                new_name=Path(r["new"]).name,
            )
            for r in rows
        ]

    @app.post("/api/documents/{document_id}/organise")
    def resume_organisation(document_id: int):
        try:
            with service.fs_lock:
                return service.organiser.resume(document_id)
        except (ValueError, OSError, RuntimeError) as exc:
            raise HTTPException(409, str(exc))

    @app.post("/api/library/organisation/restore-all")
    def restore_all():
        with service.fs_lock:
            return service.organiser.restore_all()

    @app.post("/api/library/organisation/{operation}/undo")
    def undo(operation: int):
        try:
            with service.fs_lock:
                return service.organiser.undo(operation)
        except (ValueError, OSError) as exc:
            raise HTTPException(409, str(exc))

    @app.post("/api/library/import")
    async def import_pdf(
        request: Request, name: str = Query("paper.pdf", max_length=200)
    ):
        import uuid, re

        if not hasattr(service, "write"):
            raise HTTPException(503, "Automatic library service is unavailable")
        root = service.folder.resolve()
        intake = (root / "Intake").resolve()
        if not intake.is_relative_to(root):
            raise HTTPException(400, "Invalid intake location")
        intake.mkdir(parents=True, exist_ok=True)
        stem = re.sub(r"[^\w.-]+", "_", Path(name).name, flags=re.UNICODE)[:100]
        if not stem.lower().endswith(".pdf"):
            raise HTTPException(400, "Only PDF imports are supported")
        token = uuid.uuid4().hex
        temporary = intake / (token + ".partial")
        target = intake / (token[:8] + "_" + stem)
        try:
            size = 0
            with temporary.open("xb") as stream:
                async for chunk in request.stream():
                    size += len(chunk)
                    if size > 512 * 1024 * 1024:
                        raise HTTPException(413, "PDF exceeds the 512 MB import limit")
                    stream.write(chunk)
                stream.flush()
                os.fsync(stream.fileno())
            with temporary.open("rb") as stream:
                if stream.read(5) != b"%PDF-":
                    raise HTTPException(400, "The file does not have a PDF header")
            temporary.rename(target)
            return {
                "imported": True,
                "message": "Paper added; preparation starts automatically",
            }
        finally:
            if temporary.exists():
                temporary.unlink()

    @app.post("/api/library/pause")
    def pause():
        if hasattr(service, "stop"):
            service.stop()
        return {"paused": True}

    @app.get("/api/library/readiness")
    def readiness():
        return (
            service.status()
            if hasattr(service, "status")
            else {"states": {}, "files": 0, "semantic_available": False}
        )

    @app.get("/api/library/stats", response_model=LibraryStats)
    def stats():
        return service.stats()

    @app.get("/api/documents", response_model=list[DocumentSummary])
    def documents(q: str = Query("", max_length=500)):
        return service.documents(q)

    @app.get("/api/documents/{document_id}", response_model=DocumentDetail)
    def detail(document_id: int, page: int = Query(1, ge=1)):
        try:
            return service.detail(document_id, page)
        except FileNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.get("/api/documents/{document_id}/pdf")
    def pdf(document_id: int):
        try:
            path = service.path(document_id)
            return FileResponse(
                path,
                media_type="application/pdf",
                content_disposition_type="inline",
                headers={"Cache-Control": "no-store"},
            )
        except FileNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.get("/api/search", response_model=SearchResult)
    def search(
        q: str = Query(min_length=1, max_length=2000),
        limit: int = Query(8, ge=1, le=30),
    ):
        return {
            "sources": service.search(q, limit),
            "mode": "hybrid" if getattr(service, "embedder", None) else "keyword",
            "notice": "Retrieved passages only. No scientific answer or entailment verification has been generated.",
        }

    dist = Path(__file__).resolve().parents[1] / "frontend/dist"
    if dist.is_dir():
        app.mount("/", StaticFiles(directory=dist, html=True), name="workspace")
    return app


def health() -> dict[str, str]:
    return {"status": "ok", "application": "Lab Research Agent", "version": "1.0.0-dev"}


app = create_app()
