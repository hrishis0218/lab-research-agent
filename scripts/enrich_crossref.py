"""Enrich an existing PDF audit with bibliographic candidates from Crossref.

Example (first 25 uncached DOIs):
python -m scripts.enrich_crossref --input data/pdf_audit.csv --output data/pdf_enriched.csv
Run again with --limit 100 to extend the cached coverage.
"""
from __future__ import annotations

import argparse

from backend.documents.crossref import enrich_csv


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Read-only DOI metadata enrichment (does not rename or alter PDFs)"
    )
    parser.add_argument("--input", default="data/pdf_audit.csv")
    parser.add_argument("--output", default="data/pdf_enriched.csv")
    parser.add_argument("--cache", default="data/crossref_cache.json")
    parser.add_argument("--limit", type=int, default=25,
                        help="Maximum number of new network queries (default: 25)")
    parser.add_argument("--email", default="",
                        help="Optional contact email for Crossref polite API pool")
    args = parser.parse_args()
    stats = enrich_csv(args.input, args.output, args.cache,
                       limit=args.limit, email=args.email)
    print("Crossref enrichment completed:", stats)
    print("Review CSV:", args.output)
    print("No PDF files, filenames, or SQLite databases were modified.")


if __name__ == "__main__":
    main()
