"""No original PDFs are renamed or edited during metadata audit."""
import csv
import tempfile
import unittest
from pathlib import Path

import pymupdf

from backend.documents.audit import audit_folder, safe_filename, inspect_pdf


class PdfAuditTests(unittest.TestCase):
    def test_filename_sanitisation(self):
        self.assertEqual(safe_filename("TiO2: Field / Response?", "2024", "fallback"), "2024_TiO2_Field_Response.pdf")

    def test_read_only_audit_and_exact_duplicate(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            papers = root / "papers"
            papers.mkdir()
            original = papers / "one.pdf"
            doc = pymupdf.open()
            try:
                page = doc.new_page()
                page.insert_text((72, 72), "Electric field effects on titanium dioxide films")
                page.insert_text((72, 100), "doi: 10.1234/field.2024")
                doc.set_metadata({"title": "Electric field effects on titanium dioxide films"})
                doc.save(original)
            finally:
                doc.close()
            duplicate = papers / "copy.pdf"
            duplicate.write_bytes(original.read_bytes())
            before = original.read_bytes()
            report = root / "report.csv"
            result = audit_folder(papers, report)
            self.assertEqual(result["pdfs"], 2)
            self.assertEqual(result["exact_duplicates"], 1)
            self.assertEqual(original.read_bytes(), before)
            self.assertTrue(duplicate.exists())
            with report.open("r", encoding="utf-8-sig", newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["doi"], "10.1234/field.2024")
            self.assertEqual(sum(bool(row["duplicate_of"]) for row in rows), 1)

    def test_bad_pdf_is_reported_not_deleted(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "broken.pdf"
            path.write_text("not a PDF", encoding="utf-8")
            result = inspect_pdf(path)
            self.assertTrue(result["error"])
            self.assertTrue(path.exists())


if __name__ == "__main__":
    unittest.main()
