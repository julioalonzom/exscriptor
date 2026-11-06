#!/usr/bin/env python3
"""f / long-s (ſ) confusions in diplomatic page files: screen them, then crop them for the eye.

Why: in roman type of the 16th-17th c. ``f`` and ``ſ`` differ by one stroke
(the crossbar runs through the stem on ``f``, stops at its left on ``ſ``), and
both readers we use confuse them in BOTH directions. On Soto 1550 (2026-11):
the lector draft wrote ``fit`` for ``ſit`` and ``somitem`` for ``fomitem``
about 260 times in 264 pages; the LLM corrector, re-deciding ~51,000 long s
from the image, fixed most and introduced its own (``infusionem`` ->
``inſuſionem``, ``efformabat`` -> ``eſformabat``). Many confusions are real
words either way (``fit``/``ſit``, ``fine``/``ſine``, ``forte``/``ſorte``,
``fiunt``/``ſiunt``), so no mapping can fix them: the print decides, site by
site.

``screen`` lists every f- or ſ-bearing token whose other reading the corpus
lexicon (built WITHOUT this work) knows:

- ``oov``: the page's form is unknown and the other is a word -- almost
  always a misread;
- ``dominated``: both known, the other >= 5x more frequent;
- ``pair``: both are common words, neither 5x commoner -- context may
  guess, only the scan decides. A page form much commoner than its swap
  (``ſit`` against ``fit``) is not listed: sample those by page instead
  (``sheets --all-f``).

``sheets`` cuts each site's word from the page scan (tesseract word boxes,
aligned to the page file with f/ſ/s folded) onto labelled contact sheets for
one eye pass; a verdict TSV (``id<TAB>f|ſ|ok<TAB>note``) closes them.

    python3 -m exscriptor.longs screen works/<w>/diplomatic --lexicon .cache/lex.json --out sites.tsv
    python3 -m exscriptor.longs sheets sites.tsv --scans 'works/<w>/tmp/scans/<w>/{page}.jpg' --out-dir sheets/
    python3 -m exscriptor.longs sheets --all-f --pages pg-012,pg-014 ...   # random-page audit: every f
"""
from __future__ import annotations

import csv
import io
import itertools
import json
import re
import subprocess
import unicodedata
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path

import typer
from typing_extensions import Annotated

app = typer.Typer(add_completion=False, help=__doc__.split("\n\n")[0])
WORD = re.compile(r"[^\W\d_]+")
COMMENT = re.compile(r"<!--.*?-->", re.S)
MAX_SITES = 4  # f/ſ positions per token tried exhaustively (2^4 variants)


def fold(t: str) -> str:
    """Lexicon key: lowercase, long s as s, u/v and i/j merged, ligatures spelled out."""
    t = unicodedata.normalize("NFC", t.lower())
    for a, b in (("ſ", "s"), ("v", "u"), ("j", "i"), ("æ", "ae"), ("œ", "oe"), ("ę", "ae")):
        t = t.replace(a, b)
    return t


def folded_lexicon(path: Path) -> Counter:
    c: Counter = Counter()
    for form, n in json.loads(path.read_text())["forms"].items():
        c[fold(form)] += n
    return c


def page_tokens(text: str) -> list[str]:
    return WORD.findall(unicodedata.normalize("NFC", COMMENT.sub(" ", text)))


def plain(token: str) -> bool:
    """No combining mark or abbreviation sign: an abbreviated token's lexicon form is not its letters."""
    return all(not unicodedata.combining(c) for c in unicodedata.normalize("NFD", token)) and all(
        c.isascii() or c in "ſæœę" for c in token)


