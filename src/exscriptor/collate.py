#!/usr/bin/env python3
"""Collate two independent readings of the same pages, with the scan's OCR
layer as the third witness, and settle every disagreement on the page image.

Why: a reading that has been "adjudicated" can still be wrong wherever its
readers agreed with what they expected rather than with the print (``esset``
for a printed ``essent``), and wherever a merge of two passes kept the wrong
pass (a marginal note attached to the wrong anchor). Neither defect is
visible to a ratio screen, a marker count or a witness edition the commented
text lacks. Two independent readings plus the OCR layer locate every such
site, and a crop of the page decides it.

Inputs are page files in the zone format (``<<<NAME>>>`` opens a block, the
next marker or ``<<<END NAME>>>`` closes it; a page without markers is one
``BODY`` block). Keyed notes are spliced into their anchors before collating,
so a note attached to the wrong anchor shows up as a disagreement *at the
anchor*: a block ``NAME`` with refs ``[*N]`` followed by a block
``NAME-MARGINALIA`` holding lines ``*N text``.

Each voice (block name) is collated as one stream over the whole range, so a
block given to the wrong voice appears as a large omission in one stream and
an addition in the other. Folding: case, accents, ligatures (æ œ ſ),
punctuation, markdown and Greek apparatus keys (``[α]``) are ignored.

Sites (JSONL), one per disagreement:

- ``kind: "a-b"``: the readings differ. ``ocr`` gives the OCR layer's reading
  between the nearest agreeing anchors, ``ocr_agrees`` says with whom
  (``a`` / ``b`` / ``neither`` / ``unknown``).
- ``kind: "ocr-only"``: the readings agree and the OCR differs, reported only
  when the OCR's form is a lexicon word and the readings' form is not, or
  the OCR's form is a different lexicon word (``--lexicon``). This is where a
  shared error hides.

``bbox`` (PDF points) locates the site for ``crop``; ``a_span`` holds the
file offsets in witness A, which ``apply`` uses to write decisions back.

Usage:

    python3 -m exscriptor.collate sites A_DIR B_DIR --range 13-63 --pdf X.pdf \\
        --out sites.jsonl [--skip THOMAS-APPARATUS] [--lexicon .cache/latin-lexicon.json]
    python3 -m exscriptor.collate crop sites.jsonl --pdf X.pdf --out-dir crops/ [--dpi 500]
    python3 -m exscriptor.collate apply sites.jsonl decisions.tsv A_DIR [--dry-run]

``decisions.tsv``: ``id<TAB>reading<TAB>evidence``. ``reading`` is the text
the print has at the site, written as it should stand in A's page file
(``=a`` keeps A, ``=b`` takes B's raw text, ``=ocr`` the OCR's).
"""
from __future__ import annotations

import json
import re
import subprocess
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

import typer
from typing_extensions import Annotated

app = typer.Typer(add_completion=False, help=__doc__.split("\n\n")[0])

MARKER = re.compile(r"^<<<(END )?([A-Z][A-Z0-9_-]*)>>>\s*$")
NOTE_REF = re.compile(r"\[\*(\d+)\]")
NOTE_LINE = re.compile(r"^(\*(\d+)\s+)(.*)$")
GREEK_KEY = re.compile(r"\[[Ͱ-Ͽἀ-῿]+\]")
TOKEN = re.compile(r"⟨|⟩|[^\W_]+")
NOTES_SUFFIX = "-MARGINALIA"
ROMAN = re.compile(r"^[ivxlcdm]+$")
CONTEXT = 6


