#!/usr/bin/env python3
"""Word-level diff of two supplied digital transcriptions of the same text.

Why: when a transcription is handed over as digital text (a DOCX, a chunked
HTML corpus) rather than as page images, nothing is read and the supplied
files are witnesses, not sources. One of them is normally the ancestor of the
other — a format conversion or a spell-check pass sits between them — and
those passes do invisible damage: rare words silently replaced by common ones
(``quoddam`` -> ``quodam``), and formatted spans deleted and re-entered by
hand. Neither is visible to any downstream gate, and both are exactly what a
word-level diff finds.

The print stays the arbiter: a difference is located here and settled on the
page image, never by preferring the later file. Formatting is a separate
channel — a word whose italics differ while its letters agree is a ``span``
site, since restoring a span is a different decision from correcting a word.

Reads:

- DOCX: ``word/document.xml`` paragraphs and runs (``w:rPr/w:i`` is the italic
  state; ``w:br``/``w:cr`` are breaks inside a paragraph), then
  ``word/footnotes.xml`` as trailing note blocks.
- HTML: ``<p>`` blocks, ``<i>``/``<em>`` spans, ``<br>``, entity decoding and
  the declared charset; a paragraph that is only a link is navigation and is
  dropped, and number-led paragraphs are read as notes.

Nothing edition-specific is hardcoded: banners, standing headers and footers
are dropped by a caller-supplied ``--drop`` regex.

Usage:

    python3 -m exscriptor.supplied A.docx B.html --out sites.jsonl \\
        [--drop 'Version of June' --drop 'Letzte [AÄ]nder'] [--dump-dir tmp/]

``--dump-dir`` writes both normalized flows as ``a.txt`` / ``b.txt``, one
block per line, so the parse can be eyeballed before the sites are trusted.
"""
from __future__ import annotations

import html as html_mod
import json
import re
import zipfile
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from xml.etree import ElementTree as ET

import typer
from typing_extensions import Annotated

from exscriptor.collate import fold

app = typer.Typer(add_completion=False, help=__doc__.split("\n\n")[0])

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
WORD = re.compile(r"[^\W_]+")
NOTE_OPEN = re.compile(r"^(\d+)\s+(\S.*)$", re.S)
HEAD = re.compile(r"<head\b.*?</head>", re.S | re.I)
SCRIPT = re.compile(r"<(script|style)\b.*?</\1>", re.S | re.I)
COMMENT = re.compile(r"<!--.*?-->", re.S)
CHARSET = re.compile(rb"charset=[\"']?([\w-]+)", re.I)
PARA = re.compile(r"<p\b[^>]*>(.*?)</p>", re.S | re.I)
BODY = re.compile(r"<body\b[^>]*>(.*?)</body>", re.S | re.I)
ITALIC = re.compile(r"<(i|em)\b[^>]*>(.*?)</\1>", re.S | re.I)
# OpenOffice/StarOffice HTML export: footnotes in <div id="sdfootnoteN">, the
# marker in the text is an anchor or a <sup> holding the bare number.
NOTE_DIV = re.compile(r"<div\b[^>]*\bid=[\"']?sdfootnote(\d+)[\"']?[^>]*>(.*?)</div>", re.S | re.I)
SYMBOL = re.compile(r"<(a|sup)\b[^>]*>\s*\d+\s*</\1>", re.S | re.I)
TAG = re.compile(r"<[^>]+>")
BR = re.compile(r"<br\b[^>]*>", re.I)
LINK_ONLY = re.compile(r"^(<a\b.*?</a>\s*)+$", re.S | re.I)
# Invisible formatting characters: a soft hyphen or zero-width space inside a
# word is not a reading, and exported HTML from word processors is full of
# them. They are stripped from the extracted text itself, not just folded.
INVISIBLE = dict.fromkeys(map(ord, "\u00ad\u200b\u200c\u200d\ufeff"), None)
ENC = {"utf8": "utf-8", "latin1": "cp1252", "iso-8859-1": "cp1252", "windows-1252": "cp1252"}
BRACKET_NOTE = re.compile(r"^\[(\d+)\]")


# ---------------------------------------------------------------- documents