def classify(token: str, lex: Counter, ratio: float = 5, common: int = 20) -> tuple[str, str, int, int] | None:
    """(kind, other reading, count of the page's form, count of the other) or None.

    The other reading swaps f <-> ſ at one or more positions (an ``s`` is
    never touched: round s is not confused with f)."""
    if not plain(token):
        return None
    idx = [i for i, c in enumerate(token) if c in "fſ"][:MAX_SITES]
    if not idx:
        return None
    own = lex.get(fold(token), 0)
    swap = {"f": "ſ", "ſ": "f"}
    best, bc = "", 0
    for k in range(1, len(idx) + 1):
        for sub in itertools.combinations(idx, k):
            alt = "".join(swap[c] if i in sub else c for i, c in enumerate(token))
            n = lex.get(fold(alt), 0)
            if n > bc:
                best, bc = alt, n
    if not bc:
        return None
    if own == 0:
        return "oov", best, own, bc
    if bc >= ratio * own:
        return "dominated", best, own, bc
    if own >= common and bc >= common and own < ratio * bc:
        return "pair", best, own, bc  # page form commoner by >= ratio (ſit vs fit): not listed
    return None


@app.command()
def screen(
    pages_dir: Annotated[Path, typer.Argument(help="diplomatic/ (pg-*.md)")],
    lexicon: Annotated[Path, typer.Option(help="exscriptor.lexicon JSON built WITHOUT this work")],
    out: Annotated[Path, typer.Option(help="sites TSV")],
    ratio: Annotated[float, typer.Option(help="'dominated' when the other reading is this many times commoner")] = 5,
    common: Annotated[int, typer.Option(help="'pair' when both readings occur at least this often")] = 20,
):
    """Every f/ſ token whose swapped reading the lexicon knows, with its page, index and context."""
    meta = json.loads(lexicon.read_text())
    work = pages_dir.resolve().parent
    if not any(work.name in p for p in meta.get("exclude", [])):
        typer.echo(f"warning: lexicon does not exclude {work.name}: its own misreads count as words", err=True)
    lex = folded_lexicon(lexicon)
    rows = []
    for p in sorted(pages_dir.glob("pg-*.md")):
        toks = page_tokens(p.read_text())
        for i, t in enumerate(toks):
            hit = classify(t, lex, ratio, common)
            if hit:
                kind, alt, own, other = hit
                rows.append([p.stem, i, t, alt, kind, own, other, " ".join(toks[max(0, i - 4):i + 5])])
    order = {"oov": 0, "dominated": 1, "pair": 2}
    rows.sort(key=lambda r: (order[r[4]], r[0], r[1]))
    with out.open("w", newline="") as f:
        w = csv.writer(f, delimiter="\t", lineterminator="\n")
        w.writerow(["id", "page", "index", "token", "other", "kind", "lex_token", "lex_other", "context"])
        for n, r in enumerate(rows, 1):
            w.writerow([f"s{n:04d}", *r])
    typer.echo(f"{len(rows)} sites: " + ", ".join(f"{k} {v}" for k, v in Counter(r[4] for r in rows).items()))


def _skey(t: str) -> str:
    t = "".join(c for c in unicodedata.normalize("NFD", t.lower()) if not unicodedata.combining(c))
    for a, b in (("ſ", "s"), ("f", "s"), ("v", "u"), ("j", "i"), ("æ", "ae"), ("œ", "oe")):
        t = t.replace(a, b)
    return t


def align(page: list[str], ocr: list[str]) -> dict[int, int]:
    """Page-token index -> OCR-token index, with f, ſ and s folded together."""
    sm = SequenceMatcher(None, [_skey(w) for w in page], [_skey(w) for w in ocr], autojunk=False)
    amap: dict[int, int] = {}
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal" or (tag == "replace" and i2 - i1 == j2 - j1):
            amap.update({i1 + k: j1 + k for k in range(i2 - i1)})
    return amap


