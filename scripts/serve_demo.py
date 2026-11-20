"""Run the isolated synthetic UI test server at localhost:8001."""

import os
import runpy
from pathlib import Path
import uvicorn

if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    runpy.run_module("scripts.demo_fixture", run_name="__main__")
    os.environ["LAB_DATABASE"] = str(root / "data/demo/demo.sqlite3")
    os.environ["LAB_PDF_FOLDER"] = str(root / "data/demo/papers")
    os.environ["LAB_METADATA_OFFLINE"] = "1"
    os.environ["LAB_DEMO_OFFLINE"] = "1"
    uvicorn.run("backend.main:app", host="127.0.0.1", port=8001)
