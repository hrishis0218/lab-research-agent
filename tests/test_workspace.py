"""Synthetic integration coverage: never touches the real research collection."""
import hashlib
import tempfile
import unittest
from pathlib import Path
from contextlib import closing
import pymupdf
from fastapi.testclient import TestClient
from core import connect
from retrieval import index_semantic
from backend.library import Library
from backend.main import create_app


class WorkspaceTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.folder = self.root / 'papers'
        self.folder.mkdir()
        with pymupdf.open() as pdf:
            pdf.new_page().insert_text((72, 72), 'Synthetic fixture: annealing changes titanium dioxide films.')
            pdf.save(self.folder / 'fixture.pdf')
        self.database = self.root / 'index.sqlite3'
        with closing(connect(self.database)) as db:
            index_semantic(str(self.folder), db, with_embeddings=False)
        (self.folder / 'unindexed.pdf').write_bytes((self.folder / 'fixture.pdf').read_bytes())
        self.before = hashlib.sha256(self.database.read_bytes()).hexdigest()
        self.client = TestClient(create_app(Library(self.database, self.folder)))

    def tearDown(self):
        self.client.close()
        self.assertEqual(self.before, hashlib.sha256(self.database.read_bytes()).hexdigest())
        self.temp.cleanup()

    def test_stats_distinguish_populations(self):
        stats = self.client.get('/api/library/stats').json()
        self.assertEqual((stats['on_disk'], stats['indexed'], stats['unindexed']), (2, 1, 1))
        self.assertIsNone(stats['duplicate_copies'])

    def test_source_pdf_and_search(self):
        found = self.client.get('/api/search', params={'q': 'annealing', 'limit': 3}).json()['sources']
        self.assertEqual(len(found), 1)
        source = found[0]
        self.assertEqual(source['page'], 1)
        self.assertIn('annealing', source['excerpt'])
        detail = self.client.get(f"/api/documents/{source['document_id']}").json()
        self.assertIsNone(detail['abstract'])
        self.assertTrue(self.client.get(f"/api/documents/{source['document_id']}/pdf").content.startswith(b'%PDF'))
        self.assertEqual(self.client.get('/api/documents/999/pdf').status_code, 404)
        self.assertEqual(self.client.get('/api/search?q=x&limit=31').status_code, 422)

    def test_pdf_outside_root_rejected(self):
        restricted = TestClient(create_app(Library(self.database, self.root / 'other')))
        with restricted:
            self.assertEqual(restricted.get('/api/documents/1/pdf').status_code, 404)

    def test_missing_database_and_host_rejected(self):
        with TestClient(create_app(Library(self.root / 'missing.sqlite', self.folder))) as client:
            self.assertEqual(client.get('/api/documents').json(), [])
            self.assertEqual(client.get('/api/library/stats').json()['indexed'], 0)
            self.assertEqual(client.get('/api/health', headers={'host': 'malicious.example'}).status_code, 400)
        self.assertFalse((self.root / 'missing.sqlite').exists())

    def test_416_vs_262(self):
        from unittest.mock import patch
        service = Library(self.database, self.folder)
        with closing(connect(self.database)) as db:
            db.executemany('INSERT INTO chunk_documents(path,title,size,mtime_ns) VALUES (?,?,0,0)',
                [(str(self.folder / f'{i}.pdf'), f'fixture {i}') for i in range(261)])
            db.commit()
        self.before = hashlib.sha256(self.database.read_bytes()).hexdigest()
        paths = [self.folder / 'fixture.pdf', self.folder / 'unindexed.pdf'] + [self.folder / f'{i}.pdf' for i in range(414)]
        with patch.object(Path, 'rglob', return_value=iter(paths)), patch.object(Path, 'is_file', return_value=True):
            stats = service.stats()
        self.assertEqual(stats['on_disk'], 416)
        self.assertEqual(stats['indexed'], 262)
        self.assertEqual(stats['unindexed'], 154)


    def test_pdf_worker_mime_type(self):
        import mimetypes
        self.assertEqual(mimetypes.guess_type('pdf.worker.mjs')[0], 'application/javascript')
