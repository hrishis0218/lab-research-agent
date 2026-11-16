"""Phase 2: incremental local passage indexing and hybrid retrieval."""
from __future__ import annotations

import re
import heapq
import math
import unicodedata
from collections import Counter
import sqlite3
from pathlib import Path
from functools import lru_cache

import fitz
import numpy as np
from core import connect

MODEL_NAME = "BAAI/bge-small-en-v1.5"
CHUNK_WORDS = 180
OVERLAP_WORDS = 35


def ensure_schema(db: sqlite3.Connection) -> None:
    db.executescript("""
      CREATE TABLE IF NOT EXISTS chunk_documents (
        id INTEGER PRIMARY KEY, path TEXT UNIQUE NOT NULL,
        title TEXT NOT NULL, size INTEGER NOT NULL, mtime_ns INTEGER NOT NULL
      );
      CREATE TABLE IF NOT EXISTS chunks (
        id INTEGER PRIMARY KEY, document_id INTEGER NOT NULL,
        page INTEGER NOT NULL, position INTEGER NOT NULL, content TEXT NOT NULL,
        embedding BLOB, model TEXT,
        FOREIGN KEY(document_id) REFERENCES chunk_documents(id)
      );
      CREATE INDEX IF NOT EXISTS chunks_document_idx ON chunks(document_id);
      CREATE VIRTUAL TABLE IF NOT EXISTS chunk_fts USING fts5(
        content, content='chunks', content_rowid='id', tokenize='unicode61'
      );
      CREATE TRIGGER IF NOT EXISTS chunks_insert AFTER INSERT ON chunks BEGIN
        INSERT INTO chunk_fts(rowid,content) VALUES(new.id,new.content);
      END;
      CREATE TRIGGER IF NOT EXISTS chunks_delete AFTER DELETE ON chunks BEGIN
        INSERT INTO chunk_fts(chunk_fts,rowid,content)
        VALUES('delete',old.id,old.content);
      END;
    """)


@lru_cache(maxsize=1)
def embedding_model():
    from fastembed import TextEmbedding
    return TextEmbedding(model_name=MODEL_NAME, threads=2)


def chunks_from_text(text: str):
    words = text.split()
    step = CHUNK_WORDS - OVERLAP_WORDS
    for start in range(0, len(words), step):
        part = words[start:start + CHUNK_WORDS]
        if part:
            yield " ".join(part)
        if start + CHUNK_WORDS >= len(words):
            break


def index_semantic(folder: str, db: sqlite3.Connection, with_embeddings=True) -> dict:
    ensure_schema(db)
    root = Path(folder).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"Folder does not exist: {root}")
    # Download/init only when embedding is requested.
    model = embedding_model() if with_embeddings else None
    result = {"indexed": 0, "unchanged": 0, "errors": []}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() != ".pdf":
            continue
        try:
            stat = path.stat()
            previous = db.execute(
                "SELECT id,size,mtime_ns FROM chunk_documents WHERE path=?", (str(path),)
            ).fetchone()
            current = bool(previous and previous["size"] == stat.st_size and
                           previous["mtime_ns"] == stat.st_mtime_ns)
            if current:
                if with_embeddings:
                    missing = db.execute("""SELECT COUNT(*) FROM chunks WHERE document_id=?
                      AND (embedding IS NULL OR model IS NULL OR model!=?)""",
                      (previous["id"], MODEL_NAME)).fetchone()[0]
                    if not missing:
                        result["unchanged"] += 1
                        continue
                    rows = db.execute("SELECT id,content FROM chunks WHERE document_id=? ORDER BY id",
                                      (previous["id"],)).fetchall()
                    vectors = list(model.passage_embed([r["content"] for r in rows], batch_size=16))
                    with db:
                        db.executemany("UPDATE chunks SET embedding=?,model=? WHERE id=?",
                            [(np.asarray(v,dtype=np.float32).tobytes(), MODEL_NAME, r["id"])
                             for r,v in zip(rows,vectors)])
                    result["indexed"] += 1
                    continue
                result["unchanged"] += 1
                continue
            with fitz.open(path) as pdf:
                if pdf.needs_pass:
                    raise ValueError("Password-protected PDF")
                title = (pdf.metadata or {}).get("title") or path.stem
                passages = [(number+1, i, passage)
                            for number,page in enumerate(pdf)
                            for i,passage in enumerate(chunks_from_text(page.get_text("text",sort=True)))]
            vectors = list(model.passage_embed([p[2] for p in passages],batch_size=16)) if model and passages else []
            with db:
                if previous:
                    doc_id = previous["id"]
                    db.execute("DELETE FROM chunks WHERE document_id=?", (doc_id,))
                    db.execute("UPDATE chunk_documents SET title=?,size=?,mtime_ns=? WHERE id=?",
                               (title,stat.st_size,stat.st_mtime_ns,doc_id))
                else:
                    doc_id = db.execute("INSERT INTO chunk_documents(path,title,size,mtime_ns) VALUES (?,?,?,?)",
                            (str(path),title,stat.st_size,stat.st_mtime_ns)).lastrowid
                db.executemany("""INSERT INTO chunks(document_id,page,position,content,embedding,model)
                  VALUES(?,?,?,?,?,?)""", [
                    (doc_id,page,pos,body,
                     np.asarray(vectors[j],dtype=np.float32).tobytes() if vectors else None,
                     MODEL_NAME if vectors else None)
                    for j,(page,pos,body) in enumerate(passages)])
            result["indexed"] += 1
        except Exception as exc:
            result["errors"].append(f"{path.name}: {exc}")
    return result


