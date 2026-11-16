import argparse
from core import connect, index_folder

parser = argparse.ArgumentParser(description="Index local research PDFs")
parser.add_argument("folder", help="Folder to scan recursively")
args = parser.parse_args()
with connect() as db:
    result = index_folder(args.folder, db)
print(result)
