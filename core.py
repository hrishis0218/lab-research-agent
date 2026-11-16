"""Local-only PDF indexing and page-level full-text retrieval."""
from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import fitz

DB_PATH = Path(__file__).parent / "data" / "library.sqlite3"


def connect(db_path: Path = DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.executescript("""
        CREATE TABLE IF NOT EXISTS documents (
          id INTEGER PRIMARY KEY, path TEXT UNIQUE NOT NULL,
          size INTEGER NOT NULL, mtime_ns INTEGER NOT NULL,
          title TEXT, pages INTEGER NOT NULL
        );
        CREATE VIRTUAL TABLE IF NOT EXISTS page_search USING fts5(
          document_id UNINDEXED, page_number UNINDEXED, body,
          tokenize='unicode61'
        );
    """)
    return con


def index_folder(folder: str | Path, con: sqlite3.Connection) -> dict:
    folder = Path(folder).expanduser().resolve()
    if not folder.is_dir():
        raise ValueError(f"Folder does not exist: {folder}")
    stats = {"added_or_updated": 0, "unchanged": 0, "failed": []}
    for path in sorted(folder.rglob("*")):
        if not path.is_file() or path.suffix.lower() != ".pdf":
            continue
        try:
            st = path.stat()
            old = con.execute("SELECT * FROM documents WHERE path=?", (str(path),)).fetchone()
            if old and old["size"] == st.st_size and old["mtime_ns"] == st.st_mtime_ns:
                stats["unchanged"] += 1
                continue
            with fitz.open(path) as pdf:
                if pdf.needs_pass:
                    raise ValueError("password-protected PDF")
                pages = [page.get_text("text", sort=True) for page in pdf]
                title = (pdf.metadata or {}).get("title") or path.stem
            with con:
                if old:
                    doc_id = old["id"]
                    con.execute("DELETE FROM page_search WHERE document_id=?", (doc_id,))
                    con.execute("UPDATE documents SET size=?, mtime_ns=?, title=?, pages=? WHERE id=?",
                                (st.st_size, st.st_mtime_ns, title, len(pages), doc_id))
                else:
                    doc_id = con.execute(
                        "INSERT INTO documents(path,size,mtime_ns,title,pages) VALUES (?,?,?,?,?)",
                        (str(path), st.st_size, st.st_mtime_ns, title, len(pages))
                    ).lastrowid
                con.executemany(
                    "INSERT INTO page_search(document_id,page_number,body) VALUES (?,?,?)",
                    ((doc_id, i + 1, body) for i, body in enumerate(pages) if body.strip())
                )
            stats["added_or_updated"] += 1
        except Exception as exc:
            stats["failed"].append(f"{path.name}: {exc}")
    return stats


def search(query: str, con: sqlite3.Connection, limit: int = 30) -> list[dict]:
    # FTS5 expression syntax is complex; quote user tokens as literal words.
    words = [w for w in query.split() if w.strip()]
    if not words:
        return []
    expression = " AND ".join('"' + w.replace('"', '""') + '"' for w in words)
    rows = con.execute("""
      SELECT d.title, d.path, p.page_number,
        snippet(page_search, 2, '[', ']', ' … ', 35) AS excerpt,
        bm25(page_search) AS score
      FROM page_search p JOIN documents d ON d.id = p.document_id
      WHERE page_search MATCH ? ORDER BY score LIMIT ?
    """, (expression, max(1, min(limit, 100)))).fetchall()
    return [dict(row) for row in rows]


def document_count(con: sqlite3.Connection) -> int:
    return con.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