# Phase 2.1: query-aware ranking using the existing Phase 2 SQLite schema.
# No new dependencies, model downloads or re-indexing are required.

SUBSCRIPTS = str.maketrans("₀₁₂₃₄₅₆₇₈₉", "0123456789")
MATERIAL_ALIASES = {
    "tio2": ("tio2", "titanium dioxide", "titania"),
    "y2o3": ("y2o3", "yttrium oxide", "yttria"),
    "sio2": ("sio2", "silicon dioxide", "silica"),
    "nb2o5": ("nb2o5", "niobium pentoxide", "niobium oxide"),
    "zno": ("zno", "zinc oxide"),
    "al2o3": ("al2o3", "aluminium oxide", "aluminum oxide", "alumina"),
    "ag": ("silver", "ag nanoparticles", "ag films"),
}
STOP_WORDS = set("what which why when where how does do is are a an the and or of in on at with to for from as by can could role play thin film films structural structure changes change influence under effect effects physical mechanism mechanisms".split())
CONCEPT_GROUPS = (
    ("crystalli", ("crystalli", "anatase", "rutile", "nucleation", "phase transition", "grain growth")),
    ("vacanc", ("vacanc", "oxygen defect", "nonstoichiomet", "non-stoichiomet")),
    ("optical", ("optical", "refractive index", "ellipsometr", "absorption", "permittivity")),
    ("electric", ("electric field", "poling", "ion migration", "electromigration", "drift")),
    ("anneal", ("anneal", "thermal treatment", "heat treatment", "temperature")),
)


def _normalise(value: str) -> str:
    value = unicodedata.normalize("NFKC", value.translate(SUBSCRIPTS)).lower()
    # Treat TiO2 and Ti O2 alike, but avoid turning ordinary words into formulas.
    value = re.sub(r"\b(ti|si|nb|al|y)\s+(o\d+)\b", r"\1\2", value)
    return re.sub(r"\s+", " ", value).strip()


def _materials(text: str) -> set[str]:
    text = _normalise(text)
    result = set()
    for chemical, aliases in MATERIAL_ALIASES.items():
        for alias in aliases:
            # Ag alone is ambiguous (e.g. ordinary prose). Only accept the full expressions.
            if re.search(r"(?<![a-z0-9])" + re.escape(alias) + r"(?![a-z0-9])", text):
                result.add(chemical)
                break
    return result


def _concepts(text: str) -> set[str]:
    text = _normalise(text)
    return {name for name, terms in CONCEPT_GROUPS if any(t in text for t in terms)}


def _content_quality(content: str) -> float:
    text = _normalise(content)
    if len(text.split()) < 28:
        return -0.75
    penalty = 0.0
    if any(p in text for p in ("creative commons attribution", "all rights reserved", "published by elsevier", "open access under", "copyright ©", "copyright (c)")):
        penalty -= 1.1
    if re.search(r"\b(references|bibliography)\b", text[:140]):
        penalty -= 1.0
    # Dense citation strings without explanatory prose tend to be reference lists.
    if len(re.findall(r"\b(?:19|20)\d{2}\b", text)) >= 7 and len(re.findall(r"\b(?:doi|j\.|vol\.|pp\.)\b", text)) >= 3:
        penalty -= 0.7
    return penalty


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", _normalise(text)))


def _too_similar(a: str, b: str) -> bool:
    a_norm, b_norm = _normalise(a), _normalise(b)
    if a_norm == b_norm:
        return True
    # Overlapping adjacent chunks may share vocabulary. Only reject near-duplicates.
    a_terms, b_terms = _tokens(a_norm), _tokens(b_norm)
    if not a_terms or not b_terms:
        return False
    overlap = len(a_terms & b_terms) / len(a_terms | b_terms)
    return overlap > 0.90 and min(len(a_norm), len(b_norm)) / max(len(a_norm), len(b_norm)) > 0.80