@dataclass
class Block:
    """One paragraph-shaped unit: a run list, plus its note number if any."""
    spans: list[tuple[bool, str]] = field(default_factory=list)
    note: int | None = None

    @property
    def text(self) -> str:
        return "".join(t for _, t in self.spans).strip()

    def words(self) -> list[tuple[str, bool]]:
        """(raw, italic) per word, over the block's joined text.

        Tokenizing the joined text, not each span, is what re-joins a word a
        conversion split across runs (``subsiste`` + ``ndo``).
        """
        text = "".join(t for _, t in self.spans)
        flags: list[bool] = []
        for italic, t in self.spans:
            flags.extend([italic] * len(t))
        return [(m.group(0), flags[m.start()]) for m in WORD.finditer(text)]


def _plain(spans: list[tuple[bool, str]]) -> list[tuple[bool, str]]:
    """Collapse whitespace, drop invisible characters, drop empty spans."""
    out: list[tuple[bool, str]] = []
    for italic, text in spans:
        t = text.translate(INVISIBLE).replace("\u00a0", " ")
        t = re.sub(r"\s+", " ", t)
        if t.strip():
            out.append((italic, t))
    return out


# ------------------------------------------------------------------- DOCX

def _italic(rpr: ET.Element | None) -> bool:
    if rpr is None:
        return False
    i = rpr.find(W + "i")
    return i is not None and i.get(W + "val") not in ("0", "false", "off")


def _runs(el: ET.Element) -> list[tuple[bool, str]]:
    out: list[tuple[bool, str]] = []
    for r in el.iter(W + "r"):
        italic = _italic(r.find(W + "rPr"))
        buf: list[str] = []
        for child in r:
            tag = child.tag
            if tag == W + "t":
                buf.append(child.text or "")
            elif tag in (W + "br", W + "cr", W + "tab"):
                buf.append(" ")
            elif tag == W + "noBreakHyphen":
                # A non-breaking hyphen is a character, not formatting: dropping
                # it turns 'I-II' into 'III' in citations, which then reads as a
                # different reference and shows up as a phantom site.
                buf.append("-")
            elif tag == W + "softHyphen":
                buf.append("")                 # a hyphenation hint, not text
            elif tag == W + "sym":
                code = child.get(W + "char")
                buf.append(chr(int(code, 16)) if code else "")
        if buf:
            out.append((italic, "".join(buf)))
    return out


def read_docx(path: Path) -> list[Block]:
    """Body paragraphs in order, then the footnotes as note blocks."""
    z = zipfile.ZipFile(path)
    doc = ET.fromstring(z.read("word/document.xml"))
    blocks = [Block(spans=s) for p in doc.iter(W + "p") if (s := _plain(_runs(p)))]
    if "word/footnotes.xml" in z.namelist():
        fn = ET.fromstring(z.read("word/footnotes.xml"))
        for n in fn.findall(W + "footnote"):
            num = int(n.get(W + "id") or -1)
            if num <= 0:  # separator / continuationSeparator
                continue
            spans = _plain(_runs(n))
            if spans:
                blocks.append(Block(spans=spans, note=num))
    return blocks


# ------------------------------------------------------------------- HTML

def _decode(raw: bytes) -> str:
    """UTF-8 when the bytes are valid UTF-8, else the declared charset.

    Old exports declare a charset their own bytes contradict: one file in the
    Suárez corpus is declared windows-1252 and holds UTF-8 Greek.
    """
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        m = CHARSET.search(raw[:4096])
        enc = (m.group(1).decode("ascii", "replace") if m else "cp1252").lower()
        return raw.decode(ENC.get(enc, enc), errors="replace")


def _clean(s: str) -> str:
    return html_mod.unescape(TAG.sub("", BR.sub(" ", s)))


def _html_spans(frag: str) -> list[tuple[bool, str]]:
    """(italic, text) for one paragraph's inner HTML, tags removed."""
    parts: list[tuple[bool, str]] = []
    pos = 0
    for m in ITALIC.finditer(frag):
        if m.start() > pos:
            parts.append((False, _clean(frag[pos:m.start()])))
        parts.append((True, _clean(m.group(2))))
        pos = m.end()
    parts.append((False, _clean(frag[pos:])))
    return _plain(parts)