def fold(tok: str) -> str:
    t = unicodedata.normalize("NFD", tok.lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return t.replace("æ", "ae").replace("œ", "oe").replace("ſ", "s")


@dataclass
class Tok:
    norm: str
    raw: str
    page: int
    start: int  # offset in the page file; -1 for synthetic tokens
    end: int
    flagged: bool = False


# ---------------------------------------------------------------- readings

def parse_blocks(text: str) -> list[tuple[str, int, int]]:
    """(name, start, end) offsets of each block's body in ``text``."""
    blocks: list[tuple[str, int, int]] = []
    name, start, pos, seen = None, 0, 0, False
    for line in text.splitlines(keepends=True):
        m = MARKER.match(line.strip())
        if m:
            seen = True
            if name is not None:
                blocks.append((name, start, pos))
            name = None if m.group(1) else m.group(2)
            start = pos + len(line)
        pos += len(line)
    if name is not None:
        blocks.append((name, start, pos))
    if not seen and text.strip():
        blocks.append(("BODY", 0, len(text)))
    return blocks


def _tokens(text: str, base: int, page: int, out: list[Tok]) -> None:
    masked = GREEK_KEY.sub(lambda m: " " * len(m.group(0)), text)
    for m in TOKEN.finditer(masked):
        s, e = m.span()
        flagged = "⟦" in masked[max(0, s - 1):s] or "⟦" in masked[max(0, s - 30):s] and "⟧" not in masked[max(0, s - 30):s]
        out.append(Tok(fold(m.group(0)), m.group(0), page, base + s, base + e, flagged))


def page_streams(text: str, page: int, skip: set[str]) -> dict[str, list[Tok]]:
    """Tokens per voice for one page, keyed notes spliced into their anchors."""
    blocks = parse_blocks(text)
    streams: dict[str, list[Tok]] = defaultdict(list)
    consumed: set[int] = set()
    for i, (name, s, e) in enumerate(blocks):
        if name in skip or i in consumed:
            continue
        if name.endswith(NOTES_SUFFIX):  # notes with no text block before them
            _tokens(text[s:e], s, page, streams[name])
            continue
        # this occurrence's notes: the first NAME-MARGINALIA block after it,
        # unless another NAME block comes first (other blocks, such as an
        # apparatus, may stand between)
        notes: dict[str, tuple[int, int]] = {}
        for j in range(i + 1, len(blocks)):
            if blocks[j][0] == name:
                break
            if blocks[j][0] == name + NOTES_SUFFIX:
                consumed.add(j)
                _, ns, ne = blocks[j]
                pos = ns
                for line in text[ns:ne].splitlines(keepends=True):
                    m = NOTE_LINE.match(line.rstrip("\n"))
                    if m:
                        notes.setdefault(m.group(2), (pos + len(m.group(1)),
                                                      pos + len(m.group(1)) + len(m.group(3))))
                    pos += len(line)
                break
        used: set[str] = set()
        out = streams[name]
        pos = s
        body = text[s:e]
        for m in NOTE_REF.finditer(body):
            _tokens(body[pos - s:m.start()], pos, page, out)
            key = m.group(1)
            out.append(Tok("⟨", "⟨", page, s + m.start(), s + m.start()))
            if key in notes:
                used.add(key)
                ns, ne = notes[key]
                _tokens(text[ns:ne], ns, page, out)
            else:
                out.append(Tok(f"?note{key}", f"[*{key}] without a note", page, -1, -1))
            out.append(Tok("⟩", "⟩", page, s + m.end(), s + m.end()))
            pos = s + m.end()
        _tokens(body[pos - s:], pos, page, out)
        for key, (ns, ne) in notes.items():
            if key not in used:
                out.append(Tok("⟨", "⟨", page, -1, -1))
                out.append(Tok(f"?unanchored{key}", f"*{key} without an anchor", page, -1, -1))
                _tokens(text[ns:ne], ns, page, out)
                out.append(Tok("⟩", "⟩", page, -1, -1))
    return streams


def reading_streams(pages_dir: Path, first: int, last: int, skip: set[str],
                    pattern: str = "pg-{n:03d}.md") -> tuple[dict[str, list[Tok]], list[int], dict[int, str]]:
    streams: dict[str, list[Tok]] = defaultdict(list)
    missing = []
    texts: dict[int, str] = {}
    for n in range(first, last + 1):
        p = pages_dir / pattern.format(n=n)
        if not p.exists():
            missing.append(n)
            continue
        texts[n] = p.read_text(encoding="utf-8")
        for voice, toks in page_streams(texts[n], n, skip).items():
            streams[voice].extend(toks)
    return streams, missing, texts


# --------------------------------------------------------------------- OCR

WORD_XML = re.compile(r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">([^<]*)</word>')


@dataclass
class OcrTok:
    norm: str
    raw: str
    page: int
    box: tuple[float, float, float, float]


def parse_bbox_xml(xml: str, page: int) -> list[OcrTok]:
    """OCR tokens of one page, hyphenation at line ends rejoined."""
    import html
    lines: list[list[tuple[str, tuple]]] = []
    for line in re.findall(r"<line\b.*?</line>", xml, re.S):
        words = [(html.unescape(w[4]), tuple(float(x) for x in w[:4])) for w in WORD_XML.findall(line)]
        if words:
            lines.append(words)
    words: list[tuple[str, tuple]] = []
    carry = None
    for line in lines:
        line = list(line)
        if carry is not None:
            w, box = line[0]
            line[0] = (carry[0] + w, carry[1])
            carry = None
        if line[-1][0].endswith(("-", "¬")) and len(line[-1][0]) > 1:
            carry = (line[-1][0].rstrip("-¬"), line[-1][1])
            line = line[:-1]
        words.extend(line)
    if carry is not None:
        words.append(carry)
    out: list[OcrTok] = []
    for w, box in words:
        for m in TOKEN.finditer(w):
            out.append(OcrTok(fold(m.group(0)), m.group(0), page, box))
    return out


def ocr_tokens(pdf: Path, first: int, last: int) -> list[OcrTok]:
    out: list[OcrTok] = []
    for n in range(first, last + 1):
        xml = subprocess.run(["pdftotext", "-f", str(n), "-l", str(n), "-bbox-layout", str(pdf), "-"],
                             capture_output=True, text=True, check=True).stdout
        out.extend(parse_bbox_xml(xml, n))
    return out


def align_to_ocr(stream: list[Tok], ocr: list[OcrTok], chunk: int = 40) -> list[int | None]:
    """For each stream token, the index of the OCR token it equals, or None.

    The OCR layer reads the page in its own block order (columns, apparatus,
    margins), so a global alignment is meaningless. Each chunk of the stream
    is placed by voting on the offsets of its shared trigrams, then aligned
    inside that window; unplaced runs are retried as smaller chunks."""
    grams: dict[tuple, list[int]] = defaultdict(list)
    onorm = [t.norm for t in ocr]
    for k in range(len(onorm) - 2):
        grams[(onorm[k], onorm[k + 1], onorm[k + 2])].append(k)
    mapping: list[int | None] = [None] * len(stream)

    def place(lo: int, hi: int) -> None:
        seg = [t.norm for t in stream[lo:hi]]
        if len(seg) < 4:
            return
        votes: Counter = Counter()
        for k in range(len(seg) - 2):
            hits = grams.get((seg[k], seg[k + 1], seg[k + 2]), ())
            if len(hits) > 8:
                continue
            for pos in hits:
                votes[pos - k] += 1
        if not votes:
            return
        smooth = Counter({off: sum(votes.get(off + d, 0) for d in range(-3, 4)) for off in votes})
        off, n = smooth.most_common(1)[0]
        if n < 2:
            return
        w0 = max(0, off - 15)
        window = onorm[w0:off + len(seg) + 15]
        sm = SequenceMatcher(None, seg, window, autojunk=False)
        for a, b, size in sm.get_matching_blocks():
            for d in range(size):
                if mapping[lo + a + d] is None:
                    mapping[lo + a + d] = w0 + b + d
        # retry unplaced runs
        run = None
        for k in range(lo, hi + 1):
            if k < hi and mapping[k] is None:
                run = k if run is None else run
            elif run is not None:
                if k - run >= 8 and (k - run) < (hi - lo):
                    place(run, k)
                run = None

    for lo in range(0, len(stream), chunk):
        place(lo, min(len(stream), lo + chunk))
    return mapping


# ------------------------------------------------------------------- sites

def _anchor(mapping: list[int | None], i: int, step: int, limit: int = 5) -> tuple[int, int] | None:
    k = i
    for _ in range(limit):
        if k < 0 or k >= len(mapping):
            return None
        if mapping[k] is not None:
            return k, mapping[k]
        k += step
    return None


def _ocr_between(mapping, ocr, i1, i2, slack) -> tuple[list[OcrTok], list[OcrTok]] | None:
    """OCR tokens strictly between the agreeing anchors around [i1, i2), and
    the anchors themselves (for the bbox)."""
    left = _anchor(mapping, i1 - 1, -1)
    right = _anchor(mapping, i2, +1)
    if not left or not right:
        return None
    (lk, lo), (rk, ro) = left, right
    gap = ro - lo - 1
    if gap < 0 or gap > (rk - lk - 1) + slack:
        return None
    return ocr[lo + 1:ro], [ocr[lo], ocr[ro]]


def _box(toks: list[OcrTok]) -> dict | None:
    if not toks:
        return None
    page = Counter(t.page for t in toks).most_common(1)[0][0]
    bs = [t.box for t in toks if t.page == page]
    return {"page": page, "x0": min(b[0] for b in bs), "y0": min(b[1] for b in bs),
            "x1": max(b[2] for b in bs), "y1": max(b[3] for b in bs)}


def _raw(toks) -> str:
    return " ".join(t.raw for t in toks)


def _span(toks: list[Tok], texts: dict[int, str] | None = None) -> dict | None:
    real = [t for t in toks if t.start >= 0]
    if not real:
        return None
    if len({t.page for t in real}) > 1:
        return {"page": real[0].page, "start": real[0].start, "end": real[0].end, "multi_page": True}
    start, end = min(t.start for t in real), max(t.end for t in real)
    if texts and real[0].page in texts:
        start, end = _flag_bounds(texts[real[0].page], start, end)
    return {"page": real[0].page, "start": start, "end": end}


def _slice(toks: list[Tok], texts: dict[int, str] | None) -> str | None:
    """The span's exact text in its page file, punctuation and markup
    included; None when it is not one contiguous run (a note spliced from
    the margin, or a site across pages): such a site is edited by hand."""
    if not toks or texts is None:
        return "" if not toks else None
    if any(t.start < 0 or t.norm in ("⟨", "⟩") for t in toks) or len({t.page for t in toks}) > 1:
        return None
    text = texts.get(toks[0].page)
    if text is None:
        return None
    for x, y in zip(toks, toks[1:]):
        if y.start < x.end or "\n\n" in text[x.end:y.start] or "[*" in text[x.end:y.start]:
            return None
    start, end = _flag_bounds(text, toks[0].start, toks[-1].end)
    return text[start:end]


def _flag_bounds(text: str, start: int, end: int) -> tuple[int, int]:
    """Widen a span to a doubt flag ``⟦…?⟧`` enclosing it, so that a decision
    replaces the flag with the reading."""
    o = text.rfind("⟦", max(0, start - 60), start + 1)
    if o < 0 or "⟧" in text[o:start]:
        return start, end
    c = text.find("⟧", end - 1, end + 60)
    if c < 0 or "⟦" in text[end:c]:
        return start, end
    return o, c + 1


def collate_voice(voice: str, a: list[Tok], b: list[Tok], ocr: list[OcrTok],
                  lexicon: Counter | None, texts_a: dict[int, str] | None = None,
                  texts_b: dict[int, str] | None = None) -> list[dict]:
    amap = align_to_ocr(a, ocr) if ocr else [None] * len(a)
    sm = SequenceMatcher(None, [t.norm for t in a], [t.norm for t in b], autojunk=False)
    sites: list[dict] = []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            if lexicon is not None and ocr:
                sites.extend(_ocr_only(voice, a, amap, ocr, i1, i2, lexicon))
            sites.extend(_flags(voice, a, b, amap, ocr, i1, i2, j1, texts_a))
            continue
        sa, sb = a[i1:i2], b[j1:j2]
        found = _ocr_between(amap, ocr, i1, i2, slack=(j2 - j1) + 4) if ocr else None
        site = {
            "kind": "a-b", "voice": voice,
            "a": _raw(sa), "b": _raw(sb),
            "a_text": _slice(sa, texts_a), "b_text": _slice(sb, texts_b),
            "before": _raw(a[max(0, i1 - CONTEXT):i1]), "after": _raw(a[i2:i2 + CONTEXT]),
            "a_span": _span(sa, texts_a) or _insertion_point(a, i1),
            "pages": sorted({t.page for t in sa + sb}) or [a[min(i1, len(a) - 1)].page],
            "flagged": any(t.flagged for t in sa + sb),
            "size": max(i2 - i1, j2 - j1),
        }
        if found is None:
            site["ocr"], site["ocr_agrees"], site["bbox"] = None, "unknown", None
        else:
            between, anchors = found
            o = [t.norm for t in between]
            site["ocr"] = _raw(between)
            site["ocr_agrees"] = ("a" if o == [t.norm for t in sa] else
                                  "b" if o == [t.norm for t in sb] else "neither")
            site["bbox"] = _box(between + anchors)
        sites.append(site)
    return sites


def _flags(voice, a, b, amap, ocr, i1, i2, j1, texts_a) -> list[dict]:
    """A doubt flag on a word both readings agree on is still a doubt."""
    out = []
    k = i1
    while k < i2:
        if not a[k].flagged:
            k += 1
            continue
        start = k
        while k < i2 and a[k].flagged:
            k += 1
        sa = a[start:k]
        found = _ocr_between(amap, ocr, start, k, slack=2) if ocr else None
        out.append({
            "kind": "flag", "voice": voice, "a": _raw(sa), "b": _raw(b[j1 + start - i1:j1 + k - i1]),
            "a_text": _slice(sa, texts_a), "b_text": None,
            "before": _raw(a[max(0, start - CONTEXT):start]), "after": _raw(a[k:k + CONTEXT]),
            "a_span": _span(sa, texts_a), "pages": sorted({t.page for t in sa}),
            "flagged": True, "size": k - start,
            "ocr": _raw(found[0]) if found else None, "ocr_agrees": "unknown",
            "bbox": _box(found[0] + found[1]) if found else None,
        })
    return out


def _insertion_point(a: list[Tok], i: int) -> dict | None:
    """Where an insertion goes in A: just after the token before the site."""
    for k in range(i - 1, -1, -1):
        if a[k].start >= 0:
            return {"page": a[k].page, "start": a[k].end, "end": a[k].end, "insert": True}
    return None


def _ocr_only(voice, a, amap, ocr, i1, i2, lexicon) -> list[dict]:
    out = []
    k = i1
    while k < i2:
        if amap[k] is not None or a[k].norm in ("⟨", "⟩"):
            k += 1
            continue
        start = k
        while k < i2 and amap[k] is None and k - start < 4:
            k += 1
        found = _ocr_between(amap, ocr, start, k, slack=2)
        if not found:
            continue
        between, anchors = found
        if not between:
            continue
        ours = [t.norm for t in a[start:k]]
        theirs = [t.norm for t in between]
        if ours == theirs or "".join(ours) == "".join(theirs):
            continue
        ocr_known = all(lexicon.get(t, 0) >= 3 for t in theirs if not t.isdigit())
        ours_known = all(lexicon.get(t, 0) >= 2 for t in ours if not t.isdigit())
        if not ocr_known or (ours_known and len(theirs) != len(ours)):
            continue
        if all(len(t) <= 2 or ROMAN.match(t) or t.isdigit() for t in ours + theirs):
            continue  # numerals and fragments: the OCR's weakest ground
        out.append({
            "kind": "ocr-only", "voice": voice, "a": _raw(a[start:k]), "b": _raw(a[start:k]),
            "ocr": _raw(between), "ocr_agrees": "neither",
            "before": _raw(a[max(0, start - CONTEXT):start]), "after": _raw(a[k:k + CONTEXT]),
            "a_span": _span(a[start:k]), "pages": sorted({t.page for t in a[start:k]}),
            "flagged": False, "size": k - start, "ours_known": ours_known,
            "bbox": _box(between + anchors),
        })
    return out


@app.command()
def sites(
    a_dir: Annotated[Path, typer.Argument(help="Witness A: the reading that decisions are applied to")],
    b_dir: Annotated[Path, typer.Argument(help="Witness B: an independent reading")],
    range_: Annotated[str, typer.Option("--range", help="first-last page numbers")],
    out: Annotated[Path, typer.Option(help="sites JSONL")],
    pdf: Annotated[Path, typer.Option(help="The scan, for its OCR layer and bboxes")] = None,
    skip: Annotated[list[str], typer.Option(help="Block names not collated (unpublished layers)")] = None,
    lexicon: Annotated[Path, typer.Option(help="Lexicon JSON (exscriptor.lexicon) for ocr-only sites")] = None,
    pattern: Annotated[str, typer.Option(help="Page filename pattern")] = "pg-{n:03d}.md",
) -> None:
    """Collate A and B (and the OCR layer) into a sites file."""
    first, last = (int(x) for x in range_.split("-"))
    skipset = set(skip or ())
    sa, miss_a, ta = reading_streams(a_dir, first, last, skipset, pattern)
    sb, miss_b, tb = reading_streams(b_dir, first, last, skipset, pattern)
    if miss_a or miss_b:
        typer.echo(f"REFUSED: missing pages A={miss_a} B={miss_b}")
        raise typer.Exit(1)
    ocr = ocr_tokens(pdf, first, last) if pdf else []
    lex = None
    if lexicon:
        from exscriptor.lexicon import load
        lex = load(lexicon)
    rows: list[dict] = []
    for voice in sorted(set(sa) | set(sb)):
        rows.extend(collate_voice(voice, sa.get(voice, []), sb.get(voice, []), ocr, lex, ta, tb))
    for n, r in enumerate(rows, 1):
        r["id"] = f"s{n:04d}"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    c = Counter((r["kind"], r["ocr_agrees"]) for r in rows)
    typer.echo(f"{out}: {len(rows)} sites")
    for (kind, agrees), n in sorted(c.items()):
        typer.echo(f"  {kind:9} ocr={agrees:8} {n}")


def load_sites(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


@app.command()
def crop(
    sites_path: Annotated[Path, typer.Argument(help="sites JSONL")],
    pdf: Annotated[Path, typer.Option(help="The scan")],
    out_dir: Annotated[Path, typer.Option(help="Where crops go (<id>.png)")],
    dpi: Annotated[int, typer.Option(help="Render resolution")] = 500,
    pad_x: Annotated[float, typer.Option(help="Horizontal padding, points")] = 90.0,
    pad_y: Annotated[float, typer.Option(help="Vertical padding, points")] = 14.0,
    ids: Annotated[str, typer.Option(help="Comma-separated site ids (default: all with a bbox)")] = "",
    page_image: Annotated[str, typer.Option(help="Pre-rendered page pattern, e.g. 'hires/full-{n:03d}.jpg' "
                                            "(cut from it instead of re-rendering: much faster)")] = "",
    page_dpi: Annotated[int, typer.Option(help="Resolution of --page-image")] = 350,
) -> None:
    """Render one small crop per site around its OCR bbox. Keep crops small:
    a few lines, never a full page width at high dpi."""
    want = set(ids.split(",")) if ids else None
    out_dir.mkdir(parents=True, exist_ok=True)
    n = 0
    cache: dict[int, object] = {}
    for s in load_sites(sites_path):
        if (want and s["id"] not in want) or not s.get("bbox"):
            continue
        b = s["bbox"]
        x0, y0 = max(0.0, b["x0"] - pad_x), max(0.0, b["y0"] - pad_y)
        w, h = (b["x1"] - b["x0"]) + 2 * pad_x, (b["y1"] - b["y0"]) + 2 * pad_y
        if h > 120:  # anchors on different lines far apart: the bbox is not a site
            continue
        target = out_dir / s["id"]
        if page_image:
            from PIL import Image
            if b["page"] not in cache:
                cache.clear()  # pages arrive in order; keep one decoded page
                cache[b["page"]] = Image.open(page_image.format(n=b["page"]))
            k = page_dpi / 72.0
            cache[b["page"]].crop((int(x0 * k), int(y0 * k), int((x0 + w) * k), int((y0 + h) * k))) \
                .save(f"{target}.png")
            n += 1
            continue
        k = dpi / 72.0
        subprocess.run(["pdftoppm", "-r", str(dpi), "-f", str(b["page"]), "-l", str(b["page"]),
                        "-x", str(int(x0 * k)), "-y", str(int(y0 * k)), "-W", str(int(w * k)),
                        "-H", str(int(h * k)), "-png", "-singlefile", str(pdf), str(target)], check=True)
        n += 1
    typer.echo(f"{n} crops in {out_dir}")


@app.command()
def sheet(
    sites_path: Annotated[Path, typer.Argument(help="sites JSONL")],
    out: Annotated[Path, typer.Option(help="Worksheet markdown")],
    crops: Annotated[Path, typer.Option(help="Directory of <id>.png crops")] = None,
    keep_agrees: Annotated[str, typer.Option(help="ocr_agrees class treated as settled (A + OCR against B)")] = "a",
    sample: Annotated[int, typer.Option(help="Settled sites sampled into the sheet to calibrate that rule")] = 20,
    seed: Annotated[int, typer.Option(help="Sample seed")] = 1,
    ids: Annotated[str, typer.Option(help="Only these site ids (comma-separated)")] = "",
    page_images: Annotated[str, typer.Option(help="Fallback image pattern for sites without a crop, e.g. 'hires/pg-{n:03d}-*.jpg'")] = "",
) -> None:
    """Write an adjudication worksheet: every unsettled site (plus a seeded
    sample of the settled class) with both readings, the OCR's, its context
    and its crop. The adjudicator answers in a decisions TSV for ``apply``."""
    import random
    rows = load_sites(sites_path)
    want = set(ids.split(",")) if ids else None
    settled = [r for r in rows if r["kind"] == "a-b" and r["ocr_agrees"] == keep_agrees]
    picked = set(r["id"] for r in random.Random(seed).sample(settled, min(sample, len(settled))))
    todo = [r for r in rows if (want is None and (r not in settled or r["id"] in picked))
            or (want is not None and r["id"] in want)]
    lines = [f"# Adjudication sheet: {len(todo)} sites", "",
             "For each site, look at the crop (or the page image) and write one line in the",
             "decisions TSV: `id<TAB>reading<TAB>evidence`. `reading` is `=a` (A's text is",
             "what is printed), `=b` (B's), or the printed text itself written as it must",
             "stand in A's file (replacing A's text exactly, punctuation and *italics*",
             "included). `evidence`: what you saw, e.g. `crop: print reads essent`.",
             "A site marked MANUAL cannot be applied mechanically: write `MANUAL` as the",
             "reading and describe the fix in the evidence.", ""]
    for r in todo:
        manual = r.get("a_text") is None and not (r.get("a_span") or {}).get("insert")
        img = crops / f"{r['id']}.png" if crops and (crops / f"{r['id']}.png").exists() else None
        lines += [f"## {r['id']} — {r['voice']}, PDF {', '.join(map(str, r['pages']))}"
                  + (" — CALIBRATION" if r["id"] in picked else "") + (" — MANUAL" if manual else ""), "",
                  f"- context: … {r['before']} ⟦…⟧ {r['after']} …",
                  f"- A: `{r.get('a_text') if r.get('a_text') is not None else r['a']}`",
                  f"- B: `{r.get('b_text') if r.get('b_text') is not None else r['b']}`",
                  f"- OCR: `{r['ocr']}` (agrees: {r['ocr_agrees']})" + (f"; kind: {r['kind']}" if r['kind'] != 'a-b' else ""),
                  f"- image: {img if img else (page_images.format(n=r['pages'][0]) if page_images else 'none')}", ""]
    out.write_text("\n".join(lines), encoding="utf-8")
    typer.echo(f"{out}: {len(todo)} sites ({len(picked & {r['id'] for r in todo})} calibration)")


def read_decisions(path: Path) -> dict[str, tuple[str, str]]:
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 3 or not parts[2].strip():
            raise ValueError(f"decision without evidence: {line!r}")
        out[parts[0]] = (parts[1], parts[2])
    return out


def plan_edits(site_rows: list[dict], decisions: dict[str, tuple[str, str]]) -> tuple[dict[int, list], list[str]]:
    """Per page, (start, end, new text, id) edits on witness A; and errors."""
    by_id = {s["id"]: s for s in site_rows}
    edits: dict[int, list] = defaultdict(list)
    errors: list[str] = []
    for sid, (reading, _evidence) in decisions.items():
        s = by_id.get(sid)
        if s is None:
            errors.append(f"{sid}: no such site")
            continue
        if reading == "=a":
            continue
        if reading == "MANUAL":
            errors.append(f"{sid}: MANUAL; fix the page file by hand, then mark it =a")
            continue
        span = s.get("a_span")
        if s.get("a_text") is None and not (span or {}).get("insert"):
            errors.append(f"{sid}: A's span is not one contiguous run; edit the page file by hand")
            continue
        if not span or span.get("multi_page"):
            errors.append(f"{sid}: no single-page span in A; edit the page file by hand")
            continue
        if reading == "=b" and s.get("b_text") is None:
            errors.append(f"{sid}: B's reading is not one contiguous run; write it out")
            continue
        text = {"=b": s.get("b_text"), "=ocr": s["ocr"]}.get(reading, reading)
        if text is None:
            errors.append(f"{sid}: {reading} has no text")
            continue
        if span.get("insert"):
            text = " " + text
        edits[span["page"]].append((span["start"], span["end"], text, sid))
    for page, es in edits.items():
        es.sort()
        for (s1, e1, _, id1), (s2, e2, _, id2) in zip(es, es[1:]):
            if s2 < e1:
                errors.append(f"{id1} and {id2} overlap on page {page}")
    return edits, errors


@app.command()
def apply(
    sites_path: Annotated[Path, typer.Argument(help="sites JSONL (from the same A files)")],
    decisions_path: Annotated[Path, typer.Argument(help="id<TAB>reading<TAB>evidence")],
    a_dir: Annotated[Path, typer.Argument(help="Witness A's page directory")],
    pattern: Annotated[str, typer.Option(help="Page filename pattern")] = "pg-{n:03d}.md",
    dry_run: Annotated[bool, typer.Option(help="Print the edits only")] = False,
) -> None:
    """Write decided readings into A's page files. Refuses on any error, and
    refuses if a page changed since the sites were computed (the span text
    must still be what the site says)."""
    rows = load_sites(sites_path)
    edits, errors = plan_edits(rows, read_decisions(decisions_path))
    by_id = {s["id"]: s for s in rows}
    texts = {}
    for page, es in edits.items():
        p = a_dir / pattern.format(n=page)
        texts[page] = p.read_text(encoding="utf-8")
        for s, e, _, sid in es:
            if not by_id[sid]["a_span"].get("insert") and texts[page][s:e] != by_id[sid]["a_text"]:
                errors.append(f"{sid}: page {page} no longer has {by_id[sid]['a_text']!r} at the span")
    if errors:
        typer.echo("REFUSED:\n  " + "\n  ".join(errors))
        raise typer.Exit(1)
    n = 0
    for page, es in sorted(edits.items()):
        t = texts[page]
        for s, e, new, sid in sorted(es, reverse=True):
            typer.echo(f"pg {page} {sid}: {t[s:e]!r} -> {new.strip()!r}")
            t = t[:s] + new + t[e:]
            n += 1
        if not dry_run:
            (a_dir / pattern.format(n=page)).write_text(t, encoding="utf-8")
    typer.echo(f"{'would apply' if dry_run else 'applied'} {n} edit(s) on {len(edits)} page(s)")


if __name__ == "__main__":
    app()
