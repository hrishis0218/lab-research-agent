"""Durable local ingestion. All writes go to a disposable sidecar, never the legacy index."""
from __future__ import annotations
import hashlib
import json
import re
import sqlite3
import threading
import time
from contextlib import closing
from pathlib import Path
import pymupdf
import numpy as np
from backend.library import Library
from retrieval import ensure_schema, chunks_from_text, MODEL_NAME, retrieve


class SmartLibrary(Library):
    def __init__(self, legacy: Library, state: Path, embedder=None, metadata_lookup=None):
        state.parent.mkdir(parents=True, exist_ok=True)
        # SQLite backup includes committed WAL contents; original is opened read-only.
        if not state.exists():
            temporary = state.with_suffix('.initializing')
            with legacy.connection() as source, closing(sqlite3.connect(temporary)) as target:
                if source:
                    source.backup(target)
            temporary.replace(state)
        super().__init__(state, legacy.folder)
        self.embedder = embedder
        self.metadata_lookup = metadata_lookup
        self.stop_event = threading.Event()
        self.thread = None
        self.model_factory = None
        self.model_attempt = 0
        self.model_error = None
        self.scan_error = None
        with self.write() as db:
            ensure_schema(db)
            db.executescript('''
                CREATE TABLE IF NOT EXISTS discovery_failures(path TEXT PRIMARY KEY,error TEXT);
                CREATE TABLE IF NOT EXISTS doi_cache(doi TEXT PRIMARY KEY,record TEXT);
                CREATE TABLE IF NOT EXISTS identities(hash TEXT PRIMARY KEY, document_id INTEGER UNIQUE, metadata TEXT NOT NULL DEFAULT '{}');
                CREATE TABLE IF NOT EXISTS files(path TEXT PRIMARY KEY, hash TEXT, size INTEGER, mtime INTEGER, present INTEGER DEFAULT 1);
                CREATE TABLE IF NOT EXISTS jobs(hash TEXT PRIMARY KEY, state TEXT NOT NULL, attempts INTEGER DEFAULT 0, due REAL DEFAULT 0, error TEXT);
            ''')
            db.execute("UPDATE jobs SET state='pending' WHERE state='running'")
            db.commit()

    def write(self):
        return closing_connection(self.database)

    def discover(self):
        if not self.folder.is_dir():
            self.scan_error = 'Library folder unavailable; existing evidence retained.'
            return
        paths = list(self.folder.rglob('*'))
        seen = []
        for path in paths:
            if self.stop_event.is_set():
                return
            if not path.is_file() or path.suffix.lower() != '.pdf':
                continue
            path = path.resolve()
            if not path.is_relative_to(self.folder):
                continue
            try:
                key = str(path)
                stat = path.stat()
                with self.write() as db:
                    old = db.execute('SELECT * FROM files WHERE path=?', (key,)).fetchone()
                    if old and old['size'] == stat.st_size and old['mtime'] == stat.st_mtime_ns:
                        db.execute('UPDATE files SET present=1 WHERE path=?', (key,))
                    else:
                        with path.open('rb') as stream:
                            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
                        after = path.stat()
                        if (stat.st_size, stat.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                            continue  # Still being copied; next scan retries.
                        identity = db.execute('SELECT document_id FROM identities WHERE hash=?', (digest,)).fetchone()
                        if not identity:
                            legacy = db.execute('SELECT id,size,mtime_ns FROM chunk_documents WHERE path=?', (key,)).fetchone()
                            reusable = legacy and legacy['size'] == stat.st_size and legacy['mtime_ns'] == stat.st_mtime_ns
                            if reusable:
                                doc_id = legacy['id']
                            else:
                                doc_id = db.execute('INSERT INTO chunk_documents(path,title,size,mtime_ns) VALUES (?,?,?,?)',
                                    ('smart:'+digest, path.stem, stat.st_size, stat.st_mtime_ns)).lastrowid
                            db.execute('INSERT INTO identities(hash,document_id) VALUES (?,?)', (digest, doc_id))
                            db.execute("INSERT INTO jobs(hash,state) VALUES (?,'pending')", (digest,))
                        db.execute('INSERT OR REPLACE INTO files(path,hash,size,mtime,present) VALUES (?,?,?,?,1)',
                                   (key,digest,stat.st_size,stat.st_mtime_ns))
                    seen.append(key)
                with self.write() as db:
                    db.execute('DELETE FROM discovery_failures WHERE path=?',(str(path),))
            except OSError as exc:
                with self.write() as db:
                    db.execute('INSERT OR REPLACE INTO discovery_failures VALUES (?,?)',(str(path),type(exc).__name__))
        with self.write() as db:
            # Only a completed traversal may mark paths absent.
            db.execute('UPDATE files SET present=0')
            db.executemany('UPDATE files SET present=1 WHERE path=?', ((p,) for p in seen))
        self.scan_error = None

    def process_one(self):
        with self.write() as db:
            db.execute('BEGIN IMMEDIATE')
            job = db.execute("SELECT * FROM jobs WHERE state IN ('pending','retry') AND due<=? ORDER BY due LIMIT 1", (time.time(),)).fetchone()
            if not job:
                return False
            db.execute("UPDATE jobs SET state='running',attempts=attempts+1 WHERE hash=?", (job['hash'],))
        digest = job['hash']
        try:
            with self.write() as db:
                row = db.execute('SELECT path FROM files WHERE hash=? AND present=1 LIMIT 1', (digest,)).fetchone()
                identity = db.execute('SELECT document_id FROM identities WHERE hash=?', (digest,)).fetchone()
            if not row:
                raise ValueError('PDF unavailable')
            path = Path(row['path']).resolve()
            if not path.is_relative_to(self.folder):
                raise ValueError('PDF moved outside configured library')
            with path.open('rb') as stream:
                if hashlib.file_digest(stream, 'sha256').hexdigest() != digest:
                    raise ValueError('PDF changed during processing')
            with pymupdf.open(path) as pdf:
                if pdf.needs_pass:
                    raise ValueError('Password protected PDF')
                pages = [p.get_text('text', sort=True) for p in pdf]
                meta = pdf.metadata or {}
            if not any(p.strip() for p in pages):
                raise ValueError('No extractable text; OCR required')
            title = meta.get('title') or path.stem
            first = pages[0]
            match = re.search(r'10\.\d{4,9}/[^\s<>]+', first)
            metadata = {'authors': meta.get('author') or None, 'doi_candidate': match.group(0).rstrip('.,;)') if match else None,
                        'title': title, 'pages': len(pages), 'provenance': 'PDF metadata; unvalidated',
                        'categories': [term for term in ('oxide','annealing','optical','electrical','simulation') if term in (title+' '+first).lower()]}
            if match and self.metadata_lookup:
                from backend.documents.crossref import title_score
                try:
                    with self.write() as db:
                        cached=db.execute('SELECT record FROM doi_cache WHERE doi=?',(metadata['doi_candidate'],)).fetchone()
                    record = json.loads(cached[0]) if cached else self.metadata_lookup(metadata['doi_candidate'])
                    if not cached:
                        with self.write() as db:
                            db.execute('INSERT OR REPLACE INTO doi_cache VALUES (?,?)',(metadata['doi_candidate'],json.dumps(record)))
                except Exception:
                    record = {}
                    metadata['metadata_status'] = 'Crossref unavailable; PDF metadata retained'
                metadata['crossref_candidate'] = record
                if title_score(title, record.get('crossref_title','')) >= .85:
                    metadata.update(title=record['crossref_title'], authors=record.get('crossref_authors'), provenance='Crossref DOI/title match; automatic, review recommended')
            with self.write() as db:
                existing = db.execute('SELECT id,content,embedding,model FROM chunks WHERE document_id=? ORDER BY id', (identity[0],)).fetchall()
            # Preserve every seeded vector. New text only is embedded, in small CPU batches.
            passages = [(n+1,i,part) for n,text in enumerate(pages) for i,part in enumerate(chunks_from_text(text))]
            if existing:
                vectors = None
            else:
                vectors = list(self.embedder.passage_embed([p[2] for p in passages], batch_size=8)) if self.embedder else None
            with path.open('rb') as stream:
                if hashlib.file_digest(stream,'sha256').hexdigest()!=digest:
                    raise ValueError('PDF changed during extraction; retrying')
            with self.write() as db:
                if not existing:
                    db.executemany('INSERT INTO chunks(document_id,page,position,content,embedding,model) VALUES (?,?,?,?,?,?)',
                        [(identity[0],n,i,text,np.asarray(vectors[j],dtype=np.float32).tobytes() if vectors is not None else None, MODEL_NAME if vectors is not None else None) for j,(n,i,text) in enumerate(passages)])
                elif self.embedder:
                    missing = [r for r in existing if r['embedding'] is None]
                    for r,v in zip(missing,self.embedder.passage_embed([r['content'] for r in missing],batch_size=8)):
                        db.execute('UPDATE chunks SET embedding=?,model=? WHERE id=?',(np.asarray(v,dtype=np.float32).tobytes(),MODEL_NAME,r['id']))
                db.execute('UPDATE chunk_documents SET title=? WHERE id=?',(metadata['title'],identity[0]))
                db.execute('UPDATE identities SET metadata=? WHERE hash=?',(json.dumps(metadata),digest))
                db.execute("UPDATE jobs SET state=?,error=NULL,due=? WHERE hash=?", ('ready' if self.embedder else 'retry',time.time()+300,digest))
            return True
        except Exception as exc:
            with self.write() as db:
                db.execute("UPDATE jobs SET state='retry',error=?,due=? WHERE hash=?", (type(exc).__name__+': '+str(exc)[:250],time.time()+min(3600,30*2**min(job['attempts'],6)),digest))
            return True

    def stats(self):
        stats=super().stats()
        with self.write() as db:
            present=db.execute('SELECT count(*) FROM files WHERE present=1').fetchone()[0]
            indexed=db.execute("SELECT count(DISTINCT f.hash) FROM files f JOIN identities i ON i.hash=f.hash JOIN chunks c ON c.document_id=i.document_id WHERE f.present=1").fetchone()[0]
            copies=db.execute('SELECT count(*)-count(DISTINCT hash) FROM files WHERE present=1').fetchone()[0]
        stats['missing']=sum(not d['available'] for d in self.documents())
        stats.update(on_disk=present,indexed_on_disk=indexed,unindexed=max(0,present-copies-indexed),duplicate_copies=copies,duplicate_status='SHA-256 exact copies',mode='automatic sidecar')
        return stats

    def status(self):
        with self.write() as db:
            states = {r[0]:r[1] for r in db.execute('SELECT state,count(*) FROM jobs GROUP BY state')}
            return dict(states=states, files=db.execute('SELECT count(*) FROM files WHERE present=1').fetchone()[0],
                duplicate_copies=db.execute('SELECT count(*)-count(DISTINCT hash) FROM files WHERE present=1').fetchone()[0],
                semantic_available=self.embedder is not None, scan_error=self.scan_error, model_error=self.model_error,
                discovery_failures=[dict(r) for r in db.execute('SELECT error FROM discovery_failures')], failures=[dict(r) for r in db.execute('SELECT state,attempts,error FROM jobs WHERE error IS NOT NULL')])

    def path(self, document_id):
        with self.write() as db:
            rows = db.execute('SELECT f.path FROM files f JOIN identities i ON i.hash=f.hash WHERE i.document_id=? AND f.present=1',(document_id,)).fetchall()
        for row in rows:
            path = Path(row[0]).resolve()
            if path.is_relative_to(self.folder) and path.is_file():
                return path
        with self.write() as db:
            managed = db.execute('SELECT 1 FROM identities WHERE document_id=?',(document_id,)).fetchone()
        if managed:
            raise FileNotFoundError('PDF unavailable or replaced')
        path = super().path(document_id)
        with self.write() as db:
            tracked = db.execute('SELECT 1 FROM files WHERE path=?',(str(path),)).fetchone()
        if tracked:
            raise FileNotFoundError('Legacy PDF replaced; processing current version')
        return path

    def documents(self, query=''):
        docs = super().documents(query)
        for doc in docs:
            try:
                path = self.path(doc['id'])
                doc.update(available=True,filename=path.name)
            except FileNotFoundError:
                doc['available'] = False
        return docs

    def detail(self, document_id, page=1):
        doc = super().detail(document_id,page)
        with self.write() as db:
            row = db.execute('SELECT metadata FROM identities WHERE document_id=?',(document_id,)).fetchone()
        if row:
            meta=json.loads(row[0]); doc.update(authors=meta.get('authors'), metadata_provenance=meta.get('provenance','Pending identification'))
            doc['bibliography']=meta
        return doc

    def search(self, question, limit=8):
        with self.write() as db:
            rows=retrieve(question,db,limit=limit*3,semantic=self.embedder is not None,query_model=self.embedder)
        result=[]; seen=set()
        for row in rows:
            try: self.path(row['document_id'])
            except FileNotFoundError: continue
            identity=(row['document_id'],row['page'],row['content'])
            if identity in seen: continue
            seen.add(identity)
            result.append(dict(source_id=row['id'],document_id=row['document_id'],title=row['title'],page=row['page'],excerpt=row['content'],citation=f'S{len(result)+1}'))
            with self.write() as db:
                meta=db.execute('SELECT metadata FROM identities WHERE document_id=?',(row['document_id'],)).fetchone()
            result[-1]['bibliography']=json.loads(meta[0]) if meta else None
            if len(result)==limit: break
        return result

    def start(self):
        def run():
            while not self.stop_event.is_set():
                try:
                    self.discover()
                    if self.embedder is None and self.model_factory and time.time()-self.model_attempt > 300:
                        self.model_attempt=time.time()
                        try:
                            self.embedder=self.model_factory()
                            self.model_error=None
                            with self.write() as db:
                                db.execute("UPDATE jobs SET due=0 WHERE state='retry' AND error IS NULL")
                        except Exception:
                            self.model_error='Embedding model unavailable; keyword search remains available'
                    for _ in range(20):
                        if self.stop_event.is_set() or not self.process_one(): break
                except Exception as exc:
                    self.scan_error = type(exc).__name__+': scan temporarily unavailable'
                self.stop_event.wait(10)
        self.thread=threading.Thread(target=run,name='smart-library',daemon=True); self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread: self.thread.join(timeout=15)


class closing_connection:
    def __init__(self,path): self.path=path
    def __enter__(self):
        self.db=sqlite3.connect(self.path,timeout=30); self.db.row_factory=sqlite3.Row
        return self.db
    def __exit__(self,kind,value,tb):
        try:
            if kind: self.db.rollback()
            else: self.db.commit()
        finally: self.db.close()