def read_html(path: Path) -> list[Block]:
    """Body paragraphs in order; number-led trailing paragraphs are notes.

    Exported footnotes are read from their own containers when the export has
    them, and the number-led fallback covers exports that inline the notes as
    trailing paragraphs.
    """
    text = HEAD.sub(" ", COMMENT.sub(" ", _decode(path.read_bytes())))
    text = SCRIPT.sub(" ", text)
    m = BODY.search(text)
    if m:
        text = m.group(1)
    notes: list[Block] = []
    for num, frag in NOTE_DIV.findall(text):
        spans = _plain(_html_spans(SYMBOL.sub(" ", frag)))
        if spans:
            notes.append(Block(spans=spans, note=int(num)))
    text = NOTE_DIV.sub(" ", text)
    blocks: list[Block] = []
    pending: list[Block] = []
    for frag in PARA.findall(text):
        if LINK_ONLY.match(frag.strip()):
            continue
        spans = _plain(_html_spans(SYMBOL.sub(" ", frag)))
        if not spans:
            continue
        plain = "".join(t for _, t in spans)
        bracketed = BRACKET_NOTE.match(plain)
        hit = NOTE_OPEN.match(plain)
        if bracketed and blocks:
            # An apparatus line written "[N] reading, alit. variant" in the
            # text rather than exported as a footnote.
            pending.append(Block(spans=_without_lead(spans, r"^\[\d+\]\s*"), note=int(bracketed.group(1))))
        elif hit and blocks:
            pending.append(Block(spans=_without_lead(spans, r"^\d+\s*"), note=int(hit.group(1))))
        else:
            blocks.extend(pending)
            pending = []
            blocks.append(Block(spans=spans))
    blocks.extend(pending)
    return blocks + notes


def _without_lead(spans: list[tuple[bool, str]], pattern: str) -> list[tuple[bool, str]]:
    """Drop a note's own numbering, however the export writes it."""
    out = list(spans)
    italic, first = out[0]
    out[0] = (italic, re.sub(pattern, "", first))
    return out


def read(path: Path) -> list[Block]:
    return read_docx(path) if path.suffix.lower() in (".docx", ".doc") else read_html(path)


# ------------------------------------------------------------------- diff

def _drop(blocks: list[Block], patterns: list[str]) -> list[Block]:
    rx = [re.compile(p, re.I) for p in patterns]
    return [b for b in blocks if not any(r.search(b.text) for r in rx)]


def _stream(blocks: list[Block], base: int = 0) -> tuple[list[str], list[tuple[bool, str, int, int]]]:
    """Folded token stream, and (italic, raw, note number, block ordinal) per token."""
    folded: list[str] = []
    index: list[tuple[bool, str, int, int]] = []
    for bi, b in enumerate(blocks, start=base):
        for raw, italic in b.words():
            folded.append(fold(raw))
            index.append((italic, raw, b.note or 0, bi))
    return folded, index


def _at(index: list[tuple[bool, str, int, int]], i: int, field: int):
    return index[i][field] if 0 <= i < len(index) else None


def _context(index: list[tuple[bool, str, int, int]], lo: int, hi: int, n: int = 5) -> str:
    left = " ".join(t[1] for t in index[max(0, lo - n):lo])
    right = " ".join(t[1] for t in index[hi:hi + n])
    return f"{left} […] {right}".strip()


def _tokenset(b: Block) -> frozenset[str]:
    return frozenset(fold(w) for w, _ in b.words())


def archaic(tok: str) -> str:
    """Folded, with the u/v and i/j distinctions flattened.

    Witnesses of an older print routinely differ only in that spelling — one
    normalizes the print's ``hujus`` to ``huius``, the other keeps it. That is
    not a different reading, and house style normalizes it anyway, so it is
    its own class rather than a word to adjudicate.
    """
    return fold(tok).replace("j", "i").replace("v", "u")


ROMAN = set("IVXLCDM")


def numeral(tok: str) -> int | None:
    """The number a token spells, roman or arabic, else None.

    Cross-references are written roman in one witness and arabic in the other
    ("sect. V" against "sect. 5"), which is notation and not a reading — house
    style decides it, so it gets its own class instead of a word to adjudicate.
    """
    t = tok.strip().strip(".").upper()
    if not t:
        return None
    if t.isdigit():
        return int(t)
    if set(t) <= ROMAN:
        val = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
        n = 0
        for i, ch in enumerate(t):
            n += -val[ch] if i + 1 < len(t) and val[t[i + 1]] > val[ch] else val[ch]
        return n
    return None


GAP = -0.35        # cost of leaving a block unpaired, against Jaccard 0..1
FLOOR = 0.30       # below this two blocks are not the same paragraph
WINDOW = 40        # |i - j| beyond this needs no similarity: 0 anyway
GLUE_WINDOW = 200  # how far a lost-space run is looked for, in sites


