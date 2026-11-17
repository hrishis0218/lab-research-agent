"""Offline tests: no Crossref network access or changes to real PDFs."""
import csv
import tempfile
import unittest
from pathlib import Path

from backend.documents.crossref import enrich_csv, normalise_doi, title_score, possible_truncated_title


def fake_lookup(doi: str, email: str = "") -> dict:
    return {
        "DOI": doi,
        "title": ["Electric field induced changes in titanium dioxide films"],
        "author": [{"given": "Ada", "family": "Example"}],
        "container-title": ["Journal of Test Materials"],
        "published": {"date-parts": [[2024, 6]]},
        "type": "journal-article",
    }


class CrossrefEnrichmentTests(unittest.TestCase):
    def test_doi_normalisation(self):
        self.assertEqual(normalise_doi("https://doi.org/10.1234/FIELD.2024."),
                         "10.1234/field.2024")
        self.assertEqual(normalise_doi("not a doi"), "")

    def test_similarity(self):
        title = "Electric field induced changes in titanium dioxide films"
        self.assertGreaterEqual(title_score(title, title), 0.99)
        self.assertLess(title_score("Unrelated glass properties", title), 0.75)

    def test_truncated_title_detection(self):
        self.assertTrue(possible_truncated_title(
            "Bleaching versus poling: Comparison of electric field",
            "Bleaching versus poling: Comparison of electric field induced phenomena in glasses"
        ))
        self.assertFalse(possible_truncated_title(
            "APPLIED PHYSICS REVIEWS—FOCUSED REVIEWS",
            "Bleaching versus poling: Comparison of electric field induced phenomena"
        ))

    def test_enrichment_cache_and_read_only_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, target, cache = (root / p for p in
                                     ("audit.csv", "enriched.csv", "cache.json"))
            fields = ["path", "doi", "title", "year"]
            with source.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                writer.writerow({"path": "paper-a.pdf", "doi": "10.1234/field.2024",
                                 "title": "Electric field induced changes in titanium dioxide films",
                                 "year": "2092"})
                writer.writerow({"path": "paper-b.pdf", "doi": "10.1234/field.2024",
                                 "title": "Unrelated glass properties", "year": "2085"})
                writer.writerow({"path": "unknown.pdf", "doi": "", "title": "", "year": ""})
            original_bytes = source.read_bytes()
            calls = []
            def lookup(doi, email=""):
                calls.append(doi)
                return fake_lookup(doi, email)
            stats = enrich_csv(source, target, cache, limit=1, delay=0, fetcher=lookup)
            self.assertEqual(stats["new_lookups"], 1)
            self.assertEqual(len(calls), 1)
            self.assertEqual(stats["matched"], 1)
            self.assertEqual(stats["review"], 1)
            self.assertEqual(source.read_bytes(), original_bytes)
            with target.open("r", encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(rows[0]["crossref_year"], "2024")
            self.assertEqual(rows[0]["crossref_status"], "title_match_review")
            self.assertTrue(rows[0]["proposed_verified_filename"].startswith("2024_"))
            self.assertEqual(rows[1]["crossref_status"], "title_mismatch_review")
            self.assertEqual(rows[1]["proposed_verified_filename"], "")
            self.assertEqual(rows[2]["crossref_status"], "missing_or_invalid_doi")

            def fail_if_network(*args, **kwargs):
                raise AssertionError("Cache should prevent network lookup")
            again = enrich_csv(source, target, cache, limit=0, delay=0,
                               fetcher=fail_if_network)
            self.assertEqual(again["new_lookups"], 0)
            self.assertEqual(again["matched"], 1)

    def test_no_overwrite_of_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "audit.csv"
            path.write_text("path,doi\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                enrich_csv(path, path, Path(tmp) / "cache.json")


if __name__ == "__main__":
    unittest.main()
