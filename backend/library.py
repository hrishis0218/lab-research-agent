"""Read-only access to the Phase 2 passage index. No migrations or model downloads."""
from __future__ import annotations

import os
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class Library:
    def __init__(self, database: Path | None = None, folder: Path | None = None):
        self.database = database or Path(os.environ.get('LAB_DATABASE', ROOT / 'data/library.sqlite3'))
        self.folder = (folder or Path(os.environ.get('LAB_PDF_FOLDER', Path.home() / 'Desktop/all pdf papers'))).resolve()

    @contextmanager
    def connection(self):
        if not self.database.is_file():
            yield None
            return
        con = sqlite3.connect(self.database.resolve().as_uri() + '?mode=ro', uri=True)
        con.row_factory = sqlite3.Row
        con.execute('PRAGMA query_only=ON')
        try:
            yield con
        finally:
            con.close()

    def documents(self, query: str = '') -> list[dict]:
        with self.connection() as con:
            if con is None:
                return []
            rows = con.execute('''SELECT d.id,d.title,d.path,count(c.id) passages,
                max(c.page) pages FROM chunk_documents d LEFT JOIN chunks c ON c.document_id=d.id
                GROUP BY d.id ORDER BY d.title COLLATE NOCASE''').fetchall()
        result = []
        for row in rows:
            doc = dict(row)
            path = Path(doc.pop('path')).resolve()
            if query.casefold() not in (str(doc['title']) + path.name).casefold():
                continue
            doc.update(filename=path.name, available=path.is_file() and path.is_relative_to(self.folder))
            result.append(doc)
        return result

    def stats(self) -> dict:
        docs = self.documents()
        disk = {str(p.resolve()).casefold() for p in self.folder.rglob('*') if p.is_file() and p.suffix.lower() == '.pdf'} if self.folder.is_dir() else set()
        with self.connection() as con:
            indexed = {str(Path(r[0]).resolve()).casefold() for r in con.execute('SELECT path FROM chunk_documents')} if con else set()
        return dict(on_disk=len(disk), indexed=len(docs), indexed_on_disk=len(disk & indexed),
                    unindexed=len(disk - indexed), missing=len(indexed - disk),
                    passages=sum(d['passages'] for d in docs), database_available=self.database.is_file(),
                    folder_available=self.folder.is_dir(), duplicate_copies=None,
                    duplicate_status='Not scanned in this milestone', mode='read-only')

    def path(self, document_id: int) -> Path:
        with self.connection() as con:
            row = con.execute('SELECT path FROM chunk_documents WHERE id=?', (document_id,)).fetchone() if con else None
        if not row:
            raise FileNotFoundError('Document not found')
        path = Path(row[0]).resolve()
        if not path.is_relative_to(self.folder) or path.suffix.lower() != '.pdf' or not path.is_file():
            raise FileNotFoundError('PDF unavailable in configured library')
        return path

    def detail(self, document_id: int, page: int = 1) -> dict:
        docs = [d for d in self.documents() if d['id'] == document_id]
        if not docs:
            raise FileNotFoundError('Document not found')
        doc = docs[0]
        with self.connection() as con:
            row = con.execute('SELECT id,content,page FROM chunks WHERE document_id=? AND page=? ORDER BY position LIMIT 1', (document_id, page)).fetchone()
        doc.update(page=page, excerpt=row['content'] if row else None, source_id=row['id'] if row else None,
                   abstract=None, authors=None, doi=None, metadata_provenance='Existing index / PDF metadata; not bibliographically validated')
        if doc['available']:
            import pymupdf
            with pymupdf.open(self.path(document_id)) as pdf:
                doc['pages'] = len(pdf)
                doc['authors'] = (pdf.metadata or {}).get('author') or None
        return doc

    def search(self, question: str, limit: int = 8) -> list[dict]:
        terms = re.findall(r'\w+', question, re.UNICODE)
        if not terms:
            return []
        expression = ' OR '.join('"' + term + '"' for term in terms)
        with self.connection() as con:
            if con is None:
                return []
            rows = con.execute('''SELECT c.id source_id,c.document_id,c.page,c.content excerpt,d.title,
                bm25(chunk_fts) rank FROM chunk_fts JOIN chunks c ON c.id=chunk_fts.rowid
                JOIN chunk_documents d ON d.id=c.document_id WHERE chunk_fts MATCH ?
                ORDER BY rank LIMIT ?''', (expression, min(limit * 10, 200))).fetchall()
        from retrieval import _too_similar
        chosen = []
        counts: dict[int, int] = {}
        for row in rows:
            item = dict(row)
            if counts.get(item['document_id'], 0) >= 2 or any(_too_similar(item['excerpt'], previous['excerpt']) for previous in chosen):
                continue
            item.pop('rank')  # Ranking utility is not scientific confidence.
            item['citation'] = f'S{len(chosen) + 1}'
            chosen.append(item)
            counts[item['document_id']] = counts.get(item['document_id'], 0) + 1
            if len(chosen) >= limit:
                break
        return chosen
