"""Read-only scientific PDF audit: metadata, hashes and proposed filenames.

No input PDF is modified. No database is opened or changed.
"""
from __future__ import annotations

import csv
import hashlib
import re
import unicodedata
from collections import defaultdict
from pathlib import Path

import pymupdf

DOI_PATTERN = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Za-z0-9]+", re.I)
BAD_TITLES = {"untitled", "title", "document", "microsoft word", "article", "paper"}
CSV_FIELDS = [
    "path", "sha256", "duplicate_of", "pages", "title", "title_source",
    "author", "year", "doi", "abstract", "proposed_filename",
    "metadata_review_required", "error",
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def clean_text(value: str) -> str:
    return " ".join((value or "").split())


def plausible_title(title: str, fallback_stem: str) -> bool:
    t = clean_text(title).strip(" .-_")
    stem = clean_text(fallback_stem).lower()
    return (
        12 <= len(t) <= 220
        and t.lower() not in BAD_TITLES
        and not t.lower().startswith(("http://", "https://"))
        and t.lower() != stem
        and not re.fullmatch(r"[\w.-]+\.pdf", t, re.I)
        and not re.search(r"\b(?:doi|issn|abstract)\s*:", t, re.I)
    )


def title_from_page(page) -> str:
    """Conservative font-size title candidate. Never claim high confidence."""
    data = page.get_text("dict", sort=True)
    candidates = []
    for block in data.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            spans = [s for s in line.get("spans", []) if clean_text(s.get("text", ""))]
            if not spans:
                continue
            text = clean_text(" ".join(s["text"] for s in spans))
            size = max(float(s.get("size", 0)) for s in spans)
            y = min(float(s["bbox"][1]) for s in spans)
            if y < page.rect.height * .65 and plausible_title(text, "") and size >= 11:
                candidates.append((size, y, text))
    if not candidates:
        return ""
    candidates.sort(key=lambda c: (-c[0], c[1]))
    return candidates[0][2]


def extract_abstract(text: str) -> str:
    """Best-effort first-page abstract; empty if boundaries are ambiguous."""
    match = re.search(r"\babstract\b\s*[:\u2014-]?\s*", text, re.I)
    if not match:
        return ""
    tail = text[match.end():]
    end = re.search(
        r"\n\s*(?:1\.?\s+introduction|introduction|keywords?\s*[:\u2014]|"
        r"received\s*[:\u2014]|©|copyright)\b", tail, re.I
    )
    candidate = clean_text(tail[:end.start() if end else min(len(tail), 2200)])
    return candidate[:1800] if 80 <= len(candidate) <= 1800 else ""


def safe_filename(title: str, year: str, fallback: str) -> str:
    label = title if title else fallback
    label = unicodedata.normalize("NFKD", label)
    label = "".join(ch for ch in label if not unicodedata.combining(ch))
    label = re.sub(r"[^A-Za-z0-9]+", "_", label).strip("_")
    label = label[:110].rstrip("_") or "unidentified_paper"
    prefix = year if re.fullmatch(r"(?:19|20)\d{2}", year or "") else "Undated"
    return f"{prefix}_{label}.pdf"


def inspect_pdf(path: Path) -> dict[str, str]:
    result = {field: "" for field in CSV_FIELDS}
    result["path"] = str(path)
    try:
        result["sha256"] = sha256_file(path)
        with pymupdf.open(path) as pdf:
            if pdf.needs_pass:
                raise ValueError("Password-protected PDF")
            result["pages"] = str(len(pdf))
            metadata = pdf.metadata or {}
            page = pdf[0] if len(pdf) else None
            first_text = page.get_text("text", sort=True) if page else ""
            metadata_title = clean_text(metadata.get("title", ""))
            if plausible_title(metadata_title, path.stem):
                title, source = metadata_title, "pdf_metadata"
            else:
                title = title_from_page(page) if page else ""
                source = "first_page_candidate" if title else "unidentified"
            result["title"] = title
            result["title_source"] = source
            result["author"] = clean_text(metadata.get("author", ""))
            doi_match = DOI_PATTERN.search(first_text[:10000])
            if doi_match:
                result["doi"] = doi_match.group().rstrip(".,;:)]}")
            result["abstract"] = extract_abstract(first_text)
            year_match = re.search(r"\b(?:19|20)\d{2}\b", first_text[:4000])
            if year_match:
                result["year"] = year_match.group()
            result["proposed_filename"] = safe_filename(title, result["year"], path.stem)
            result["metadata_review_required"] = "yes" if source != "pdf_metadata" or not result["doi"] else "no"
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        result["metadata_review_required"] = "yes"
    return result


def audit_folder(folder: str | Path, output_csv: str | Path) -> dict[str, int]:
    root = Path(folder).expanduser().resolve()
    destination = Path(output_csv).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"PDF folder does not exist: {root}")
    paths = sorted(p for p in root.rglob("*") if p.is_file() and p.suffix.lower() == ".pdf")
    results = [inspect_pdf(path) for path in paths]
    grouped = defaultdict(list)
    for row in results:
        if row["sha256"]:
            grouped[row["sha256"]].append(row)
    for copies in grouped.values():
        if len(copies) > 1:
            for duplicate in copies[1:]:
                duplicate["duplicate_of"] = copies[0]["path"]
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(results)
    return {
        "pdfs": len(results),
        "exact_duplicates": sum(bool(x["duplicate_of"]) for x in results),
        "need_review": sum(x["metadata_review_required"] == "yes" for x in results),
        "errors": sum(bool(x["error"]) for x in results),
    }
