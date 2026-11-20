import tempfile
import unittest
from pathlib import Path
import numpy as np
import pymupdf
from backend.library import Library
from backend.smart_library import SmartLibrary

class Model:
    def passage_embed(self,texts,batch_size=8):
        for text in texts: yield np.ones(384,dtype=np.float32)
    def query_embed(self,text): yield np.ones(384,dtype=np.float32)

class SmartTests(unittest.TestCase):
    def test_lifecycle(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); papers=root/'papers'; papers.mkdir()
            def pdf(path,text):
                with pymupdf.open() as doc:
                    doc.new_page().insert_text((72,72),text);doc.save(path)
            first=papers/'new.pdf';pdf(first,'Annealing titanium oxide films with experimental provenance.')
            service=SmartLibrary(Library(root/'absent.db',papers),root/'smart.db',Model())
            service.discover();self.assertTrue(service.process_one())
            result=service.search('annealing');self.assertEqual(len(result),1)
            identity=result[0]['document_id']
            self.assertEqual(result[0]['page'],1)
            (papers/'copy.pdf').write_bytes(first.read_bytes())
            service.discover();self.assertEqual(service.status()['duplicate_copies'],1)
            first.rename(papers/'renamed.pdf');service.discover()
            self.assertEqual(service.search('annealing')[0]['document_id'],identity)
            with service.write() as db:
                db.execute("UPDATE jobs SET state='running'")
            recovered=SmartLibrary(Library(root/'absent.db',papers),root/'smart.db',Model())
            self.assertEqual(recovered.status()['states']['pending'],1)
            recovered.process_one()
            (papers/'bad.pdf').write_bytes(b'not a PDF')
            recovered.discover();recovered.process_one()
            self.assertTrue(recovered.status()['failures'])
            # Replacement creates a new identity; old chunks cannot link to new bytes.
            (papers/'copy.pdf').unlink();(papers/'renamed.pdf').unlink()
            pdf(papers/'renamed.pdf','Optical absorption from a different paper.')
            recovered.discover();recovered.process_one()
            self.assertNotIn(identity,[r['document_id'] for r in recovered.search('annealing')])
            self.assertNotEqual(recovered.search('optical')[0]['document_id'],identity)
            self.assertFalse((root/'absent.db').exists())

    def test_legacy_preservation_and_restart(self):
        import hashlib
        from contextlib import closing
        from core import connect
        from retrieval import index_semantic
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); papers=root/'papers';papers.mkdir()
            with pymupdf.open() as pdf:
                pdf.new_page().insert_text((72,72),'Annealing experimental conditions with page provenance.')
                pdf.save(papers/'paper.pdf')
            legacy=root/'legacy.sqlite3'
            with closing(connect(legacy)) as db:
                index_semantic(str(papers),db,with_embeddings=False)
            before=hashlib.sha256(legacy.read_bytes()).hexdigest()
            service=SmartLibrary(Library(legacy,papers),root/'state.sqlite3',Model())
            service.discover();service.process_one()
            self.assertEqual(service.search('annealing')[0]['document_id'],1)
            self.assertEqual(before,hashlib.sha256(legacy.read_bytes()).hexdigest())
            with service.write() as db:
                vector=db.execute('SELECT embedding FROM chunks').fetchone()[0]
            restored=SmartLibrary(Library(legacy,papers),root/'state.sqlite3',Model())
            restored.discover()
            with restored.write() as db:
                self.assertEqual(vector,db.execute('SELECT embedding FROM chunks').fetchone()[0])
    def test_automatic_application_worker(self):
        import os,time
        from unittest.mock import patch
        from fastapi.testclient import TestClient
        from backend.main import create_app
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);papers=root/'papers';papers.mkdir()
            with pymupdf.open() as pdf:
                pdf.new_page().insert_text((72,72),'Annealing background processing evidence.')
                pdf.save(papers/'background.pdf')
            with patch.dict(os.environ,{'LAB_SMART_DATABASE':str(root/'sidecar.db'),'LAB_METADATA_OFFLINE':'1'}),patch('fastembed.TextEmbedding',return_value=Model()):
                with TestClient(create_app(Library(root/'legacy.db',papers),automatic=True)) as client:
                    for _ in range(100):
                        status=client.get('/api/library/readiness').json()
                        if status['states'].get('ready'): break
                        time.sleep(.05)
                    self.assertEqual(status['states'].get('ready'),1)
                    result=client.get('/api/search?q=annealing').json()
                    self.assertEqual(result['mode'],'hybrid')
                    self.assertEqual(len(result['sources']),1)
            self.assertFalse((root/'legacy.db').exists())