def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def align(A: list[Block], B: list[Block]) -> list[tuple[str, int | None, int | None]]:
    """Align two block lists by token overlap, monotonically.

    Not by an exact key per block: a conversion drops headings, adds banners
    and glues words across line breaks, so any fixed signature either misses
    the same paragraph or collides. A paragraph that drifted one place
    mispairs with its neighbour, and then nearly every paragraph in the unit
    reports a third of its words as unmatched — thousands of false sites
    burying the real ones.
    """
    sa, sb = [_tokenset(x) for x in A], [_tokenset(y) for y in B]
    na, nb = len(A), len(B)
    back: list[list[tuple[int, int]]] = [[(0, 0)] * (nb + 1) for _ in range(na + 1)]
    dp = [[0.0] * (nb + 1) for _ in range(na + 1)]
    for i in range(1, na + 1):
        dp[i][0] = i * GAP
    for j in range(1, nb + 1):
        dp[0][j] = j * GAP
    for i in range(1, na + 1):
        for j in range(1, nb + 1):
            if abs(i - j) > WINDOW:
                sim = 0.0
            else:
                sim = _jaccard(sa[i - 1], sb[j - 1])
            diag = dp[i - 1][j - 1] + (sim if sim >= FLOOR else -1.0)
            up, left = dp[i - 1][j] + GAP, dp[i][j - 1] + GAP
            best = max(diag, up, left)
            dp[i][j] = best
            back[i][j] = (i - 1, j - 1) if best == diag else ((i - 1, j) if best == up else (i, j - 1))
    ops: list[tuple[str, int | None, int | None]] = []
    i, j = na, nb
    while i or j:
        pi, pj = back[i][j]
        if (pi, pj) == (i - 1, j - 1):
            sim = _jaccard(sa[i - 1], sb[j - 1])
            if sim >= FLOOR:
                ops.append(("pair", i - 1, j - 1))
            else:  # the DP had no better option; two blocks, not one
                ops.append(("b", None, j - 1))
                ops.append(("a", i - 1, None))
        elif (pi, pj) == (i - 1, j):
            ops.append(("a", i - 1, None))
        else:
            ops.append(("b", None, j - 1))
        i, j = pi, pj
    ops.reverse()
    return ops


def _word_sites(fa, ia, fb, ib) -> list[dict]:
    """Word-level sites between one aligned pair of blocks."""
    sites: list[dict] = []

    def site(kind: str, i1: int, i2: int, j1: int, j2: int) -> None:
        sites.append({
            "kind": kind,
            "a": " ".join(t[1] for t in ia[i1:i2]),
            "b": " ".join(t[1] for t in ib[j1:j2]),
            "italic_a": _at(ia, i1, 0),
            "italic_b": _at(ib, j1, 0),
            "note_a": _at(ia, i1, 2) or None,
            "note_b": _at(ib, j1, 2) or None,
            "block_a": _at(ia, i1, 3),
            "block_b": _at(ib, j1, 3),
            "context": _context(ia, i1, i2),
        })

    for tag, i1, i2, j1, j2 in SequenceMatcher(None, fa, fb, autojunk=False).get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                if ia[i1 + k][0] != ib[j1 + k][0]:
                    site("span", i1 + k, i1 + k + 1, j1 + k, j1 + k + 1)
            continue
        if tag == "replace":
            n = min(i2 - i1, j2 - j1)
            for k in range(n):
                i, j = i1 + k, j1 + k
                if fa[i] == fb[j]:
                    kind = "span"
                elif archaic(fa[i]) == archaic(fb[j]):
                    kind = "orthography"
                elif (na := numeral(fa[i])) is not None and na == numeral(fb[j]):
                    kind = "numeral"
                else:
                    kind = "word"
                site(kind, i, i + 1, j, j + 1)
            if i2 - i1 > n:
                site("a-only", i1 + n, i2, j2, j2)
            if j2 - j1 > n:
                site("b-only", i2, i2, j1 + n, j2)
        elif tag == "delete":
            site("a-only", i1, i2, j1, j1)
        else:
            site("b-only", i1, i1, j1, j2)
    return _merge_glue(sites)


