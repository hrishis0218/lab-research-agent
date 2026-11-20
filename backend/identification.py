"""Conservative automatic bibliographic identification; sends metadata only."""

import json, re, os, unicodedata, time
from urllib.parse import urlencode, quote, urlsplit
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from backend.ocr import readable_page
from threading import RLock

PDF_LOCK = RLock()
import pymupdf
from backend.documents.audit import (
    plausible_title,
    title_from_page,
    extract_abstract,
    DOI_PATTERN,
)
from backend.documents.crossref import title_score, flatten_record, plain_text


class Identifier:
    def __init__(self, library):
        self.library = library
        self.legacy_cache = {}
        self.circuits = {}
        cache = library.database.parent / "crossref_cache.json"
        if cache.exists():
            try:
                self.legacy_cache = json.loads(cache.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                pass

    def request(self, key, url):
        if os.environ.get("LAB_METADATA_OFFLINE") == "1":
            raise OSError("Metadata services disabled for isolated tests")
        with self.library.write() as db:
            row = db.execute(
                "SELECT record FROM doi_cache WHERE doi=?", (key,)
            ).fetchone()
        if row:
            return json.loads(row[0])
        host = urlsplit(url).hostname
        if self.circuits.get(host, 0) > time.time():
            raise OSError(
                "Bibliographic service temporarily unavailable; retry scheduled"
            )
        try:
            request = Request(
                url,
                headers={
                    "User-Agent": "LabResearchAgent/1.0 bibliographic-identification",
                    "Accept": "application/json",
                },
            )
            with urlopen(request, timeout=4) as response:
                data = json.load(response)
        except OSError as exc:
            if not isinstance(exc, HTTPError) or exc.code in (
                401,
                403,
                429,
                500,
                502,
                503,
                504,
            ):
                self.circuits[host] = time.time() + 120
            raise
        with self.library.write() as db:
            db.execute(
                "INSERT OR REPLACE INTO doi_cache VALUES (?,?)", (key, json.dumps(data))
            )
        return data

    def identify(self, path):
        with PDF_LOCK, pymupdf.open(path) as pdf:
            if pdf.needs_pass:
                raise ValueError("Password protected PDF")
            ocr = False
            first_page = pdf[0] if len(pdf) else None
            if first_page is not None:
                first, ocr, first_page = readable_page(first_page)
            else:
                first = ""
            meta = pdf.metadata or {}
            title = meta.get("title", "")
            if re.match(
                r"^(?:PII\s*:|arXiv\s*:|doi\s*:|Microsoft Word|untitled|doi.org|\d{4}\.)",
                title,
                re.I,
            ):
                title = ""
            if not plausible_title(title, ""):
                title = title_from_page(first_page) if len(pdf) else ""
            # Join adjacent title lines with the same prominent font size.
            if len(pdf) and title:
                lines = []
                for block in first_page.get_text("dict", sort=True).get("blocks", []):
                    for line in block.get("lines", []):
                        spans = line.get("spans", [])
                        if spans:
                            lines.append(
                                (
                                    " ".join(s.get("text", "") for s in spans),
                                    max(s.get("size", 0) for s in spans),
                                    line["bbox"],
                                )
                            )
                for i, (text, size, bbox) in enumerate(lines):
                    if (
                        unicodedata.normalize("NFKC", title).strip()
                        == unicodedata.normalize("NFKC", text).strip()
                    ):
                        parts = [text]
                        last = bbox
                        for nxt, nsize, nbbox in lines[i + 1 : i + 4]:
                            if (
                                abs(nsize - size) < 0.8
                                and nbbox[1] > last[1]
                                and -size * 0.8 <= nbbox[1] - last[3] < size * 1.5
                                and len(" ".join(parts + [nxt])) < 260
                            ):
                                parts.append(nxt)
                                last = nbbox
                            else:
                                break
                        title = " ".join(parts)
                        break
            record = {
                "title": title or path.stem,
                "authors": meta.get("author") or None,
                "abstract": extract_abstract(first) or None,
                "pages": len(pdf),
                "doi": None,
                "year": None,
                "journal": None,
                "verified": False,
                "provenance": "PDF extraction; bibliographic identity unverified",
                "version": 4,
                "text_origin": "ocr" if ocr else "pdf_text",
                "type": "article",
                "fields": {
                    "title": {
                        "source": "PDF metadata / first-page extraction"
                        if title
                        else "filename fallback",
                        "confidence": "unverified",
                    },
                    "authors": {"source": "PDF metadata", "confidence": "unverified"},
                    "abstract": {
                        "source": "first-page extraction",
                        "confidence": "unverified",
                    },
                },
            }
        if re.search(
            r"\b(?:doctoral thesis|master.?s thesis|dissertation|submitted.*degree)\b",
            first,
            re.I,
        ):
            record["type"] = "thesis"
        elif re.search(r"\barXiv:", first):
            record["type"] = "preprint"
        elif re.search(r"\btechnical report\b", first, re.I):
            record["type"] = "report"
        elif re.search(r"\breview\b", record["title"], re.I):
            record["type"] = "review"
        before_references = re.split(
            r"\n\s*(?:references|bibliography)\s*\n", first, flags=re.I
        )[0]
        candidates = list(
            dict.fromkeys(
                m.group().rstrip(".,;:)]}")
                for m in DOI_PATTERN.finditer(before_references[:10000])
            )
        )[:3]
        publications = []
        failures = []
        for doi in candidates:
            try:
                cached = self.legacy_cache.get(doi.lower())
                if isinstance(cached, dict) and "crossref_title" in cached:
                    item = {
                        "title": [cached["crossref_title"]],
                        "DOI": cached.get("crossref_doi", doi),
                        "container-title": [cached.get("crossref_journal", "")],
                        "author": [
                            {"family": a.strip()}
                            for a in cached.get("crossref_authors", "").split(";")
                            if a.strip()
                        ],
                        "type": cached.get("crossref_type", "journal-article"),
                        "issued": {"date-parts": [[int(cached["crossref_year"])]]}
                        if str(cached.get("crossref_year", "")).isdigit()
                        else {},
                    }
                elif isinstance(cached, dict) and "title" in cached:
                    item = cached
                else:
                    data = self.request(
                        "doi:" + doi,
                        "https://api.crossref.org/works/" + quote(doi, safe=""),
                    )
                    item = data.get("message", data)
                publications.append(item)
            except Exception:
                failures.append("DOI lookup unavailable")
        if (
            title
            and max(
                [title_score(title, (i.get("title") or [""])[0]) for i in publications]
                + [0]
            )
            < 0.85
        ):
            try:
                query = urlencode({"query.bibliographic": title, "rows": 3})
                publications.extend(
                    self.request(
                        "title:" + title, "https://api.crossref.org/works?" + query
                    )["message"]["items"]
                )
            except Exception:
                failures.append("Title lookup unavailable")
        best = max(
            publications,
            key=lambda i: title_score(title, (i.get("title") or [""])[0]),
            default=None,
        )
        score = title_score(title, (best.get("title") or [""])[0]) if best else 0
        matches = [
            i
            for i in publications
            if title_score(title, (i.get("title") or [""])[0]) >= 0.98
        ]
        ambiguous = len(
            {str(i.get("DOI", "")) for i in matches}
        ) > 1 and not record.get("authors")
        if ambiguous:
            score = 0
            record["identity_status"] = (
                "Multiple bibliographic matches; review required"
            )

        if (
            best
            and score >= 0.9
            and (
                len(title.split()) >= 5
                or ("book" in best.get("type", "") and len(title.split()) >= 3)
            )
        ):
            flat = flatten_record(best)
            record.update(
                title=flat["crossref_title"],
                authors=flat["crossref_authors"] or record["authors"],
                year=flat["crossref_year"] or None,
                journal=flat["crossref_journal"] or None,
                doi=flat["crossref_doi"] or None,
                verified=True,
                confidence=score,
                provenance="Crossref bibliographic title match",
            )
            record["abstract"] = (
                plain_text(best.get("abstract", "")) or record["abstract"]
            )
            record["type"] = (
                "book"
                if "book" in flat["crossref_type"]
                else "thesis"
                if "dissertation" in flat["crossref_type"]
                else "review"
                if re.search(r"\breview\b", record["title"], re.I)
                else "article"
            )
            for field in ("title", "authors", "year", "journal", "doi"):
                record["fields"][field] = {"source": "Crossref", "confidence": score}
        elif title and not ambiguous:
            try:
                data = self.request(
                    "openalex:" + title,
                    "https://api.openalex.org/works?"
                    + urlencode({"search": title, "per-page": 3}),
                )
                work = max(
                    data.get("results", []),
                    key=lambda w: title_score(title, w.get("display_name", "")),
                    default={},
                )
                score = title_score(title, work.get("display_name", ""))
                if score >= 0.94 and len(title.split()) >= 5:
                    record.update(
                        title=work["display_name"],
                        authors="; ".join(
                            a["author"]["display_name"]
                            for a in work.get("authorships", [])
                        )
                        or record["authors"],
                        year=work.get("publication_year"),
                        doi=(work.get("doi") or "").replace("https://doi.org/", "")
                        or None,
                        journal=(
                            (work.get("primary_location") or {}).get("source") or {}
                        ).get("display_name"),
                        verified=True,
                        confidence=score,
                        provenance="OpenAlex bibliographic title match",
                        type="book"
                        if work.get("type") == "book"
                        else "thesis"
                        if work.get("type") == "dissertation"
                        else record["type"],
                    )
                    record["fields"] = {
                        k: {"source": "OpenAlex", "confidence": score}
                        for k in ("title", "authors", "year", "journal", "doi")
                    }
            except Exception:
                failures.append("Additional metadata service unavailable")
        text = (record["title"] + " " + first).lower()
        record["categories"] = [
            tag
            for tag, pattern in {
                "Oxides": r"oxide|tio2|zno",
                "Thin films": r"thin.film|coating",
                "Annealing": r"anneal|thermal treatment",
                "Optical characterisation": r"ellipsometr|optical|spectroscop",
                "Electrical": r"electr|dielectric",
                "Simulation": r"simulation|density.functional",
                "Microscopy": r"microscop|sem\b|tem\b",
            }.items()
            if re.search(pattern, text)
        ]
        record["metadata_errors"] = failures
        record["metadata_retry_after"] = time.time() + 600 if failures else 0
        record["stage"] = "identified"
        return record
