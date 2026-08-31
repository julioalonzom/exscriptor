"""OCR-layer helpers: the scan PDF's own text layer as second witness.

The archive.org PDFs carry a text layer (their own OCR). It is an
independent second witness: it knows no Latin, so it never regularizes.
`ocr_words()` reads the per-page text from a pre-extracted dump when one
exists (env OCR_DUMP or the pdf arg), falling back to running pdftotext.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

# Cache of the full pdftotext dump (page N -> text), loaded lazily.
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


def words(text: str) -> list[str]:
    return re.findall(r"[A-Za-zÆæ]+", text)


def ocr_words(pdf: str, num: int) -> list[str]:
    """Word list of page `num` from the OCR layer (1-based PDF page)."""
    pages = _load(pdf)
    if 1 <= num <= len(pages):
        return words(pages[num - 1])
    return []


def ocr_text(pdf: str, num: int) -> str:
    pages = _load(pdf)
    if 1 <= num <= len(pages):
        return pages[num - 1]
    return ""
