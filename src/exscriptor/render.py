#!/usr/bin/env python3
"""The page image for a page number: the one thing every reader, adjudicator,
replay and human check needs, found or rendered the same way.

Lookup order, for page ``n`` of a work dir:

1. an existing render, ``pages/pg-NNN.{jpg,jpeg,png}`` (the scouting
   convention; gitignored, regenerable);
2. otherwise the page is rendered from ``work.json``'s ``source_pdf`` with
   ``pdftoppm`` into ``pages/``. PDF page = ``n + pdf_offset``
   (``work.json`` ``pages.pdf_offset``, default 0).

Usage:

    python3 -m exscriptor.render works/<work> 34            # prints the image path
    python3 -m exscriptor.render works/<work> 34 --dpi 300 --open
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import typer
from typing_extensions import Annotated

EXTS = (".jpg", ".jpeg", ".png")


def _meta(work: Path) -> dict:
    p = work / "work.json"
    return json.loads(p.read_text()) if p.exists() else {}


def pdf_page(work: Path, n: int) -> int:
    return n + int((_meta(work).get("pages") or {}).get("pdf_offset", 0))


def page_image(work: Path, n: int, dpi: int = 200, fresh: bool = False) -> Path:
    """Path to an image of page ``n``; renders it if no render exists."""
    pages = work / "pages"
    if not fresh:
        for ext in EXTS:
            p = pages / f"pg-{n:03d}{ext}"
            if p.exists():
                return p
    src = _meta(work).get("source_pdf")
    if not src:
        raise FileNotFoundError(f"no render of page {n} in {pages} and no source_pdf in work.json")
    pdf = Path(os.path.expanduser(src))
    if not pdf.is_absolute():
        pdf = work / pdf
    if not pdf.exists():
        raise FileNotFoundError(f"source_pdf not found: {pdf}")
    if not shutil.which("pdftoppm"):
        raise RuntimeError("pdftoppm (poppler) is needed to render pages")
    pages.mkdir(exist_ok=True)
    k = pdf_page(work, n)
    stem = pages / f"pg-{n:03d}"
    subprocess.run(["pdftoppm", "-jpeg", "-r", str(dpi), "-f", str(k), "-l", str(k), "-singlefile",
                    str(pdf), str(stem)], check=True, capture_output=True)
    return stem.with_suffix(".jpg")


def main(
    work: Annotated[Path, typer.Argument()],
    page: Annotated[int, typer.Argument()],
    dpi: Annotated[int, typer.Option()] = 200,
    fresh: Annotated[bool, typer.Option(help="Re-render even if a render exists")] = False,
    open_: Annotated[bool, typer.Option("--open", help="Open it in the system viewer")] = False,
):
    """Print the path of page N's image (rendering it if needed)."""
    img = page_image(work, page, dpi, fresh)
    print(img)
    if open_:
        opener = "open" if sys.platform == "darwin" else "xdg-open"
        subprocess.run([opener, str(img)], check=False)


app = typer.Typer(add_completion=False)
app.command()(main)

if __name__ == "__main__":
    app()