def _merge_glue(rows: list[dict]) -> list[dict]:
    """Collapse a word glued to its neighbour into one site.

    A conversion that turns a line break into nothing leaves two words with no
    space between them, which the diff reports twice — once as a word that
    cannot match, once as the unmatched remainder. It is one event, and a
    class the ledger summarises in bulk rather than adjudicating case by case,
    so it is one row: ``glue-a`` when A holds the glued pair.

    The loss can also run across a whole paragraph, so the unit is a *run* of
    sites, tested as a run: the two sides identical once whitespace is ignored.
    A real difference anywhere inside breaks that, which is what keeps this
    from swallowing one.
    """
    def packed(s: str) -> str:
        return re.sub(r"\s+", "", s)

    out: list[dict] = []
    i = 0
    while i < len(rows):
        run: tuple[int, str, str] | None = None
        a_parts: list[str] = []
        b_parts: list[str] = []
        for j in range(i, min(i + GLUE_WINDOW, len(rows))):
            a_parts.append(rows[j]["a"])
            b_parts.append(rows[j]["b"])
            a = " ".join(p for p in a_parts if p)
            b = " ".join(p for p in b_parts if p)
            if a != b and packed(a) == packed(b):
                run = (j + 1, a, b)
        if run:
            end, a, b = run
            first = rows[i]
            kind = "glue-a" if a.count(" ") < b.count(" ") else "glue-b"
            out.append({**first, "kind": kind, "a": a, "b": b,
                        "context": f"{first['context']} [run of {end - i} sites]"})
            i = end
            continue
        out.append(rows[i])
        i += 1
    return out


def _whole(kind: str, blocks: list[Block], block_no: int, sites: list[dict], path: str) -> None:
    """A block present in one witness and not the other."""
    b = blocks[block_no]
    sites.append({
        "kind": kind,
        "a": b.text if path == "a" else "",
        "b": b.text if path == "b" else "",
        "italic_a": None,
        "italic_b": None,
        "note_a": b.note if path == "a" else None,
        "note_b": b.note if path == "b" else None,
        "block_a": block_no if path == "a" else None,
        "block_b": block_no if path == "b" else None,
        "context": b.text[:120],
    })


def diff(a: Path, b: Path, drop: list[str] | None = None) -> dict:
    """Differences between two witnesses of the same text, block by block."""
    A = _drop(read(a), drop or [])
    B = _drop(read(b), drop or [])
    sites: list[dict] = []
    for tag, i, j in align(A, B):
        if tag == "pair":
            sites.extend(_word_sites(*_stream([A[i]], base=i), *_stream([B[j]], base=j)))
        elif tag == "a":
            _whole("a-block-only", A, i, sites, "a")
        else:
            _whole("b-block-only", B, j, sites, "b")
    for n, s in enumerate(sites, start=1):
        s["id"] = n
    return {"blocks_a": len(A), "blocks_b": len(B),
            "words_a": sum(len(x.words()) for x in A),
            "words_b": sum(len(x.words()) for x in B), "sites": sites}


def dump(path: Path, dest: Path, drop: list[str] | None = None) -> None:
    lines = [f"{'[note %d] ' % b.note if b.note else ''}{b.text}"
             for b in _drop(read(path), drop or [])]
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("\n".join(lines) + "\n", encoding="utf-8")


@app.command()
def main(
    a: Annotated[Path, typer.Argument(help="Witness A (the file decisions apply to)")],
    b: Annotated[Path, typer.Argument(help="Witness B (the second witness)")],
    out: Annotated[Path, typer.Option("--out", help="Sites JSONL")] = None,
    drop: Annotated[list[str], typer.Option("--drop", help="Regex: drop blocks matching (banners, footers)")] = None,
    dump_dir: Annotated[Path, typer.Option("--dump-dir", help="Write both flows as a.txt / b.txt")] = None,
) -> None:
    r = diff(a, b, drop)
    kinds: dict[str, int] = {}
    for s in r["sites"]:
        k = s["kind"] + ("/note" if (s["note_a"] or s["note_b"]) else "")
        kinds[k] = kinds.get(k, 0) + 1
    typer.echo(json.dumps({k: v for k, v in r.items() if k != "sites"}
                          | {"sites": len(r["sites"]), "kinds": kinds}, ensure_ascii=False))
    if dump_dir:
        dump(a, dump_dir / "a.txt", drop)
        dump(b, dump_dir / "b.txt", drop)
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", encoding="utf-8") as fh:
            for s in r["sites"]:
                fh.write(json.dumps(s, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    app()
