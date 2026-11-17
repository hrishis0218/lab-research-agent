"""Crossref DOI metadata enrichment for an existing PDF audit CSV.

Read-only relative to PDFs and SQLite. Crossref is queried by exact DOI, never
by title alone. All candidate matches remain proposals pending human review.
"""
from __future__ import annotations

import csv
import json
import re
import time
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from backend.documents.audit import safe_filename

CROSSREF_BASE = "https://api.crossref.org/works/"
DOI_PATTERN = re.compile(r"^10\.\d{4,9}/\S+$", re.I)
EXTRA_COLUMNS = [
    "crossref_status", "crossref_title", "crossref_authors",
    "crossref_year", "crossref_journal", "crossref_type",
    "crossref_doi", "title_similarity", "proposed_verified_filename",
    "crossref_error",
]


def normalise_doi(value: str) -> str:
    value = (value or "").strip()
    value = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi\s*:)", "", value, flags=re.I)
    value = value.rstrip(" \t\r\n.,;:)]}")
    return value.lower() if DOI_PATTERN.fullmatch(value) else ""


def plain_text(value: str) -> str:
    value = re.sub(r"<[^>]+>", " ", value or "")
    return " ".join(value.split())


def title_score(a: str, b: str) -> float:
    def words(value: str) -> list[str]:
        normal = unicodedata.normalize("NFKD", value or "")
        normal = "".join(ch for ch in normal if not unicodedata.combining(ch))
        return re.findall(r"[a-z0-9]+", normal.lower())
    left, right = words(a), words(b)
    if not left or not right:
        return 0.0
    joined = SequenceMatcher(None, " ".join(left), " ".join(right)).ratio()
    shared = len(set(left) & set(right)) / max(len(set(left)), len(set(right)))
    return round(max(joined, shared), 3)


def possible_truncated_title(extracted: str, authoritative: str) -> bool:
    """Flag likely single-line title extraction without treating it as verified.

    Require a substantial ordered prefix; generic headings and short matches
    must not be mistaken for a paper title.
    """
    def tokens(value: str) -> list[str]:
        normal = unicodedata.normalize("NFKD", value or "")
        normal = "".join(ch for ch in normal if not unicodedata.combining(ch))
        return re.findall(r"[a-z0-9]+", normal.lower())

    left, right = tokens(extracted), tokens(authoritative)
    return (
        len(extracted.strip()) >= 30
        and len(left) >= 6
        and len(right) >= len(left) + 2
        and left == right[:len(left)]
    )


def extract_year(item: dict) -> str:
    for field in ("published", "issued", "published-print", "published-online"):
        parts = (item.get(field) or {}).get("date-parts") or []
        if parts and parts[0]:
            year = str(parts[0][0])
            if year.isdigit() and 1800 <= int(year) <= 2100:
                return year
    return ""


def flatten_record(item: dict) -> dict[str, str]:
    authors = []
    for person in item.get("author") or []:
        name = " ".join(part for part in (person.get("given", ""), person.get("family", "")) if part)
        if name:
            authors.append(name)
    titles = item.get("title") or []
    containers = item.get("container-title") or []
    return {
        "crossref_title": plain_text(titles[0] if titles else ""),
        "crossref_authors": "; ".join(authors),
        "crossref_year": extract_year(item),
        "crossref_journal": plain_text(containers[0] if containers else ""),
        "crossref_type": str(item.get("type", "")),
        "crossref_doi": normalise_doi(str(item.get("DOI", ""))),
    }


def fetch_crossref(doi: str, email: str = "", timeout: float = 15) -> dict:
    query = "?" + urlencode({"mailto": email}) if email else ""
    url = CROSSREF_BASE + quote(doi, safe="") + query
    agent = "LabResearchAgent/1.0 (local scholarly metadata audit)"
    if email:
        agent += " (mailto:" + email + ")"
    request = Request(url, headers={"User-Agent": agent, "Accept": "application/json"})
    with urlopen(request, timeout=timeout) as response:
        payload = json.load(response)
    return payload["message"]


def load_cache(path: Path) -> dict:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("Crossref cache is not a JSON object")
    return data


def save_cache(path: Path, records: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8") as handle:
        json.dump(records, handle, ensure_ascii=False, indent=2)
    temp.replace(path)


def enrich_csv(
    input_csv: str | Path,
    output_csv: str | Path,
    cache_file: str | Path,
    *,
    limit: int = 25,
    email: str = "",
    delay: float = 0.25,
    fetcher=None,
) -> dict[str, int]:
    """Create a separate CSV. Never touch PDFs or the existing index.

    limit caps NEW network lookups, not total CSV rows. Cached DOI results are
    reused and source rows without DOIs are retained.
    """
    if limit < 0 or delay < 0:
        raise ValueError("limit and delay cannot be negative")
    source, target, cache_path = map(lambda p: Path(p).expanduser().resolve(),
                                     (input_csv, output_csv, cache_file))
    if source == target:
        raise ValueError("Output must differ from the original audit CSV")
    if source == cache_path or target == cache_path:
        raise ValueError("Cache must have a separate path")
    with source.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        original_fields = reader.fieldnames or []
        if "doi" not in original_fields or "path" not in original_fields:
            raise ValueError("Input is not a PDF audit CSV: required columns missing")
        rows = list(reader)
    cache = load_cache(cache_path)
    fetcher = fetcher or fetch_crossref
    looked_up = 0
    summary = {"rows": len(rows), "new_lookups": 0, "matched": 0,
               "review": 0, "missing_doi": 0, "lookup_errors": 0, "deferred": 0}
    for row in rows:
        row.update({field: "" for field in EXTRA_COLUMNS})
        doi = normalise_doi(row.get("doi", ""))
        if not doi:
            row["crossref_status"] = "missing_or_invalid_doi"
            summary["missing_doi"] += 1
            continue
        if doi in cache:
            record = cache[doi]
        elif looked_up >= limit:
            row["crossref_status"] = "deferred"
            summary["deferred"] += 1
            continue
        else:
            looked_up += 1
            try:
                record = flatten_record(fetcher(doi, email=email))
                if not record["crossref_doi"] or record["crossref_doi"] != doi:
                    raise ValueError("Crossref returned a different DOI")
                cache[doi] = record
                save_cache(cache_path, cache)
            except (HTTPError, URLError, TimeoutError, KeyError, TypeError,
                    ValueError, OSError) as exc:
                row["crossref_status"] = "lookup_error"
                row["crossref_error"] = f"{type(exc).__name__}: {exc}"
                summary["lookup_errors"] += 1
                continue
            finally:
                if delay:
                    time.sleep(delay)
        row.update(record)
        old_title = row.get("title", "")
        similarity = title_score(old_title, record["crossref_title"])
        row["title_similarity"] = f"{similarity:.3f}"
        # A DOI alone does not establish that this is the paper's own DOI:
        # it might be a reference listed on the first page.
        if not record["crossref_title"]:
            status = "review_no_crossref_title"
        elif similarity >= 0.75:
            status = "title_match_review"
        elif possible_truncated_title(old_title, record["crossref_title"]):
            status = "possible_truncated_title_review"
        else:
            status = "title_mismatch_review"
        row["crossref_status"] = status
        if status == "title_match_review":
            row["proposed_verified_filename"] = safe_filename(
                record["crossref_title"], record["crossref_year"], "paper")
            summary["matched"] += 1
        else:
            summary["review"] += 1
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8-sig", newline="") as handle:
        fields = original_fields + [field for field in EXTRA_COLUMNS if field not in original_fields]
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    summary["new_lookups"] = looked_up
    return summary
