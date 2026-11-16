"""Local-only, read-only PDF viewer and metadata utilities.

The server listens on 127.0.0.1, serves ONLY indexed PDF paths, and requires a
random per-process token for every request. It never uploads or modifies PDFs.
"""
from __future__ import annotations

import html
import re
import secrets
import threading
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, urlsplit

import fitz


def extract_abstract(text: str) -> str | None:
    """Best-effort first-page abstract extraction; no invented abstracts."""
    text = re.sub(r"\r", "\n", text)
    match = re.search(r"(?im)^\s*(?:abstract|summary)\s*[:—–-]?\s*", text)
    if not match:
        return None
    tail = text[match.end():]
    end = re.search(r"(?im)^\s*(?:keywords?|index terms|introduction|1\.?\s+introduction|©|copyright|received|references)\s*[:—–-]?\s*", tail)
    if end:
        tail = tail[:end.start()]
    tail = re.sub(r"\s+", " ", tail).strip()
    if len(tail) < 60:
        return None
    return tail[:2800] + ("…" if len(tail) > 2800 else "")


@lru_cache(maxsize=256)
def read_metadata(path: str, mtime_ns: int) -> dict:
    with fitz.open(path) as doc:
        meta = doc.metadata or {}
        first = doc[0].get_text("text", sort=True) if len(doc) else ""
        second = doc[1].get_text("text", sort=True) if len(doc) > 1 else ""
        abstract = extract_abstract(first) or extract_abstract(second)
        return {
            "pdf_title": (meta.get("title") or "").strip(),
            "author": (meta.get("author") or "").strip(),
            "subject": (meta.get("subject") or "").strip(),
            "keywords": (meta.get("keywords") or "").strip(),
            "abstract": abstract,
            "pages": len(doc),
        }


class LocalPdfServer:
    def __init__(self):
        self.token = secrets.token_urlsafe(28)
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt, *args):
                return

            def do_GET(self):
                match = re.fullmatch(r"/pdf/([0-9]+)/([A-Za-z0-9_-]+)", urlsplit(self.path).path)
                if not match or match.group(2) != outer.token:
                    self.send_error(404)
                    return
                from core import connect
                try:
                    with connect() as db:
                        row = db.execute("SELECT path FROM chunk_documents WHERE id=?", (int(match.group(1)),)).fetchone()
                    if row is None:
                        self.send_error(404)
                        return
                    path = Path(row["path"])
                    if not path.is_file() or path.suffix.lower() != ".pdf":
                        self.send_error(404)
                        return
                    size = path.stat().st_size
                    self.send_response(200)
                    self.send_header("Content-Type", "application/pdf")
                    self.send_header("Content-Disposition", "inline; filename=\"document.pdf\"")
                    self.send_header("Content-Length", str(size))
                    self.send_header("Cache-Control", "private, no-store")
                    self.send_header("X-Content-Type-Options", "nosniff")
                    self.send_header("X-Frame-Options", "SAMEORIGIN") if False else None
                    self.end_headers()
                    with path.open("rb") as file:
                        while block := file.read(128 * 1024):
                            self.wfile.write(block)
                except (BrokenPipeError, ConnectionResetError):
                    pass
                except Exception:
                    try:
                        self.send_error(500)
                    except Exception:
                        pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def url(self, document_id: int, page: int = 1) -> str:
        return f"http://127.0.0.1:{self.port}/pdf/{int(document_id)}/{self.token}#page={max(1, int(page))}"


@lru_cache(maxsize=1)
def local_pdf_server() -> LocalPdfServer:
    return LocalPdfServer()
