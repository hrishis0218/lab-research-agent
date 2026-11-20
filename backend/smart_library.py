"""Durable local ingestion. All writes go to a disposable sidecar, never the legacy index."""

from __future__ import annotations
import hashlib
import json
import re
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from threading import RLock
from contextlib import closing
from pathlib import Path
import pymupdf
from backend.identification import PDF_LOCK
from backend.ocr import readable_page
import numpy as np
from backend.library import Library
from retrieval import ensure_schema, chunks_from_text, MODEL_NAME, retrieve


class SmartLibrary(Library):
    def __init__(
        self,
        legacy: Library,
        state: Path,
        embedder=None,
        metadata_lookup=None,
        worker_mode=False,
    ):
        state.parent.mkdir(parents=True, exist_ok=True)
        self.worker_lock = None
        if worker_mode:
            import msvcrt

            self.worker_lock = open(str(state) + ".worker.lock", "a+b")
            self.worker_lock.seek(0)
            if not self.worker_lock.read(1):
                self.worker_lock.write(b"0")
                self.worker_lock.flush()
            self.worker_lock.seek(0)
            try:
                msvcrt.locking(self.worker_lock.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                self.worker_lock.close()
                self.worker_lock = None
                raise RuntimeError("Another Smart Library worker is active") from None

        import os

        lock_path = Path(str(state) + ".worker.lock")
        if (
            not worker_mode
            and os.name == "nt"
            and lock_path.exists()
            and lock_path.stat().st_size
        ):
            import msvcrt

            with lock_path.open("r+b") as probe:
                try:
                    msvcrt.locking(probe.fileno(), msvcrt.LK_NBLCK, 1)
                except OSError:
                    raise RuntimeError(
                        "Another Smart Library worker is active; refusing concurrent recovery"
                    ) from None
                msvcrt.locking(probe.fileno(), msvcrt.LK_UNLCK, 1)

        # SQLite backup includes committed WAL contents; original is opened read-only.
        if not state.exists():
            temporary = state.with_suffix(".initializing")
            with (
                legacy.connection() as source,
                closing(sqlite3.connect(temporary)) as target,
            ):
                if source:
                    source.backup(target)
            temporary.replace(state)
        super().__init__(state, legacy.folder)
        self.fs_lock = RLock()
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
            db.executescript("""
                CREATE TABLE IF NOT EXISTS discovery_failures(path TEXT PRIMARY KEY,error TEXT);
                CREATE TABLE IF NOT EXISTS doi_cache(doi TEXT PRIMARY KEY,record TEXT);
                CREATE TABLE IF NOT EXISTS identities(hash TEXT PRIMARY KEY, document_id INTEGER UNIQUE, metadata TEXT NOT NULL DEFAULT '{}');
                CREATE TABLE IF NOT EXISTS files(path TEXT PRIMARY KEY, hash TEXT, size INTEGER, mtime INTEGER, present INTEGER DEFAULT 1);
                CREATE TABLE IF NOT EXISTS jobs(hash TEXT PRIMARY KEY, state TEXT NOT NULL, attempts INTEGER DEFAULT 0, due REAL DEFAULT 0, error TEXT);
            """)
            db.execute("UPDATE jobs SET state='pending' WHERE state='running'")
            db.execute(
                "CREATE TABLE IF NOT EXISTS aliases(old_id INTEGER PRIMARY KEY, document_id INTEGER NOT NULL, evidence TEXT NOT NULL)"
            )
            db.execute("CREATE TABLE IF NOT EXISTS features(name TEXT PRIMARY KEY)")
            if not db.execute(
                "SELECT 1 FROM features WHERE name='local_ocr_v1'"
            ).fetchone():
                db.execute(
                    "UPDATE jobs SET due=0 WHERE state='retry' AND error LIKE '%OCR required%'"
                )
                db.execute("INSERT INTO features VALUES ('local_ocr_v1')")
            db.commit()
        from backend.organiser import Organiser
        from backend.identification import Identifier

        self.organiser = Organiser(self)
        self.identifier = Identifier(self)

    def identify_one(self, digest):
        if self.stop_event.is_set():
            return
        with self.write() as db:
            row = db.execute(
                "SELECT document_id,metadata FROM identities WHERE hash=?", (digest,)
            ).fetchone()
            paths = [
                Path(r[0])
                for r in db.execute(
                    "SELECT path FROM files WHERE hash=? AND present=1", (digest,)
                )
            ]
        if not paths:
            return
        try:
            metadata = self.identifier.identify(paths[0])
            # Keep metadata visible independently of slow embeddings/file locks.
            with self.write() as db:
                db.execute(
                    "UPDATE identities SET metadata=? WHERE hash=?",
                    (json.dumps(metadata), digest),
                )
                db.execute(
                    "UPDATE chunk_documents SET title=? WHERE id=?",
                    (metadata["title"], row["document_id"]),
                )
            if self.stop_event.is_set():
                return
            with self.fs_lock:
                for path in paths:
                    self.organiser.move(path, digest, metadata)
            with self.write() as db:
                ready = db.execute(
                    "SELECT state FROM jobs WHERE hash=?", (digest,)
                ).fetchone()
            metadata["stage"] = (
                "search_ready" if ready and ready[0] == "ready" else "organised"
            )
            with self.write() as db:
                db.execute(
                    "UPDATE identities SET metadata=? WHERE hash=?",
                    (json.dumps(metadata), digest),
                )
            # Reconcile missing legacy paths using two exact passage anchors on matching pages.
            with PDF_LOCK, pymupdf.open(self.path(row["document_id"])) as pdf:

                class PageText(dict):
                    def get(cache, number, default=""):
                        if number not in cache:
                            cache[number] = (
                                " ".join(
                                    pdf[number - 1].get_text("text", sort=True).split()
                                )
                                if 1 <= number <= len(pdf)
                                else ""
                            )
                        return super().get(number, default)

                page_text = PageText()
                with self.write() as db:
                    old = db.execute(
                        "SELECT id,path FROM chunk_documents WHERE id NOT IN (SELECT document_id FROM identities) AND id NOT IN (SELECT old_id FROM aliases WHERE evidence NOT LIKE 'Rejected:%')"
                    ).fetchall()
                    for candidate in old:
                        samples = db.execute(
                            "SELECT page,content FROM chunks WHERE document_id=? AND length(content)>180 ORDER BY id LIMIT 3",
                            (candidate["id"],),
                        ).fetchall()
                        matches = len(samples) >= 2 and all(
                            " ".join(r["content"].split())
                            in page_text.get(r["page"], "")
                            for r in samples
                        )
                        if matches:
                            all_chunks = db.execute(
                                "SELECT page,content FROM chunks WHERE document_id=?",
                                (candidate["id"],),
                            ).fetchall()
                            matches = all(
                                " ".join(r["content"].split())
                                in page_text.get(r["page"], "")
                                for r in all_chunks
                            )
                        if (
                            matches
                            and not db.execute(
                                "SELECT 1 FROM chunks WHERE document_id=? LIMIT 1",
                                (row["document_id"],),
                            ).fetchone()
                        ):
                            # Rebind a newly discovered placeholder to the proven legacy identity.
                            db.execute(
                                "UPDATE identities SET document_id=? WHERE hash=?",
                                (candidate["id"], digest),
                            )
                            db.execute(
                                "UPDATE chunk_documents SET title=? WHERE id=?",
                                (metadata["title"], candidate["id"]),
                            )
                            db.execute(
                                "INSERT OR IGNORE INTO aliases VALUES (?,?,?)",
                                (
                                    row["document_id"],
                                    candidate["id"],
                                    "Unchanged PDF: reused legacy chunks and embeddings",
                                ),
                            )
                            break
                        if matches:
                            db.execute(
                                "INSERT OR IGNORE INTO aliases VALUES (?,?,?)",
                                (
                                    candidate["id"],
                                    row["document_id"],
                                    "All indexed passages matched exact page-level text",
                                ),
                            )
        except Exception as exc:
            with self.write() as db:
                metadata = json.loads(
                    db.execute(
                        "SELECT metadata FROM identities WHERE hash=?", (digest,)
                    ).fetchone()[0]
                )
                metadata.update(
                    version=4,
                    stage="needs_attention",
                    processing_error=type(exc).__name__,
                    next_retry=time.time() + 300,
                )
                db.execute(
                    "UPDATE identities SET metadata=? WHERE hash=?",
                    (json.dumps(metadata), digest),
                )

    def audit_aliases(self):
        with self.write() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS alias_review(old_id INTEGER,document_id INTEGER,evidence TEXT,reason TEXT,created TEXT DEFAULT CURRENT_TIMESTAMP)"
            )
            rows = db.execute(
                "SELECT * FROM aliases WHERE evidence NOT LIKE 'Unchanged PDF:%'"
            ).fetchall()
        for row in rows:
            if self.stop_event.is_set():
                return
            try:
                with PDF_LOCK, pymupdf.open(self.path(row["document_id"])) as pdf:
                    pages = {
                        n + 1: " ".join(readable_page(p)[0].split())
                        for n, p in enumerate(pdf)
                    }
                with self.write() as db:
                    chunks = db.execute(
                        "SELECT page,content FROM chunks WHERE document_id=?",
                        (row["old_id"],),
                    ).fetchall()
                    valid = bool(chunks) and all(
                        " ".join(c["content"].split()) in pages.get(c["page"], "")
                        for c in chunks
                    )
                    if valid:
                        db.execute(
                            "UPDATE aliases SET evidence=? WHERE old_id=?",
                            (
                                "All indexed passages matched exact page-level text",
                                row["old_id"],
                            ),
                        )
                    elif not row["evidence"].startswith("Rejected:"):
                        db.execute(
                            "INSERT INTO alias_review(old_id,document_id,evidence,reason) VALUES (?,?,?,?)",
                            (
                                row["old_id"],
                                row["document_id"],
                                row["evidence"],
                                "Some indexed passages did not occur on the target PDF page",
                            ),
                        )
                        db.execute(
                            "UPDATE aliases SET evidence='Rejected: page evidence mismatch' WHERE old_id=?",
                            (row["old_id"],),
                        )
            except Exception:
                continue

    def write(self):
        return closing_connection(self.database)

    def discover(self):
        if not self.folder.is_dir():
            self.scan_error = "Library folder unavailable; existing evidence retained."
            return
        paths = list(self.folder.rglob("*"))
        seen = []
        for path in paths:
            if self.stop_event.is_set():
                return
            if not path.is_file() or path.suffix.lower() != ".pdf":
                continue
            path = path.resolve()
            if not path.is_relative_to(self.folder):
                continue
            try:
                key = str(path)
                stat = path.stat()
                with self.write() as db:
                    old = db.execute(
                        "SELECT * FROM files WHERE path=?", (key,)
                    ).fetchone()
                    if (
                        old
                        and old["size"] == stat.st_size
                        and old["mtime"] == stat.st_mtime_ns
                    ):
                        db.execute("UPDATE files SET present=1 WHERE path=?", (key,))
                    else:
                        with path.open("rb") as stream:
                            digest = hashlib.file_digest(stream, "sha256").hexdigest()
                        after = path.stat()
                        if (stat.st_size, stat.st_mtime_ns) != (
                            after.st_size,
                            after.st_mtime_ns,
                        ):
                            continue  # Still being copied; next scan retries.
                        identity = db.execute(
                            "SELECT document_id FROM identities WHERE hash=?", (digest,)
                        ).fetchone()
                        if not identity:
                            legacy = db.execute(
                                "SELECT id,size,mtime_ns FROM chunk_documents WHERE path=?",
                                (key,),
                            ).fetchone()
                            reusable = (
                                legacy
                                and legacy["size"] == stat.st_size
                                and legacy["mtime_ns"] == stat.st_mtime_ns
                            )
                            if reusable:
                                doc_id = legacy["id"]
                            else:
                                doc_id = db.execute(
                                    "INSERT INTO chunk_documents(path,title,size,mtime_ns) VALUES (?,?,?,?)",
                                    (
                                        "smart:" + digest,
                                        path.stem,
                                        stat.st_size,
                                        stat.st_mtime_ns,
                                    ),
                                ).lastrowid
                            db.execute(
                                "INSERT INTO identities(hash,document_id) VALUES (?,?)",
                                (digest, doc_id),
                            )
                            db.execute(
                                "INSERT INTO jobs(hash,state) VALUES (?,'pending')",
                                (digest,),
                            )
                        db.execute(
                            "INSERT OR REPLACE INTO files(path,hash,size,mtime,present) VALUES (?,?,?,?,1)",
                            (key, digest, stat.st_size, stat.st_mtime_ns),
                        )
                    seen.append(key)
                with self.write() as db:
                    db.execute(
                        "DELETE FROM discovery_failures WHERE path=?", (str(path),)
                    )
            except OSError as exc:
                with self.write() as db:
                    db.execute(
                        "INSERT OR REPLACE INTO discovery_failures VALUES (?,?)",
                        (str(path), type(exc).__name__),
                    )
        with self.write() as db:
            # Only a completed traversal may mark paths absent.
            db.execute("UPDATE files SET present=0")
            db.executemany(
                "UPDATE files SET present=1 WHERE path=?", ((p,) for p in seen)
            )
        self.scan_error = None

    def process_one(self):
        with self.write() as db:
            db.execute("BEGIN IMMEDIATE")
            job = db.execute(
                "SELECT * FROM jobs WHERE state IN ('pending','retry') AND due<=? ORDER BY due LIMIT 1",
                (time.time(),),
            ).fetchone()
            if not job:
                return False
            db.execute(
                "UPDATE jobs SET state='running',attempts=attempts+1 WHERE hash=?",
                (job["hash"],),
            )
        digest = job["hash"]
        try:
            with self.write() as db:
                row = db.execute(
                    "SELECT path FROM files WHERE hash=? AND present=1 LIMIT 1",
                    (digest,),
                ).fetchone()
                identity = db.execute(
                    "SELECT document_id FROM identities WHERE hash=?", (digest,)
                ).fetchone()
            if not row:
                raise ValueError("PDF unavailable")
            path = Path(row["path"]).resolve()
            if not path.is_relative_to(self.folder):
                raise ValueError("PDF moved outside configured library")
            with path.open("rb") as stream:
                if hashlib.file_digest(stream, "sha256").hexdigest() != digest:
                    raise ValueError("PDF changed during processing")
            with PDF_LOCK, pymupdf.open(path) as pdf:
                if pdf.needs_pass:
                    raise ValueError("Password protected PDF")
                page_data = [readable_page(p)[:2] for p in pdf]
                pages = [text for text, used_ocr in page_data]
                ocr_used = any(flag for text, flag in page_data)
                meta = pdf.metadata or {}
            if not any(p.strip() for p in pages):
                raise ValueError("No extractable text; OCR required")
            with self.write() as db:
                prepared = json.loads(
                    db.execute(
                        "SELECT metadata FROM identities WHERE hash=?", (digest,)
                    ).fetchone()[0]
                )
            title = prepared.get("title") or meta.get("title") or path.stem
            first = pages[0]
            match = re.search(r"10\.\d{4,9}/[^\s<>]+", first)
            metadata = {
                "authors": meta.get("author") or None,
                "doi_candidate": match.group(0).rstrip(".,;)") if match else None,
                "title": title,
                "pages": len(pages),
                "provenance": "PDF metadata; unvalidated",
                "categories": [
                    term
                    for term in (
                        "oxide",
                        "annealing",
                        "optical",
                        "electrical",
                        "simulation",
                    )
                    if term in (title + " " + first).lower()
                ],
            }
            if prepared.get("version", 0) >= 2:
                metadata = prepared
            if match and self.metadata_lookup and prepared.get("version") != 4:
                from backend.documents.crossref import title_score

                try:
                    with self.write() as db:
                        cached = db.execute(
                            "SELECT record FROM doi_cache WHERE doi=?",
                            (metadata["doi_candidate"],),
                        ).fetchone()
                    record = (
                        json.loads(cached[0])
                        if cached
                        else self.metadata_lookup(metadata["doi_candidate"])
                    )
                    if not cached:
                        with self.write() as db:
                            db.execute(
                                "INSERT OR REPLACE INTO doi_cache VALUES (?,?)",
                                (metadata["doi_candidate"], json.dumps(record)),
                            )
                except Exception:
                    record = {}
                    metadata["metadata_status"] = (
                        "Crossref unavailable; PDF metadata retained"
                    )
                metadata["crossref_candidate"] = record
                if title_score(title, record.get("crossref_title", "")) >= 0.85:
                    metadata.update(
                        title=record["crossref_title"],
                        authors=record.get("crossref_authors"),
                        provenance="Crossref DOI/title match; automatic, review recommended",
                    )
            if ocr_used:
                if prepared.get("text_origin") != "ocr":
                    metadata["version"] = 2
                metadata["text_origin"] = "ocr"
                metadata["extraction_warning"] = (
                    "OCR text may misread scientific numbers, units and equations; verify the original page"
                )
            with self.write() as db:
                existing = db.execute(
                    "SELECT id,content,embedding,model FROM chunks WHERE document_id=? ORDER BY id",
                    (identity[0],),
                ).fetchall()
            # Preserve every seeded vector. New text only is embedded, in small CPU batches.
            passages = [
                (n + 1, i, part)
                for n, text in enumerate(pages)
                for i, part in enumerate(chunks_from_text(text))
            ]
            if existing:
                vectors = None
            else:
                vectors = (
                    list(
                        self.embedder.passage_embed(
                            [p[2] for p in passages], batch_size=8
                        )
                    )
                    if self.embedder
                    else None
                )
            with path.open("rb") as stream:
                if hashlib.file_digest(stream, "sha256").hexdigest() != digest:
                    raise ValueError("PDF changed during extraction; retrying")
            with self.write() as db:
                if not existing:
                    db.executemany(
                        "INSERT INTO chunks(document_id,page,position,content,embedding,model) VALUES (?,?,?,?,?,?)",
                        [
                            (
                                identity[0],
                                n,
                                i,
                                text,
                                np.asarray(vectors[j], dtype=np.float32).tobytes()
                                if vectors is not None
                                else None,
                                MODEL_NAME if vectors is not None else None,
                            )
                            for j, (n, i, text) in enumerate(passages)
                        ],
                    )
                elif self.embedder:
                    missing = [r for r in existing if r["embedding"] is None]
                    for r, v in zip(
                        missing,
                        self.embedder.passage_embed(
                            [r["content"] for r in missing], batch_size=8
                        ),
                    ):
                        db.execute(
                            "UPDATE chunks SET embedding=?,model=? WHERE id=?",
                            (
                                np.asarray(v, dtype=np.float32).tobytes(),
                                MODEL_NAME,
                                r["id"],
                            ),
                        )
                db.execute(
                    "UPDATE chunk_documents SET title=? WHERE id=?",
                    (metadata["title"], identity[0]),
                )
                metadata["stage"] = "search_ready" if self.embedder else "text_ready"
                db.execute(
                    "UPDATE identities SET metadata=? WHERE hash=?",
                    (json.dumps(metadata), digest),
                )
                db.execute(
                    "UPDATE jobs SET state=?,error=NULL,due=? WHERE hash=?",
                    ("ready" if self.embedder else "retry", time.time() + 300, digest),
                )
            return True
        except Exception as exc:
            with self.write() as db:
                db.execute(
                    "UPDATE jobs SET state='retry',error=?,due=? WHERE hash=?",
                    (
                        type(exc).__name__ + ": " + str(exc)[:250],
                        time.time() + min(3600, 30 * 2 ** min(job["attempts"], 6)),
                        digest,
                    ),
                )
            return True

    def stats(self):
        with self.write() as db:
            present = db.execute(
                "SELECT count(*) FROM files WHERE present=1"
            ).fetchone()[0]
            indexed = db.execute(
                "SELECT count(DISTINCT f.hash) FROM files f JOIN identities i ON i.hash=f.hash JOIN chunks c ON c.document_id=i.document_id WHERE f.present=1"
            ).fetchone()[0]
            copies = db.execute(
                "SELECT count(*)-count(DISTINCT hash) FROM files WHERE present=1"
            ).fetchone()[0]
            passages = db.execute(
                "SELECT count(*) FROM chunks WHERE document_id IN (SELECT document_id FROM identities)"
            ).fetchone()[0]
            missing = db.execute(
                "SELECT count(*) FROM chunk_documents WHERE id NOT IN (SELECT document_id FROM identities) AND id NOT IN (SELECT old_id FROM aliases WHERE evidence NOT LIKE 'Rejected:%')"
            ).fetchone()[0]
        return dict(
            on_disk=present,
            indexed=indexed,
            indexed_on_disk=indexed,
            unindexed=max(0, present - copies - indexed),
            missing=missing,
            passages=passages,
            duplicate_copies=copies,
            duplicate_status="SHA-256 exact copies",
            mode="automatic sidecar",
            database_available=True,
            folder_available=self.folder.is_dir(),
        )

    def status(self):
        with self.write() as db:
            metadata = [
                json.loads(r[0]) for r in db.execute("SELECT metadata FROM identities")
            ]
            states = {
                r[0]: r[1]
                for r in db.execute("SELECT state,count(*) FROM jobs GROUP BY state")
            }
            return dict(
                metadata_unverified=sum(not bool(m.get("verified")) for m in metadata),
                metadata_verified=sum(bool(m.get("verified")) for m in metadata),
                metadata_preparing=sum(
                    m.get("version") != 4 or m.get("stage") == "identified"
                    for m in metadata
                ),
                metadata_attention=sum(
                    m.get("stage") == "needs_attention" for m in metadata
                ),
                states=states,
                files=db.execute(
                    "SELECT count(*) FROM files WHERE present=1"
                ).fetchone()[0],
                duplicate_copies=db.execute(
                    "SELECT count(*)-count(DISTINCT hash) FROM files WHERE present=1"
                ).fetchone()[0],
                semantic_available=self.embedder is not None,
                scan_error=self.scan_error,
                model_error=self.model_error,
                discovery_failures=[
                    dict(r) for r in db.execute("SELECT error FROM discovery_failures")
                ],
                failures=[
                    dict(r)
                    for r in db.execute(
                        "SELECT state,attempts,error FROM jobs WHERE error IS NOT NULL"
                    )
                ],
            )

    def path(self, document_id):
        with self.write() as db:
            alias = db.execute(
                "SELECT document_id,evidence FROM aliases WHERE old_id=? AND old_id NOT IN (SELECT document_id FROM identities)",
                (document_id,),
            ).fetchone()
        if alias:
            if not alias["evidence"].startswith(
                ("All indexed passages", "Unchanged PDF:")
            ):
                raise FileNotFoundError(
                    "Historical source awaits page-level reconciliation"
                )
            document_id = alias[0]
        with self.write() as db:
            rows = db.execute(
                "SELECT f.path FROM files f JOIN identities i ON i.hash=f.hash WHERE i.document_id=? AND f.present=1",
                (document_id,),
            ).fetchall()
        for row in rows:
            path = Path(row[0]).resolve()
            if path.is_relative_to(self.folder) and path.is_file():
                return path
        # Resolve the journalled target during the filesystem/SQLite commit window.
        with self.write() as db:
            pending = db.execute(
                "SELECT m.new,m.old,m.hash,m.state FROM moves m JOIN identities i ON i.hash=m.hash WHERE i.document_id=? AND m.state IN ('planned','undo_planned') ORDER BY m.id DESC",
                (document_id,),
            ).fetchall()
        from backend.documents.audit import sha256_file

        for item in pending:
            target = Path(
                item["old"] if item["state"] == "undo_planned" else item["new"]
            ).resolve()
            if (
                target.is_relative_to(self.folder)
                and target.is_file()
                and sha256_file(target) == item["hash"]
            ):
                return target
        with self.write() as db:
            managed = db.execute(
                "SELECT 1 FROM identities WHERE document_id=?", (document_id,)
            ).fetchone()
        if managed:
            raise FileNotFoundError("PDF unavailable or replaced")
        path = super().path(document_id)
        with self.write() as db:
            tracked = db.execute(
                "SELECT 1 FROM files WHERE path=?", (str(path),)
            ).fetchone()
        if tracked:
            raise FileNotFoundError("Legacy PDF replaced; processing current version")
        return path

    def documents(self, query=""):
        with self.write() as db:
            rows = db.execute(
                "SELECT d.id,d.title,i.metadata,count(c.id) passages,max(c.page) pages FROM identities i JOIN chunk_documents d ON d.id=i.document_id LEFT JOIN chunks c ON c.document_id=d.id GROUP BY d.id ORDER BY d.title COLLATE NOCASE"
            ).fetchall()
            attachments = {}
            for item in db.execute(
                "SELECT i.document_id,f.path,f.present FROM files f JOIN identities i ON i.hash=f.hash"
            ):
                attachments.setdefault(item["document_id"], []).append(dict(item))
        result = []
        for row in rows:
            meta = json.loads(row["metadata"])
            files = attachments.get(row["id"], [])
            present = [f for f in files if f["present"]]
            filename = Path(present[0]["path"]).name if present else "Unavailable PDF"
            if (
                query
                and query.casefold()
                not in (
                    row["title"] + filename + json.dumps(meta, ensure_ascii=False)
                ).casefold()
            ):
                continue
            result.append(
                dict(
                    id=row["id"],
                    title=row["title"],
                    pages=meta.get("pages") or row["pages"],
                    passages=row["passages"],
                    filename=filename,
                    available=bool(present),
                    bibliography=meta,
                    processing_state=meta.get("stage", "discovered"),
                    attachments=[
                        {
                            "filename": Path(f["path"]).name,
                            "available": bool(f["present"]),
                        }
                        for f in files
                    ],
                )
            )
        return result

    def detail(self, document_id, page=1):
        with self.write() as db:
            alias = db.execute(
                "SELECT document_id,evidence FROM aliases WHERE old_id=? AND old_id NOT IN (SELECT document_id FROM identities)",
                (document_id,),
            ).fetchone()
            if alias:
                document_id = alias[0]
            row = db.execute(
                "SELECT d.id,d.title,i.metadata FROM chunk_documents d JOIN identities i ON i.document_id=d.id WHERE d.id=?",
                (document_id,),
            ).fetchone()
            if not row:
                raise FileNotFoundError("Document not found")
            source = db.execute(
                "SELECT id,content FROM chunks WHERE document_id=? AND page=? ORDER BY position LIMIT 1",
                (document_id, page),
            ).fetchone()
            passages = db.execute(
                "SELECT count(*) FROM chunks WHERE document_id=?", (document_id,)
            ).fetchone()[0]
        meta = json.loads(row["metadata"])
        try:
            path = self.path(document_id)
            available = True
        except FileNotFoundError:
            path = None
            available = False
        return dict(
            id=document_id,
            title=row["title"],
            filename=path.name if path else "Unavailable PDF",
            available=available,
            pages=meta.get("pages") or 0,
            passages=passages,
            page=page,
            excerpt=source["content"] if source else None,
            source_id=source["id"] if source else None,
            authors=meta.get("authors"),
            abstract=meta.get("abstract"),
            doi=meta.get("doi"),
            bibliography=meta,
            metadata_provenance=meta.get("provenance", "Metadata preparation pending"),
        )

    def search(self, question, limit=8):
        with self.write() as db:
            rows = retrieve(
                question,
                db,
                limit=limit * 3,
                semantic=self.embedder is not None,
                query_model=self.embedder,
            )
        result = []
        seen = set()
        publications = {}
        for row in rows:
            try:
                self.path(row["document_id"])
            except FileNotFoundError:
                continue
            with self.write() as db:
                alias = db.execute(
                    "SELECT document_id FROM aliases WHERE old_id=? AND old_id NOT IN (SELECT document_id FROM identities)",
                    (row["document_id"],),
                ).fetchone()
                if alias:
                    row["document_id"] = alias[0]
                identity_meta = db.execute(
                    "SELECT metadata FROM identities WHERE document_id=?",
                    (row["document_id"],),
                ).fetchone()
            bibliography = json.loads(identity_meta[0]) if identity_meta else {}
            publication = bibliography.get("doi") or str(row["document_id"])
            if publications.get(publication, 0) >= 2:
                continue
            identity = (row["document_id"], row["page"], row["content"])
            if identity in seen:
                continue
            seen.add(identity)
            publications[publication] = publications.get(publication, 0) + 1
            result.append(
                dict(
                    source_id=row["id"],
                    document_id=row["document_id"],
                    title=row["title"],
                    page=row["page"],
                    excerpt=row["content"],
                    citation=f"S{len(result) + 1}",
                )
            )
            with self.write() as db:
                meta = db.execute(
                    "SELECT metadata FROM identities WHERE document_id=?",
                    (row["document_id"],),
                ).fetchone()
            result[-1]["bibliography"] = json.loads(meta[0]) if meta else None
            if len(result) == limit:
                break
        return result

    def start(self):
        import os

        if os.name == "nt" and self.worker_lock is None:
            import msvcrt

            self.worker_lock = open(str(self.database) + ".worker.lock", "a+b")
            self.worker_lock.seek(0)
            if self.worker_lock.read(1) == b"":
                self.worker_lock.write(b"0")
                self.worker_lock.flush()
            self.worker_lock.seek(0)
            try:
                msvcrt.locking(self.worker_lock.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                self.worker_lock.close()
                self.worker_lock = None
                raise RuntimeError(
                    "Another Smart Library worker is already running for this database"
                ) from None

        def run():
            self.audit_aliases()
            while not self.stop_event.is_set():
                try:
                    with self.fs_lock:
                        self.discover()
                    with self.write() as db:
                        candidates = db.execute(
                            "SELECT i.hash,i.metadata FROM identities i WHERE EXISTS (SELECT 1 FROM files f WHERE f.hash=i.hash AND f.present=1) ORDER BY document_id DESC"
                        ).fetchall()
                    identification = []
                    for row in candidates:
                        metadata = json.loads(row["metadata"])
                        if (
                            (
                                metadata.get("metadata_errors")
                                and metadata.get("metadata_retry_after", float("inf"))
                                < time.time()
                            )
                            or metadata.get("version") != 4
                            or metadata.get("stage") == "identified"
                            or (
                                metadata.get("stage") == "needs_attention"
                                and metadata.get("next_retry", float("inf"))
                                < time.time()
                            )
                        ):
                            identification.append(row["hash"])
                    with ThreadPoolExecutor(max_workers=3) as pool:
                        for digest in identification[:36]:
                            if self.stop_event.is_set():
                                break
                            pool.submit(self.identify_one, digest)
                    if (
                        self.embedder is None
                        and self.model_factory
                        and time.time() - self.model_attempt > 300
                    ):
                        self.model_attempt = time.time()
                        try:
                            self.embedder = self.model_factory()
                            self.model_error = None
                            with self.write() as db:
                                db.execute(
                                    "UPDATE jobs SET due=0 WHERE state='retry' AND error IS NULL"
                                )
                        except Exception:
                            self.model_error = "Embedding model unavailable; keyword search remains available"
                    for _ in range(20):
                        if self.stop_event.is_set() or not self.process_one():
                            break
                except Exception as exc:
                    self.scan_error = (
                        type(exc).__name__ + ": scan temporarily unavailable"
                    )
                self.stop_event.wait(10)

        original_run = run

        def guarded_run():
            try:
                original_run()
            finally:
                if self.worker_lock:
                    self.worker_lock.close()
                    self.worker_lock = None

        self.thread = threading.Thread(
            target=guarded_run, name="smart-library", daemon=True
        )
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=15)


class closing_connection:
    def __init__(self, path):
        self.path = path

    def __enter__(self):
        self.db = sqlite3.connect(self.path, timeout=30)
        self.db.row_factory = sqlite3.Row
        return self.db

    def __exit__(self, kind, value, tb):
        try:
            if kind:
                self.db.rollback()
            else:
                self.db.commit()
        finally:
            self.db.close()