def _font(size: int):
    from PIL import ImageFont
    for f in ("/System/Library/Fonts/Supplemental/Times New Roman.ttf", "/Library/Fonts/Arial Unicode.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        if Path(f).exists():
            return ImageFont.truetype(f, size)
    return ImageFont.load_default(size=size)


@app.command()
def sheets(
    sites: Annotated[Path | None, typer.Argument(help="sites TSV from `screen` (omit with --all-f)")] = None,
    scans: Annotated[str, typer.Option(help="scan path pattern with {page}, e.g. 'tmp/scans/w/{page}.jpg'")] = "",
    out_dir: Annotated[Path, typer.Option()] = Path("sheets"),
    pages_dir: Annotated[Path, typer.Option(help="diplomatic/ (pg-*.md): sites are located by token index")] = Path("diplomatic"),
    all_f: Annotated[bool, typer.Option(help="every f-bearing token of --pages: the random-page audit")] = False,
    pages: Annotated[str, typer.Option(help="comma-separated pg-NNN for --all-f")] = "",
    lang: Annotated[str, typer.Option(help="tesseract language")] = "lat",
    per_sheet: Annotated[int, typer.Option()] = 40,
):
    """Labelled word crops from the scan, one tile per site; unlocated sites listed in unlocated.tsv."""
    from PIL import Image, ImageDraw

    out_dir.mkdir(parents=True, exist_ok=True)
    if all_f:
        if not pages:
            raise typer.BadParameter("--all-f needs --pages")
        todo = []
        for pg in pages.split(","):
            toks = page_tokens((pages_dir / f"{pg}.md").read_text())
            todo += [{"id": f"{pg}#{i}", "page": pg, "index": str(i), "token": t,
                      "context": " ".join(toks[max(0, i - 3):i + 4])} for i, t in enumerate(toks) if "f" in t]
    else:
        todo = list(csv.DictReader(sites.open(), delimiter="\t"))
    by_page: dict[str, list[dict]] = {}
    for s in todo:
        by_page.setdefault(s["page"], []).append(s)
    font, tiles, lost = _font(22), [], []
    for pg, ss in sorted(by_page.items()):
        img = Path(scans.format(page=pg))
        toks = page_tokens((pages_dir / f"{pg}.md").read_text())
        tsv = subprocess.run(["tesseract", str(img), "-", "-l", lang, "tsv"], capture_output=True, text=True,
                             check=True).stdout
        boxes = []
        for r in csv.DictReader(io.StringIO(tsv), delimiter="\t", quoting=csv.QUOTE_NONE):
            if r["level"] == "5" and r["text"].strip():
                boxes += [(w, r) for w in WORD.findall(r["text"])]
        amap = align(toks, [w for w, _ in boxes])
        im = Image.open(img).convert("L")
        for s in ss:
            i = int(s["index"])
            if i not in amap:
                lost.append(s)
                continue
            b = boxes[amap[i]][1]
            x, y, w, h = (int(b[k]) for k in ("left", "top", "width", "height"))
            crop = im.crop((max(0, x - 40), max(0, y - 10), x + w + 40, y + h + 10))
            crop = crop.resize((crop.width * 2, crop.height * 2), Image.LANCZOS)
            label = f"{s['id']}  {s['token']}" + (f" / {s['other']}" if s.get("other") else "")
            tile = Image.new("L", (max(crop.width, 420), crop.height + 56), 255)
            d = ImageDraw.Draw(tile)
            d.text((2, 0), label, fill=0, font=font)
            d.text((2, 26), s.get("context", "")[:60], fill=90, font=_font(18))
            tile.paste(crop, (0, 56))
            tiles.append(tile)
    with (out_dir / "unlocated.tsv").open("w") as f:
        f.writelines(f"{s['id']}\t{s['page']}\t{s['token']}\t{s.get('context', '')}\n" for s in lost)
    W = 1600
    for n, chunk in enumerate(itertools.batched(tiles, per_sheet) if hasattr(itertools, "batched")
                              else (tiles[k:k + per_sheet] for k in range(0, len(tiles), per_sheet)), 1):
        rows, row, rw = [], [], 0
        for t in chunk:
            if row and rw + t.width > W:
                rows.append(row)
                row, rw = [], 0
            row.append(t)
            rw += t.width + 10
        rows.append(row)
        sheet = Image.new("L", (W, sum(max(t.height for t in r) + 10 for r in rows)), 255)
        y = 0
        for r in rows:
            x = 0
            for t in r:
                sheet.paste(t, (x, y))
                x += t.width + 10
            y += max(t.height for t in r) + 10
        sheet.save(out_dir / f"sheet-{n:02d}.png")
    typer.echo(f"{len(tiles)} tiles on {(len(tiles) + per_sheet - 1) // per_sheet} sheets; {len(lost)} unlocated")


if __name__ == "__main__":
    app()
