import tempfile, unittest, json
from pathlib import Path
from unittest.mock import patch
import pymupdf
from backend.library import Library
from backend.smart_library import SmartLibrary
from backend.cloud import CloudAI


class AutonomousTests(unittest.TestCase):
    def fixture(self, root, name="source.pdf"):
        papers = root / "papers"
        papers.mkdir(exist_ok=True)
        with pymupdf.open() as pdf:
            pdf.new_page().insert_text(
                (72, 72),
                "Exact scientific passage for checking quote provenance and page citations.",
            )
            pdf.save(papers / name)
        lib = SmartLibrary(Library(root / "legacy.db", papers), root / "state.db")
        lib.discover()
        with lib.write() as db:
            digest = db.execute("SELECT hash FROM files").fetchone()[0]
        return lib, papers / name, digest

    def test_collision_undo_and_crash(self):
        with tempfile.TemporaryDirectory() as temp:
            lib, source, digest = self.fixture(Path(temp))
            metadata = {
                "verified": True,
                "year": "2024",
                "authors": "Jane Smith",
                "title": "A verified scientific article title for testing",
            }
            target = lib.organiser.move(source, digest, metadata)
            self.assertTrue(target.exists())
            self.assertFalse(source.exists())
            self.assertEqual(lib.path(1), target)
            with lib.write() as db:
                operation = db.execute(
                    "SELECT id FROM moves WHERE state='done'"
                ).fetchone()[0]
            # Never replace an existing restore target.
            source.write_bytes(b"collision")
            with self.assertRaises(ValueError):
                lib.organiser.undo(operation)
            source.unlink()
            lib.organiser.undo(operation)
            self.assertEqual(lib.path(1), source)
            self.assertEqual(
                lib.organiser.move(source, digest, metadata), source
            )  # undo holds
            with lib.write() as db:
                db.execute("DELETE FROM organisation_hold")
                target2 = source.parent / "crash.pdf"
                db.execute(
                    "INSERT INTO moves(old,new,hash,state) VALUES (?,?,?,'planned')",
                    (str(source), str(target2), digest),
                )
            source.rename(target2)
            lib.organiser.recover()
            self.assertEqual(lib.path(1), target2)

    def test_same_title_collision(self):
        with tempfile.TemporaryDirectory() as temp:
            lib, source, digest = self.fixture(Path(temp))
            metadata = {
                "verified": True,
                "year": "2024",
                "authors": "Jane Smith",
                "title": "A verified scientific article title for testing",
            }
            first = lib.organiser.move(source, digest, metadata)
            duplicate = lib.folder / "copy.pdf"
            duplicate.write_bytes(first.read_bytes())
            lib.discover()
            second = lib.organiser.move(duplicate, digest, metadata)
            self.assertNotEqual(first, second)
            self.assertEqual(first.read_bytes(), second.read_bytes())

    def test_cloud_citations_and_vault_persistence(self):
        vault = {}
        with (
            tempfile.TemporaryDirectory() as temp,
            patch(
                "backend.credentials.get_key", side_effect=lambda p: vault.get(p, "")
            ),
            patch(
                "backend.credentials.save_key",
                side_effect=lambda p, k: vault.update({p: k}),
            ),
        ):
            from backend import credentials

            credentials.save_key("Gemini", "dummy-key")
            path = Path(temp) / "workspace.db"
            service = CloudAI(path)
            service.configure(
                {
                    "provider": "Gemini",
                    "model": "test-model",
                    "consent": True,
                    "enabled": True,
                }
            )
            restored = CloudAI(path)
            self.assertTrue(restored.settings()["credentials"]["Gemini"])
            sources = [
                {
                    "citation": "S1",
                    "excerpt": "Exact scientific passage for checking quote provenance and page citations.",
                }
            ]
            response = {
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "text": json.dumps(
                                        {
                                            "answer": "Supported by this passage [S1].",
                                            "quotations": [
                                                {
                                                    "source_id": "S1",
                                                    "quote": sources[0]["excerpt"],
                                                }
                                            ],
                                        }
                                    )
                                }
                            ]
                        }
                    }
                ]
            }
            with patch("httpx.Client") as client:
                client.return_value.__enter__.return_value.post.return_value.json.return_value = response
                self.assertIn("[S1]", restored.answer("Question", sources))
                response["candidates"][0]["content"]["parts"][0]["text"] = json.dumps(
                    {"answer": "Fabricated [S99]", "quotations": []}
                )
                with self.assertRaises(ValueError):
                    restored.answer("Question", sources)
            service.configure(
                {
                    "provider": "Gemini",
                    "model": "test-model",
                    "consent": False,
                    "enabled": False,
                }
            )
            with patch("httpx.Client") as client:
                self.assertIsNone(service.answer("Offline question", sources))
                client.assert_not_called()

    def test_metadata_ignores_reference_doi_and_preserves_provenance(self):
        with tempfile.TemporaryDirectory() as temp:
            lib, source, digest = self.fixture(Path(temp))
            title = (
                "A careful experimental investigation of thin film optical properties"
            )
            with pymupdf.open(source) as pdf:
                pdf.set_metadata({"title": title})
                pdf.saveIncr()
            with patch.object(
                lib.identifier,
                "request",
                return_value={
                    "message": {
                        "items": [
                            {
                                "title": [title],
                                "DOI": "10.1234/valid",
                                "type": "journal-article",
                                "author": [{"given": "Jane", "family": "Smith"}],
                                "container-title": ["Fixture journal"],
                                "issued": {"date-parts": [[2024]]},
                            }
                        ]
                    }
                },
            ):
                record = lib.identifier.identify(source)
            self.assertTrue(record["verified"])
            self.assertEqual(record["doi"], "10.1234/valid")
            self.assertEqual(record["authors"], "Jane Smith")
            self.assertIn("title", record["fields"])

    def test_reference_doi_and_multiline_pii_title(self):
        with tempfile.TemporaryDirectory() as temp:
            lib, source, digest = self.fixture(Path(temp))
            source.unlink()
            title = (
                "A careful experimental investigation of thin film optical properties"
            )
            with pymupdf.open() as pdf:
                page = pdf.new_page()
                page.insert_textbox((72, 72, 520, 170), title, fontsize=18)
                page.insert_text(
                    (72, 220),
                    "Abstract\n"
                    + (
                        "This is a controlled synthetic abstract for metadata testing. "
                        * 4
                    )
                    + "\nIntroduction\nReferences\n10.9999/unrelated",
                    fontsize=10,
                )
                pdf.set_metadata({"title": "PII: S0000-000X(24)12345-6"})
                pdf.save(source)
            requested = []

            def metadata(key, url):
                requested.append(key)
                return {
                    "message": {
                        "items": [
                            {
                                "title": [title],
                                "DOI": "10.1234/right",
                                "type": "journal-article",
                                "author": [{"family": "Smith"}],
                            }
                        ]
                    }
                }

            with patch.object(lib.identifier, "request", side_effect=metadata):
                record = lib.identifier.identify(source)
            self.assertEqual(record["title"], title)
            self.assertEqual(record["doi"], "10.1234/right")
            self.assertFalse(any(key.startswith("doi:10.9999") for key in requested))

    def test_locked_file_never_moves_or_overwrites(self):
        import ctypes

        with tempfile.TemporaryDirectory() as temp:
            lib, source, digest = self.fixture(Path(temp))
            kernel = ctypes.windll.kernel32
            kernel.CreateFileW.restype = ctypes.c_void_p
            handle = kernel.CreateFileW(str(source), 0x80000000, 0, None, 3, 0, None)
            self.assertNotEqual(handle, ctypes.c_void_p(-1).value)
            try:
                with self.assertRaises(Exception):
                    lib.organiser.move(
                        source, digest, {"title": "Locked fixture", "verified": False}
                    )
                self.assertTrue(source.exists())
            finally:
                kernel.CloseHandle.argtypes = [ctypes.c_void_p]
                kernel.CloseHandle(handle)
            self.assertEqual(source.read_bytes()[:5], b"%PDF-")

    def test_openai_adapter_and_quote_rejection(self):
        with (
            tempfile.TemporaryDirectory() as temp,
            patch("backend.credentials.get_key", return_value="dummy-key"),
        ):
            service = CloudAI(Path(temp) / "workspace.db")
            service.configure(
                {
                    "provider": "OpenAI",
                    "model": "fixture-model",
                    "enabled": True,
                    "consent": True,
                }
            )
            source = {
                "citation": "S1",
                "excerpt": "Exact experimental quotation with page-level provenance.",
            }
            with patch("httpx.Client") as client:
                post = client.return_value.__enter__.return_value.post
                post.return_value.json.return_value = {
                    "output": [
                        {
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": json.dumps(
                                        {
                                            "answer": "A statement [S1]",
                                            "quotations": [
                                                {
                                                    "source_id": "S1",
                                                    "quote": source["excerpt"],
                                                }
                                            ],
                                        }
                                    ),
                                }
                            ]
                        }
                    ]
                }
                self.assertIn("[S1]", service.answer("Question", [source]))
                self.assertFalse(post.call_args.kwargs["json"]["store"])
                post.return_value.json.return_value = {
                    "output": [
                        {
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": json.dumps(
                                        {
                                            "answer": "A statement [S1]",
                                            "quotations": [
                                                {
                                                    "source_id": "S1",
                                                    "quote": "A quotation never present in the source.",
                                                }
                                            ],
                                        }
                                    ),
                                }
                            ]
                        }
                    ]
                }
                with self.assertRaises(ValueError):
                    service.answer("Question", [source])

    def test_local_ocr_is_indexed_and_flagged_without_pdf_edits(self):
        import hashlib

        with tempfile.TemporaryDirectory() as temp:
            lib, source, digest = self.fixture(Path(temp))
            before = hashlib.sha256(source.read_bytes()).hexdigest()
            with patch(
                "backend.smart_library.readable_page",
                return_value=(
                    "Synthetic OCR annealing passage with provenance that must be checked.",
                    True,
                    None,
                ),
            ):
                self.assertTrue(lib.process_one())
            self.assertEqual(before, hashlib.sha256(source.read_bytes()).hexdigest())
            with lib.write() as db:
                metadata = json.loads(
                    db.execute("SELECT metadata FROM identities").fetchone()[0]
                )
            self.assertEqual(metadata["text_origin"], "ocr")
            self.assertIn("verify", metadata["extraction_warning"])
            self.assertEqual(lib.search("annealing")[0]["page"], 1)

    def test_inventory_416_262_reconciles_without_legacy_writes(self):
        import hashlib
        from contextlib import closing
        from core import connect
        from retrieval import ensure_schema

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            papers = root / "papers"
            papers.mkdir()
            for i in range(405):
                (papers / f"{i}.pdf").write_bytes(b"%PDF-fixture-" + str(i).encode())
            for i in range(11):
                (papers / f"copy-{i}.pdf").write_bytes(
                    (papers / f"{i}.pdf").read_bytes()
                )
            legacy = root / "legacy.db"
            with closing(connect(legacy)) as db:
                ensure_schema(db)
                for i in range(262):
                    path = (
                        papers / f"{i}.pdf"
                        if i < 177
                        else root / "old-location" / f"{i}.pdf"
                    )
                    st = path.stat() if path.exists() else None
                    db.execute(
                        "INSERT INTO chunk_documents(id,path,title,size,mtime_ns) VALUES (?,?,?,?,?)",
                        (
                            i + 1,
                            str(path),
                            f"Fixture {i}",
                            st.st_size if st else 1,
                            st.st_mtime_ns if st else 1,
                        ),
                    )
                    db.execute(
                        "INSERT INTO chunks(document_id,page,position,content,embedding,model) VALUES (?,1,0,?,?,?)",
                        (
                            i + 1,
                            "Fixture scientific excerpt " + str(i),
                            b"preserved-vector",
                            "fixture-model",
                        ),
                    )
                db.commit()
            before = hashlib.sha256(legacy.read_bytes()).hexdigest()
            lib = SmartLibrary(Library(legacy, papers), root / "state.db")
            lib.discover()
            stats = lib.stats()
            self.assertEqual(
                (
                    stats["on_disk"],
                    stats["indexed"],
                    stats["unindexed"],
                    stats["duplicate_copies"],
                    stats["missing"],
                ),
                (416, 177, 228, 11, 85),
            )
            self.assertEqual(len(lib.documents()), 405)
            self.assertEqual(
                sum(
                    len([a for a in d["attachments"] if a["available"]])
                    for d in lib.documents()
                ),
                416,
            )
            self.assertEqual(before, hashlib.sha256(legacy.read_bytes()).hexdigest())
            with lib.write() as db:
                self.assertEqual(
                    db.execute(
                        "SELECT count(*) FROM chunks WHERE embedding=?",
                        (b"preserved-vector",),
                    ).fetchone()[0],
                    262,
                )

    def test_unproven_legacy_alias_cannot_serve_wrong_pdf(self):
        with tempfile.TemporaryDirectory() as temp:
            lib,source,digest=self.fixture(Path(temp))
            with lib.write() as db:
                db.execute('INSERT INTO chunk_documents(id,path,title,size,mtime_ns) VALUES (999,?,?,1,1)',(str(Path(temp)/'missing.pdf'),'Historical source'))
                db.execute('INSERT INTO chunks(document_id,page,position,content) VALUES (999,1,0,?)',('A different historical experiment never present on the target page.',))
                db.execute('INSERT INTO aliases VALUES (999,1,?)',('Multiple exact page-level passage matches',))
            with self.assertRaises(FileNotFoundError):lib.path(999)
            lib.audit_aliases()
            with self.assertRaises(FileNotFoundError):lib.path(999)
            with lib.write() as db:
                self.assertTrue(db.execute('SELECT evidence FROM aliases WHERE old_id=999').fetchone()[0].startswith('Rejected:'))
                self.assertEqual(db.execute('SELECT count(*) FROM chunks WHERE document_id=999').fetchone()[0],1)
