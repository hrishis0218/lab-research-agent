"""Read-only audit. Example:
python -m scripts.audit_pdfs "C:\\Research\\Papers" --output "data/pdf_audit.csv"
"""
from __future__ import annotations

import argparse
from backend.documents.audit import audit_folder


def main():
    parser = argparse.ArgumentParser(description="Audit PDF metadata and exact duplicates without modifying PDFs")
    parser.add_argument("folder", help="Existing folder of PDFs (searched recursively)")
    parser.add_argument("--output", default="data/pdf_audit.csv", help="CSV report path; defaults to ignored data folder")
    args = parser.parse_args()
    result = audit_folder(args.folder, args.output)
    print(f"Audit completed: {result}")
    print(f"Report: {args.output}")
    print("No PDFs or SQLite databases were modified.")


if __name__ == "__main__":
    main()
