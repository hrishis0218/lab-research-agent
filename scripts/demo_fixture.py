"""Generate a clearly synthetic, isolated demo corpus; never opens the live index."""
from pathlib import Path
from contextlib import closing
import pymupdf
from core import connect
from retrieval import index_semantic

root = Path(__file__).resolve().parents[1] / 'data/demo'
folder = root / 'papers'
folder.mkdir(parents=True, exist_ok=True)
create_corpus=not any(folder.rglob('*.pdf'))
for name, text in [
    ('Synthetic annealing study', 'SYNTHETIC DEMO - NOT SCIENTIFIC EVIDENCE\nAnnealing titanium dioxide films: example passage for interface tests.\nThese invented observations must not be cited as real research.'),
    ('Synthetic oxygen vacancy study', 'SYNTHETIC DEMO - NOT SCIENTIFIC EVIDENCE\nOxygen vacancies in oxide films: example passage for interface tests.')
]:
    path = folder / f'{name}.pdf'
    if create_corpus and not path.exists():
        with pymupdf.open() as pdf:
            pdf.set_metadata({'title': name, 'author': 'Synthetic fixture'})
            pdf.new_page().insert_text((60, 80), text)
            pdf.new_page().insert_text((60, 80), 'SYNTHETIC DEMO\nSecond page for PDF navigation tests.')
            pdf.save(path)
with closing(connect(root / 'demo.sqlite3')) as con:
    index_semantic(str(folder), con, with_embeddings=False)
print('Synthetic demo ready under data/demo. No real papers or index changed.')