def _query_bonus(question: str, title: str, content: str) -> float:
    wanted = _materials(question)
    title_materials = _materials(title)
    content_materials = _materials(content)
    joined = _normalise(title + " " + content)
    bonus = _content_quality(content)
    if wanted:
        if wanted & content_materials:
            bonus += 1.25
        if wanted & title_materials:
            bonus += 1.10
        if not (wanted & (content_materials | title_materials)):
            bonus -= 1.4
        # An unrelated oxide is not necessarily useless as an analogy, but rank it lower.
        if title_materials and title_materials.isdisjoint(wanted):
            bonus -= 1.25
    relevant_concepts = _concepts(question)
    matched_concepts = _concepts(joined) & relevant_concepts
    bonus += min(len(matched_concepts), 3) * 0.5
    query_terms = {w for w in _tokens(question) if len(w) > 3 and w not in STOP_WORDS}
    text_terms = _tokens(content)
    if query_terms:
        bonus += 0.8 * len(query_terms & text_terms) / len(query_terms)
    if re.search(r"\b(mechanism|why|how|role|cause)\b", _normalise(question)):
        if any(t in joined for t in ("due to", "attributed to", "induced by", "facilitat", "nucleation", "diffusion", "activation energy", "kinetic", "defect migration")):
            bonus += 0.5
    return bonus


def retrieve(question: str, db: sqlite3.Connection, limit=8, semantic=True,
             candidates=60, max_per_document=2) -> list[dict]:
    """Hybrid RRF retrieval with domain-aware re-ranking and duplicate suppression.

    Re-uses the exact Phase 2 schema and embedding model. 'score' is a ranking
    utility, NOT a calibrated probability of scientific relevance.
    """
    ensure_schema(db)
    terms = re.findall(r"\w+", _normalise(question), flags=re.UNICODE)
    if not terms or limit <= 0:
        return []
    fused: dict[int, float] = {}
    # FTS5 uses a simple OR baseline. RRF stabilises score scales.
    term_query = " OR ".join('"' + t.replace('"', '""') + '"' for t in terms)
    try:
        rows = db.execute("""SELECT rowid FROM chunk_fts WHERE chunk_fts MATCH ?
                           ORDER BY bm25(chunk_fts) LIMIT 150""", (term_query,)).fetchall()
    except sqlite3.OperationalError:
        rows = []
    for rank, row in enumerate(rows, 1):
        fused[row[0]] = fused.get(row[0], 0.0) + 1.0 / (60 + rank)
    if semantic:
        query_vec = np.asarray(next(iter(embedding_model().query_embed(question))), dtype=np.float32)
        query_norm = max(float(np.linalg.norm(query_vec)), 1e-9)
        # Keep only the top vectors; do not build an unbounded list of every embedding.
        best = []
        for row in db.execute("SELECT id,embedding FROM chunks WHERE model=? AND embedding IS NOT NULL", (MODEL_NAME,)):
            vector = np.frombuffer(row["embedding"], dtype=np.float32)
            if vector.shape != query_vec.shape:
                continue
            similarity = float(np.dot(query_vec, vector) / (query_norm * max(float(np.linalg.norm(vector)), 1e-9)))
            if len(best) < 150:
                heapq.heappush(best, (similarity, row["id"]))
            elif similarity > best[0][0]:
                heapq.heapreplace(best, (similarity, row["id"]))
        for rank, (_, chunk_id) in enumerate(sorted(best, reverse=True), 1):
            fused[chunk_id] = fused.get(chunk_id, 0.0) + 1.0 / (60 + rank)
    if not fused:
        return []
    shortlist = sorted(fused, key=fused.get, reverse=True)[:max(candidates, limit * 5)]
    marks = ",".join("?" for _ in shortlist)
    records = db.execute(f"""SELECT c.id,c.document_id,c.page,c.position,c.content,d.path,d.title
        FROM chunks c JOIN chunk_documents d ON d.id=c.document_id
        WHERE c.id IN ({marks})""", shortlist).fetchall()
    ranked = []
    for r in records:
        d = dict(r)
        # RRF is ~0.01–0.03. Convert to a comparable rank-based contribution.
        d["score"] = 30.0 * fused[d["id"]] + _query_bonus(question, d["title"], d["content"])
        ranked.append(d)
    ranked.sort(key=lambda d: (d["score"], fused[d["id"]]), reverse=True)
    chosen = []
    counts = Counter()
    for row in ranked:
        if counts[row["document_id"]] >= max_per_document:
            continue
        if any(_too_similar(row["content"], old["content"]) for old in chosen):
            continue
        chosen.append(row)
        counts[row["document_id"]] += 1
        if len(chosen) == limit:
            break
    for rank, row in enumerate(chosen, 1):
        row["citation"] = f"S{rank}"
        row["score"] = round(row["score"], 4)
    return chosen
