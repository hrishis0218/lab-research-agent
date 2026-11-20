"""Local, read-only OCR fallback for image-only pages. Never alters PDFs."""

from pathlib import Path
from urllib.request import urlopen
from threading import Lock
import os

_DOWNLOAD = Lock()
TESSDATA = Path(__file__).resolve().parents[1] / "models/tessdata"


def language_data():
    folder = Path(os.environ.get("LAB_TESSDATA", TESSDATA))
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / "eng.traineddata"
    with _DOWNLOAD:
        if not target.exists():
            temporary = folder / "eng.traineddata.download"
            with (
                urlopen(
                    "https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/main/eng.traineddata",
                    timeout=30,
                ) as response,
                temporary.open("wb") as stream,
            ):
                while block := response.read(1024 * 1024):
                    stream.write(block)
            if temporary.stat().st_size < 1000000:
                raise ValueError("OCR language data download incomplete")
            temporary.replace(target)
    return str(folder.resolve())


class OCRPage:
    def __init__(self, page):
        self.page = page
        self.rect = page.rect
        self.textpage = page.get_textpage_ocr(
            language="eng", dpi=180, full=True, tessdata=language_data()
        )

    def get_text(self, *args, **kwargs):
        return self.page.get_text(*args, textpage=self.textpage, **kwargs)


def readable_page(page):
    native = page.get_text("text", sort=True)
    if not native.strip() and page.get_images():
        adapted = OCRPage(page)
        return adapted.get_text("text", sort=True), True, adapted
    return native, False, page
