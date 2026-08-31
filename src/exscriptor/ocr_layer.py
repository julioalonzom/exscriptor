"""OCR witness helpers: a second OCR pass as an independent witness.

Any second OCR source works as a witness — it knows no Latin, so it never
regularizes, and its disagreements with the transcription flag pages that
deserve a closer look at the image.

Two sources are supported:

1. The scan PDF's own embedded text layer (extracted with `pdftotext`,
   or a pre-extracted dump via OCR_DUMP / the `pdf` argument).
2. A fresh OCR run from any engine that produces a `{filename: text}`
   JSON map over the page images (e.g. macOS Vision via pyobjc; see
   `ocr_pages_json()`).

`ocr_words()` / `ocr_text()` read by page number from either source.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

# Cache of per-page text, loaded lazily.
_PAGES: list[str] | None = None
_PDF: str | None = None


def _load(pdf: str | None = None) -> list[str]:
    global _PAGES, _PDF
    pdf = pdf or os.environ.get("OCR_PDF")
    if pdf is None:
        raise SystemExit("ocr_layer: pass the pdf path or set OCR_PDF")
    if _PAGES is None or _PDF != pdf:
        dump_env = os.environ.get("OCR_DUMP")
        dump = Path(dump_env) if dump_env else None
        if dump and dump.is_file():
            _PAGES = dump.read_text(encoding="utf-8").split("\f")
        else:
            out = subprocess.run(["pdftotext", "-layout", pdf, "-"],
                                 capture_output=True, text=True)
            _PAGES = out.stdout.split("\f")
        _PDF = pdf
    return _PAGES


def ocr_pages_json(json_path: str | Path) -> list[str]:
    """Load a fresh OCR run's {filename: text} JSON map as page-ordered text.

    Filenames sort lexicographically (pg-001.jpg < pg-010.jpg), matching the
    pg-NNN image convention. Any engine works — the contract is just the
    JSON shape.
    """
    data = json.loads(Path(json_path).read_text(encoding="utf-8"))
    return [data[k] for k in sorted(data)]


def words(text: str) -> list[str]:
    return re.findall(r"[A-Za-zÆæ]+", text)


def ocr_words(pdf: str, num: int) -> list[str]:
    """Word list of page `num` from the OCR witness (1-based PDF page)."""
    pages = _load(pdf)
    if 1 <= num <= len(pages):
        return words(pages[num - 1])
    return []


def ocr_text(pdf: str, num: int) -> str:
    pages = _load(pdf)
    if 1 <= num <= len(pages):
        return pages[num - 1]
    return ""
