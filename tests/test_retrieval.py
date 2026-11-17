import tempfile
from contextlib import closing
import unittest
from pathlib import Path
import sys
from unittest.mock import patch
import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import fitz
from core import connect
from retrieval import index_semantic, retrieve, chunks_from_text


class RetrievalTests(unittest.TestCase):
    def test_chunk_overlap(self):
        words = [f"word{i}" for i in range(400)]
        pieces = list(chunks_from_text(" ".join(words)))
        self.assertGreater(len(pieces), 2)
        self.assertEqual(pieces[0].split()[-35:],pieces[1].split()[:35])

    def test_index_and_citations_without_model(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            pdf_path = root / "paper.pdf"
            pdf = fitz.open()
            page = pdf.new_page()
            page.insert_text((72,72),"Electric field modifies anatase titanium dioxide thin films.")
            pdf.save(pdf_path)
            pdf.close()
            with closing(connect(root/"test.sqlite")) as con:
                first = index_semantic(str(root),con,with_embeddings=False)
                self.assertEqual(first["indexed"],1)
                self.assertEqual(index_semantic(str(root),con,False)["unchanged"],1)
                found = retrieve("anatase field",con,semantic=False)
                self.assertEqual(len(found),1)
                self.assertEqual(found[0]["citation"],"S1")
                self.assertEqual(found[0]["page"],1)
                self.assertEqual(found[0]["path"],str(pdf_path))
                self.assertIn("anatase",found[0]["content"])

    def test_semantic_retrieval_with_stub_embeddings(self):
        class Stub:
            def passage_embed(self, texts, batch_size=16):
                for text in texts:
                    yield np.array([1,0],dtype=np.float32) if "anatase" in text else np.array([0,1],dtype=np.float32)
            def query_embed(self, query):
                yield np.array([1,0],dtype=np.float32)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with fitz.open() as pdf:
                page = pdf.new_page()
                page.insert_text((72,72),"Anatase modification with electric fields.")
                pdf.save(root/"paper.pdf")
            with closing(connect(root/"test.sqlite")) as con, patch("retrieval.embedding_model",return_value=Stub()):
                self.assertEqual(index_semantic(str(root),con,True)["indexed"],1)
                found = retrieve("phase transition",con,semantic=True)
                self.assertEqual(found[0]["citation"],"S1")
                self.assertEqual(found[0]["page"],1)


if __name__ == "__main__":
    unittest.main()
