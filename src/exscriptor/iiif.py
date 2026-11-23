#!/usr/bin/env python3
"""A library's IIIF scan as a work's source: page images, its OCR, one PDF.

Why: digital libraries (the BSB, e-rara, Gallica…) serve each page as a IIIF
image and their own OCR as hOCR, but no PDF with a text layer. The pipeline
wants both: the reader reads ``pages/pg-NNN.jpg``, and ``collate``, ``crop``
and the gates read the OCR witness from a PDF's text layer (``pdftotext
-bbox-layout``). This builds that PDF from the library's own images (embedded
unchanged, never recompressed) and its own hOCR (written as invisible text at
the hOCR's word boxes), so the OCR witness is the library's, not ours.

Page numbers are canvas numbers: page file ``pg-NNN`` is canvas NNN (1-based)
and PDF page NNN, so ``pdf_offset`` is 0. Canvases before the requested range
become blank pages, so PDF page numbers still equal canvas numbers.

Usage:

    python3 -m exscriptor.iiif fetch <manifest-url> --canvases 300-560 --out works/<w>/raw/iiif
    python3 -m exscriptor.iiif pdf works/<w>/raw/iiif --out works/<w>/raw/source.pdf

``fetch`` is resumable (existing files are kept) and writes ``pg-NNN.jpg``,
``pg-NNN.hocr`` (when the canvas names an hOCR ``seeAlso``) and
``manifest.json``. ``--no-images`` fetches the OCR only (to find a range).
``pdf`` needs PyMuPDF (``pip install pymupdf``).
"""
from __future__ import annotations

import html
import json
import re
import time
import urllib.request
from pathlib import Path

import typer
from typing_extensions import Annotated

from exscriptor import https

app = typer.Typer(add_completion=False, help=__doc__)
UA = {"User-Agent": "exscriptor (scholarly digitization)"}
WORD = re.compile(r"""<span[^>]*class=['"]ocrx_word['"][^>]*title=['"]bbox (\d+) (\d+) (\d+) (\d+)[^'"]*['"][^>]*>(.*?)</span>""", re.S)
PAGE_BOX = re.compile(r"""class=['"]ocr_page['"][^>]*title=['"][^'"]*bbox 0 0 (\d+) (\d+)""")


def _get(url: str, tries: int = 4) -> bytes:
    for i in range(tries):
        try:
            with https.urlopen(urllib.request.Request(url, headers=UA), timeout=120) as r:
                return r.read()
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(2 ** i)
    raise AssertionError


def canvases(manifest: dict) -> list[dict]:
    """IIIF Presentation v2 or v3: [{image, hocr, width, height}] in canvas order."""
    out = []
    items = manifest["sequences"][0]["canvases"] if "sequences" in manifest else manifest["items"]
    for c in items:
        if "images" in c:  # v2
            svc = c["images"][0]["resource"].get("service", {})
            image = (svc.get("@id") + "/full/full/0/default.jpg") if svc.get("@id") else c["images"][0]["resource"]["@id"]
        else:  # v3
            body = c["items"][0]["items"][0]["body"]
            svc = (body.get("service") or [{}])[0]
            image = (svc.get("id") or svc.get("@id")) + "/full/max/0/default.jpg" if svc else body["id"]
        see = c.get("seeAlso") or []
        see = see if isinstance(see, list) else [see]
        hocr = next((s.get("@id") or s.get("id") for s in see if "hocr" in str(s.get("format", "")) + str(s.get("profile", ""))), None)
        out.append({"image": image, "hocr": hocr, "width": c.get("width"), "height": c.get("height")})
    return out


def hocr_words(text: str) -> list[tuple[str, tuple[int, int, int, int]]]:
    """(word, pixel box) in hOCR order; markup inside a word span is dropped."""
    return [(html.unescape(re.sub(r"<[^>]+>", "", m[4])).strip(), tuple(int(x) for x in m[:4]))
            for m in WORD.findall(text) if re.sub(r"<[^>]+>", "", m[4]).strip()]


@app.command()
def fetch(manifest_url: str,
          out: Annotated[Path, typer.Option(help="Directory for pg-NNN.jpg / pg-NNN.hocr")],
          canvases_: Annotated[str, typer.Option("--canvases", help="First-last canvas, 1-based")] = "",
          images: Annotated[bool, typer.Option(help="Fetch the images (else the OCR only)")] = True):
    out.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(_get(manifest_url))
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False))
    cs = canvases(manifest)
    lo, hi = map(int, canvases_.split("-")) if canvases_ else (1, len(cs))
    for n in range(lo, hi + 1):
        c = cs[n - 1]
        jobs = [(c["hocr"], out / f"pg-{n:03d}.hocr")] + ([(c["image"], out / f"pg-{n:03d}.jpg")] if images else [])
        for url, dest in jobs:
            if url and not dest.exists():
                dest.write_bytes(_get(url))
    typer.echo(f"canvases {lo}-{hi} of {len(cs)} in {out}")


def build_pdf(src: Path, out: Path, dpi: int = 300) -> int:
    """One PDF page per canvas up to the last image in ``src``; returns the page count."""
    import pymupdf
    imgs = {int(p.stem[3:]): p for p in src.glob("pg-*.jpg")}
    if not imgs:
        raise typer.BadParameter(f"no pg-NNN.jpg in {src}")
    scale = 72 / dpi
    doc = pymupdf.open()
    for n in range(1, max(imgs) + 1):
        if n not in imgs:
            doc.new_page(width=200, height=300)  # outside the range: keeps PDF page n = canvas n
            continue
        data = imgs[n].read_bytes()
        pix = pymupdf.Pixmap(data)
        w, h = pix.width, pix.height
        page = doc.new_page(width=w * scale, height=h * scale)
        page.insert_image(page.rect, stream=data)
        hocr = imgs[n].with_suffix(".hocr")
        if hocr.exists():
            text = hocr.read_text(encoding="utf-8")
            if m := PAGE_BOX.search(text):  # hOCR measured on another size of the same image
                sx, sy = w / int(m[1]), h / int(m[2])
            else:
                sx = sy = 1.0
            font, tw = pymupdf.Font("helv"), pymupdf.TextWriter(page.rect)
            for word, (x0, y0, x1, y1) in hocr_words(text):
                x0, x1, y1 = x0 * sx * scale, x1 * sx * scale, y1 * sy * scale
                # ponytail: the font size that makes the word as wide as its hOCR box; pdftotext's
                # word boxes come out within a point or two, and crops pad them anyway.
                size = (x1 - x0) / (font.text_length(word, fontsize=1) or 1)
                tw.append((x0, y1), word, font=font, fontsize=max(size, 0.5))
            tw.write_text(page, render_mode=3)
    doc.save(out, garbage=3, deflate=True)
    return doc.page_count


@app.command()
def pdf(src: Path, out: Annotated[Path, typer.Option(help="The PDF to write")],
        dpi: Annotated[int, typer.Option(help="Pixels per inch the page size assumes")] = 300):
    typer.echo(f"{out}: {build_pdf(src, out, dpi)} pages")


if __name__ == "__main__":
    app()
