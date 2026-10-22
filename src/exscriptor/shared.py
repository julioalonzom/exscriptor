#!/usr/bin/env python3
"""Errors two transcriptions share, found against the print's own OCR.

Why: two digital witnesses that descend from one OCR (a cleaned file and the
OCR it was cleaned from) agree on that OCR's errors, so collating them with
each other cannot see those errors. A fresh OCR of the print is a third voice
that knows no Latin: wherever the edition text and it disagree on one word,
and the OCR's word is a common corpus form, the print may say something the
edition does not. On one real early print this found ~6 wrong words per
section-sized unit that the two-witness collation had passed.

The screen proposes; the print decides. Every site goes to a reader with a
crop of the printed lines, and every proposed change is checked by eye on a
labelled sheet before it becomes a rule.

Inputs:

- the edition text, one file per unit (``^[...]`` notes are ignored);
- the print's OCR as JSON ``{key: text}`` whose sorted keys are reading
  order (one key per column for a two-column print: a whole-leaf read
  interleaves the columns); ``ocr`` writes one with macOS Vision;
- a lexicon (``exscriptor.lexicon``) built WITHOUT the work under screen.

Usage:

    python3 -m exscriptor.shared ocr cols/*.jpg --out ocr.json --lines lines.json [--columns 2]
    python3 -m exscriptor.shared sites la/d01.md ... --ocr ocr.json --lexicon lex.json --out sites.jsonl
    python3 -m exscriptor.shared crop sites.jsonl --lines lines.json --image 'leaves/{leaf}.jpg' --out-dir crops/
    python3 -m exscriptor.shared packets sites.jsonl --out-dir packets/
    python3 -m exscriptor.shared sheets sites.jsonl --verdicts 'verdicts/*.tsv' --out sheets/sh
    python3 -m exscriptor.shared rules sites.jsonl eye.tsv --text-dir la/ > rules.tsv

``sites`` keeps a one-for-one substitution when the OCR's word is a corpus
form (``--min-freq``) and the pair is not a known OCR confusion or spelling
difference; then every site whose own word is not a corpus form, and of the
rest only pairs that occur once in the run (a pair that recurs is the OCR's
habit), that are not truncations, and whose OCR word is common
(``--common``). ``rules`` turns eye verdicts (``site<TAB>word`` or
``site<TAB>KEEP``) into ``unit<TAB>old<TAB>new<TAB>site`` with a window
grown until it is unique in the unit.
"""
from __future__ import annotations

import bisect
import csv
import difflib
import glob as globmod
import json
import re
import unicodedata
from collections import Counter
from pathlib import Path

import typer
from typing_extensions import Annotated

app = typer.Typer(add_completion=False, help=__doc__.split("\n\n")[0])

LIG = str.maketrans({"ſ": "s", "æ": "ae", "Æ": "ae", "œ": "oe", "Œ": "oe", "ę": "ae", "&": "et"})
NOTE = re.compile(r"\^\[(?:[^\[\]]|\[[^\]]*\])*\]")
# letters an early roman type and an OCR engine confuse: a pair that differs
# only in these is the OCR's misreading, not the edition's
CONFUSIONS = [("rn", "m"), ("cl", "d"), ("li", "h"), ("c", "e"), ("u", "n"), ("i", "l"), ("t", "r"), ("c", "t")]
IMAGE_EXT = re.compile(r"\.(jpe?g|png|tiff?)$", re.I)


def norm(w: str) -> str:
    """Fold for comparison: case, accents, ligatures, u/v, i/j, and long s
    (an OCR reads ``ſ`` as ``f``, so ``f`` folds to ``s`` on both sides)."""
    w = unicodedata.normalize("NFKD", w.translate(LIG).lower())
    w = "".join(c for c in w if c.isalpha())
    return w.replace("v", "u").replace("j", "i").replace("f", "s")


def _confusable(a: str, b: str) -> bool:
    for x, y in CONFUSIONS:
        a, b = a.replace(x, y), b.replace(x, y)
    return a == b


def _modern(w: str) -> str:
    """The edition's spelling against an early print's: m before q/d
    (quamvis, eamdem), xs, immo, -cumque; a final vowel the OCR reads for ę."""
    w = re.sub(r"m(?=[qd])", "n", w).replace("xs", "x").replace("immo", "imo").replace("cumque", "cunque")
    return re.sub(r"(ae|a|e)$", "", w)


def _spelling_only(a: str, b: str) -> bool:
    strip = lambda w: re.sub(r"[mn]$", "", w.replace("ae", "e"))  # a final nasal is a tilde the OCR drops
    return strip(a) == strip(b) or _modern(a) == _modern(b)


def _tilde_drop(a: str, b: str) -> bool:
    """``b`` is ``a`` without one nasal after a vowel (that vowel may read
    otherwise): the print may set the nasal as a tilde (pertinēt, indiuiduū)
    that the OCR, and a reader, drop. Only an eye on a close crop settles it."""
    a, b = norm(a), norm(b)
    return len(b) == len(a) - 1 and any(
        a[i] in "mn" and a[i - 1] in "aeiou" and b[:i - 1] == a[:i - 1] and b[i:] == a[i + 1:]
        for i in range(1, len(a)))


def _distance(a: str, b: str) -> int:
    row = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        prev, row[0] = row[0], i
        for j, cb in enumerate(b, 1):
            prev, row[j] = row[j], min(row[j] + 1, row[j - 1] + 1, prev + (ca != cb))
    return row[-1]


def load_ocr(path: Path) -> dict[str, str]:
    """``{key: text}`` (or ``{key: [[text, x, y, w, h], ...]}``), keys without
    an image extension."""
    data = json.loads(path.read_text(encoding="utf-8"))
    return {IMAGE_EXT.sub("", k): (v if isinstance(v, str) else "\n".join(l[0] for l in v))
            for k, v in data.items()}


def ocr_stream(ocr: dict[str, str]) -> tuple[list[str], list[str]]:
    words, keys = [], []
    for k in sorted(ocr):
        for w in ocr[k].split():
            t = norm(w)
            if t:
                words.append(t)
                keys.append(k)
    return words, keys


def anchors(base: list[str], stream: list[str], grams: dict | None = None) -> list[tuple[int, int]]:
    """Monotone anchors: 4-grams unique in both, longest increasing run."""
    if grams is None:
        grams = {}
        for i in range(len(stream) - 3):
            grams.setdefault(tuple(stream[i:i + 4]), []).append(i)
    bg: dict[tuple, list[int]] = {}
    for i in range(len(base) - 3):
        bg.setdefault(tuple(base[i:i + 4]), []).append(i)
    pairs = sorted((v[0], grams[g][0]) for g, v in bg.items()
                   if len(v) == 1 and len(grams.get(g, ())) == 1 and len(set(g)) > 2)
    tails: list[int] = []
    idx: list[int] = []
    prev = [-1] * len(pairs)
    for k, (_, o) in enumerate(pairs):
        j = bisect.bisect_left(tails, o)
        if j == len(tails):
            tails.append(o)
            idx.append(k)
        else:
            tails[j] = o
            idx[j] = k
        prev[k] = idx[j - 1] if j else -1
    out, k = [], idx[-1] if idx else -1
    while k >= 0:
        out.append(pairs[k])
        k = prev[k]
    return out[::-1]


def screen(unit: str, text: str, stream: list[str], keys: list[str], lex: Counter,
           min_freq: int = 50, grams: dict | None = None) -> list[dict]:
    """Every one-for-one substitution between ``text`` and the OCR stream that
    the OCR's lexicon form and a matched frame make worth a look."""
    raw = [w for w in NOTE.sub(" ", text).split() if norm(w)]
    base = [norm(w) for w in raw]
    out = []
    anc = anchors(base, stream, grams)
    for (b0, o0), (b1, o1) in zip(anc, anc[1:]):
        if b1 - b0 > 60 or o1 - o0 > 90:
            continue  # a gap the anchors do not pin
        sm = difflib.SequenceMatcher(None, base[b0:b1], stream[o0:o1], autojunk=False)
        for op, i1, i2, j1, j2 in sm.get_opcodes():
            if op != "replace" or i2 - i1 != j2 - j1:
                continue
            for k in range(i2 - i1):
                bi, oj = b0 + i1 + k, o0 + j1 + k
                a, o = base[bi], stream[oj]
                if a == o or _spelling_only(a, o) or lex.get(o, 0) < min_freq or _confusable(a, o):
                    continue
                if min(len(a), len(o)) < 3 or _distance(a, o) > max(2, len(a) // 3):
                    continue
                if not (base[bi - 1] == stream[oj - 1] and base[bi + 1] == stream[oj + 1]):
                    continue  # a reading sits in a matched frame; an OCR fragment does not
                out.append({"unit": unit, "id": f"s{bi}", "a": raw[bi], "b": o, "key": keys[oj],
                            "fa": lex.get(a, 0), "fb": lex[o],
                            "context": " ".join(raw[max(bi - 6, 0):bi]) + " […] " + " ".join(raw[bi + 1:bi + 7])})
    return out


def select(rows: list[dict], rare: int = 5, common: int = 200) -> list[dict]:
    """Every site whose own word is rare; of the rest, a pair seen once,
    not a truncation, with a common OCR word."""
    seen = Counter((norm(r["a"]), r["b"]) for r in rows)
    keep = []
    for r in rows:
        a, b = norm(r["a"]), r["b"]
        if r["fa"] >= rare and (seen[(a, b)] != 1 or a.startswith(b) or a.endswith(b) or b.startswith(a)
                                or r["fb"] < common):
            continue
        keep.append(r)
    return keep


def _load_jsonl(p: Path) -> list[dict]:
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def _write_jsonl(p: Path, rows: list[dict]) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


@app.command()
def sites(
    texts: Annotated[list[Path], typer.Argument(help="Edition text, one file per unit (unit = file stem)")],
    ocr: Annotated[Path, typer.Option(help="The print's OCR, {key: text}, sorted keys in reading order")],
    lexicon: Annotated[Path, typer.Option(help="Lexicon JSON built without this work")],
    out: Annotated[Path, typer.Option(help="sites JSONL")],
    work_dir: Annotated[Path, typer.Option(help="The work (lexicon contamination check); default: the texts' grandparent")] = None,
    min_freq: Annotated[int, typer.Option(help="The OCR's word must occur this often in the lexicon")] = 50,
    common: Annotated[int, typer.Option(help="...this often, for a site whose own word is a corpus form")] = 200,
    every: Annotated[bool, typer.Option(help="Write every candidate, unselected")] = False,
) -> None:
    """Align each unit with the print's OCR and write the sites to read."""
    from exscriptor.lexicon import contamination, default_work_dir, load
    why = contamination(lexicon, work_dir or default_work_dir(str(texts[0])))
    if why:
        typer.echo(f"REFUSED: {why}")
        raise typer.Exit(1)
    lex: Counter = Counter()
    for w, n in load(lexicon).items():
        lex[norm(w)] += n  # fold as the text is folded: divisio and diuisio are one form
    stream, keys = ocr_stream(load_ocr(ocr))
    grams: dict = {}
    for i in range(len(stream) - 3):
        grams.setdefault(tuple(stream[i:i + 4]), []).append(i)
    rows = [r for t in texts for r in screen(t.stem, t.read_text(encoding="utf-8"), stream, keys, lex, min_freq, grams)]
    picked = rows if every else select(rows, common=common)
    _write_jsonl(out, picked)
    typer.echo(f"{out}: {len(picked)} sites ({len(rows)} candidates) in {len(texts)} unit(s)")


@app.command()
def ocr(
    images: Annotated[list[Path], typer.Argument(help="Page or column images, in reading order by name")],
    out: Annotated[Path, typer.Option(help="{key: text} JSON")],
    lines: Annotated[Path, typer.Option(help="{key: [[text, x, y, w, h]]} JSON (Vision boxes: normalized, origin bottom-left)")] = None,
    columns: Annotated[int, typer.Option(help="Cut each image into this many equal columns first (keys <stem>-c1 ...)")] = 1,
    language: Annotated[str, typer.Option(help="Recognition language")] = "la",
) -> None:
    """OCR images with macOS Vision (pyobjc), no language correction."""
    try:
        import Quartz
        import Vision
        from Foundation import NSURL
        from PIL import Image
    except ImportError:
        typer.echo("REFUSED: needs macOS and the vision extra (pip install 'exscriptor[vision]', or "
                   "uv run --with-editable 'path/to/exscriptor[vision]'); "
                   "any engine writing the same JSON will do")
        raise typer.Exit(1)
    import tempfile
    texts, boxes = {}, {}
    tmp = Path(tempfile.mkdtemp())
    for img in images:
        im = Image.open(img)
        w, h = im.size
        parts = [(img.stem, img)]
        if columns > 1:
            parts = []
            for c in range(columns):
                p = tmp / f"{img.stem}-c{c + 1}.png"
                im.crop((w * c // columns, 0, w * (c + 1) // columns, h)).save(p)
                parts.append((p.stem, p))
        for key, p in parts:
            src = Quartz.CGImageSourceCreateWithURL(NSURL.fileURLWithPath_(str(p.resolve())), None)
            cg = Quartz.CGImageSourceCreateImageAtIndex(src, 0, None)
            req = Vision.VNRecognizeTextRequest.alloc().init()
            req.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
            req.setRecognitionLanguages_([language])
            req.setUsesLanguageCorrection_(False)
            Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(cg, None).performRequests_error_([req], None)
            ls = []
            for o in req.results() or []:
                bb = o.boundingBox()
                ls.append([str(o.topCandidates_(1)[0].string()), bb.origin.x, bb.origin.y, bb.size.width, bb.size.height])
            boxes[key] = ls
            texts[key] = "\n".join(l[0] for l in ls)
    out.write_text(json.dumps(texts, ensure_ascii=False), encoding="utf-8")
    if lines:
        lines.write_text(json.dumps(boxes, ensure_ascii=False), encoding="utf-8")
    typer.echo(f"{out}: {len(texts)} images")


def _cover(probe: str, txt: str) -> float:
    """How much of ``probe`` appears, in order, inside ``txt`` (0-100)."""
    m = difflib.SequenceMatcher(None, probe, txt, autojunk=False).get_matching_blocks()
    return 100.0 * sum(b.size for b in m) / max(len(probe), 1)


def locate(site: dict, boxes: dict[str, list], order: list[str]) -> tuple[str, int, int] | None:
    """(key, first line, line count) of the printed lines holding the site,
    searched in its OCR key and the two keys either side."""
    left, _, right = site["context"].partition("[…]")
    probe = " ".join(norm(w) for w in left.split()[-4:] + site["a"].split() + right.split()[:4])
    at = order.index(site["key"]) if site["key"] in order else None
    if at is None:
        return None
    best = None
    for key in [site["key"]] + order[max(at - 2, 0):at] + order[at + 1:at + 3]:
        L = boxes.get(key, [])
        for i in range(len(L)):
            for k in (1, 2, 3, 4):
                seg = L[i:i + k]
                if len(seg) < k:
                    break
                txt = " ".join(norm(w) for s in seg for w in s[0].split())
                if len(txt) < len(probe) * 0.9:
                    continue  # the probe must fit inside the lines, never the reverse
                sc = _cover(probe, txt)
                if best is None or sc > best[0] + 0.5 or (abs(sc - best[0]) <= 0.5 and k < best[3]):
                    best = (sc, key, i, k)
    return best[1:] if best and best[0] >= 60 else None


@app.command()
def crop(
    sites_path: Annotated[Path, typer.Argument(help="sites JSONL (rewritten with each site's crop)")],
    lines: Annotated[Path, typer.Option(help="{key: [[text, x, y, w, h]]} line boxes, as `ocr --lines` writes")],
    image: Annotated[str, typer.Option(help="Image to cut from: '{key}' for the OCR'd image, '{leaf}' for the "
                                            "whole leaf (key minus a -cN column suffix, same height)")],
    out_dir: Annotated[Path, typer.Option(help="Where crops go (<unit>-<id>.png)")],
    pad: Annotated[int, typer.Option(help="Lines of margin above and below")] = 1,
) -> None:
    """Cut the printed lines of each site across the image's full width: a
    reader needs the words on both sides, and a column-edge crop clips line
    starts into different words."""
    from PIL import Image
    boxes = {IMAGE_EXT.sub("", k): v for k, v in json.loads(lines.read_text(encoding="utf-8")).items()}
    order = sorted(boxes)
    rows = _load_jsonl(sites_path)
    out_dir.mkdir(parents=True, exist_ok=True)
    # a '{leaf}' image holds every column: a line's x is within its column
    ncol: dict[str, int] = {}
    for key in boxes:
        m = re.search(r"-c(\d+)$", key)
        leaf = re.sub(r"-c\d+$", "", key)
        ncol[leaf] = max(ncol.get(leaf, 1), int(m.group(1)) if m and "{leaf}" in image else 1)
    n = 0
    for r in rows:
        hit = locate(r, boxes, order)
        r["crop"] = r["zoom"] = None
        if not hit:
            continue
        key, i, k = hit
        seg = boxes[key][max(i - pad, 0): i + k + pad]
        leaf = re.sub(r"-c\d+$", "", key)
        im = Image.open(image.format(key=key, leaf=leaf))
        w, h = im.size
        ys = [1 - (s[2] + s[4]) for s in seg] + [1 - s[2] for s in seg]
        dest = out_dir / f"{r['unit']}-{r['id']}.png"
        im.crop((0, max(int(min(ys) * h) - 10, 0), w, min(int(max(ys) * h) + 10, h))).save(dest)
        r["crop"] = str(dest.resolve())
        if _tilde_drop(r["a"], r["b"]):
            m = re.search(r"-c(\d+)$", key)
            col = int(m.group(1)) - 1 if m and "{leaf}" in image else 0
            zoom = dest.with_name(f"{dest.stem}-zoom.png")
            _zoom(im, boxes[key][i:i + k], r["b"], col, ncol[leaf]).save(zoom)
            r["zoom"] = str(zoom.resolve())
        n += 1
    _write_jsonl(sites_path, rows)
    typer.echo(f"{n} crops of {len(rows)} sites in {out_dir}" + (f"; {len(rows) - n} not located" if n < len(rows) else ""))


def _zoom(im, lines: list, word: str, col: int, ncol: int, scale: int = 3):
    """``scale``x the stretch of printed line around ``word``: a tilde is a
    few pixels, lost in a full-width crop. The word's x is estimated from its
    place in the line's OCR text."""
    from PIL import Image
    w, h = im.size
    target = norm(word)
    best = (-1.0, lines[0], 0.5)
    for line in lines:
        toks = line[0].split()
        for j, tok in enumerate(toks):
            sc = _cover(target, norm(tok))
            if sc > best[0]:
                mid = len(" ".join(toks[:j])) + len(tok) / 2 + (1 if j else 0)
                best = (sc, line, mid / max(len(line[0]), 1))
    _, (_, x, y, lw, lh), frac = best
    cx, half = (col + x + lw * frac) / ncol * w, 0.15 * w / ncol
    box = (max(int(cx - half), 0), max(int((1 - y - 2 * lh) * h), 0),
           min(int(cx + half), w), min(int((1 - y + lh) * h), h))
    part = im.crop(box)
    return part.resize((part.width * scale, part.height * scale), Image.LANCZOS)


def _fold(w: str) -> str:
    w = unicodedata.normalize("NFD", w.lower())
    w = "".join(c for c in w if not unicodedata.combining(c))
    for x, y in (("v", "u"), ("j", "i"), ("y", "i"), ("ae", "e"), ("oe", "e"), ("ci", "ti"), ("h", "")):
        w = w.replace(x, y)
    return re.sub(r"[^\w\s]", "", w).strip()


@app.command()
def packets(
    sites_path: Annotated[Path, typer.Argument(help="sites JSONL with crops")],
    out_dir: Annotated[Path, typer.Option(help="Where packets go (NN.tsv)")],
    size: Annotated[int, typer.Option(help="Sites per packet")] = 25,
) -> None:
    """Reader packets, ``site left A B right crop``. Spelling-only pairs
    (u/v, i/j, ae/oe/e, y/i, ci/ti, h) are left out: house style settles
    those. Doubled letters are not folded: Summo/Sumo is a reading."""
    rows, skipped = [], 0
    for r in _load_jsonl(sites_path):
        if _fold(r["a"]) == _fold(r["b"]):
            skipped += 1
            continue
        left, _, right = r["context"].partition("[…]")
        rows.append([f"{r['unit']}:{r['id']}", " ".join(left.split()[-6:]), r["a"], r["b"],
                     " ".join(right.split()[:6]), r.get("crop") or ""])
    out_dir.mkdir(parents=True, exist_ok=True)
    for i in range(0, len(rows), size):
        with open(out_dir / f"{i // size + 1:02d}.tsv", "w", encoding="utf-8") as f:
            w = csv.writer(f, delimiter="\t", lineterminator="\n")
            w.writerow(["site", "left", "A", "B", "right", "crop"])
            w.writerows(rows[i:i + size])
    typer.echo(f"{len(rows)} sites in {-(-len(rows) // size)} packet(s); {skipped} spelling-only left out")


def read_verdicts(pattern: str) -> dict[str, list[str]]:
    """Reader verdict TSVs (``site verdict print note``), by site."""
    out = {}
    for p in sorted(globmod.glob(pattern)):
        for row in csv.reader(open(p, encoding="utf-8"), delimiter="\t"):
            if row and row[0] != "site":
                out[row[0]] = row
    return out


@app.command()
def sheets(
    sites_path: Annotated[Path, typer.Argument(help="sites JSONL with crops")],
    verdicts: Annotated[str, typer.Option(help="Glob of reader verdict TSVs")],
    out: Annotated[str, typer.Option(help="Sheet prefix (<out>-NN.png)")],
    per: Annotated[int, typer.Option(help="Crops per sheet")] = 3,
    all_sites: Annotated[bool, typer.Option("--all", help="Every site, not only those a reader would change")] = False,
) -> None:
    """Labelled contact sheets for the eye check: each crop under a banner
    ``unit:id  A > what the reader saw``. By default only the sites a reader
    did not keep as A (B, other, unclear): those are the proposed changes.
    A tilde site (``_tilde_drop``) is always shown, on its close crop: readers
    miss tildes either way."""
    from PIL import Image, ImageDraw, ImageFont
    v = read_verdicts(verdicts)
    items = []
    for r in _load_jsonl(sites_path):
        site = f"{r['unit']}:{r['id']}"
        got = v.get(site)
        tilde = _tilde_drop(r["a"], r["b"])
        if not r.get("crop") or (not all_sites and not tilde and got and got[1] == "A"):
            continue
        seen = got[2] if got and len(got) > 2 and got[2] else (got[1] if got else "?")
        items.append((f"{site}  {r['a']} > {seen}" + ("  TILDE?" if tilde else ""),
                      r.get("zoom") or r["crop"] if tilde else r["crop"]))
    try:
        font = ImageFont.truetype("Arial.ttf", 40)
    except OSError:
        font = ImageFont.load_default()
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    for n in range(0, len(items), per):
        ims = [(s, Image.open(p).convert("RGB")) for s, p in items[n:n + per]]
        W, H = max(i.width for _, i in ims), sum(i.height + 60 for _, i in ims)
        sheet = Image.new("RGB", (W, H), "white")
        d = ImageDraw.Draw(sheet)
        y = 0
        for s, i in ims:
            d.rectangle([0, y, W, y + 56], fill=(255, 230, 150))
            d.text((10, y + 4), s, fill="black", font=font)
            sheet.paste(i, (0, y + 60))
            y += i.height + 60
        sheet.save(f"{out}-{n // per + 1:02d}.png")
    typer.echo(f"{len(items)} sites on {-(-len(items) // per)} sheet(s)")


CORE = re.compile(r"^([^\w]*)(.*?)([^\w]*)$")


def window(text: str, site: dict, word: str) -> tuple[str, str] | None:
    """(old, new) for one site: the site's word with its own punctuation and
    capital replaced by ``word``, in a window of context grown until unique."""
    a = site["a"]
    pa, ca, sa = CORE.match(a).groups()
    w = CORE.match(word).group(2)
    if ca[:1].isupper():
        w = w[:1].upper() + w[1:]
    new = pa + w + sa
    left, _, right = site["context"].partition(" […] ")
    L, R = left.split(), right.split()
    for k in range(1, 7):
        for win in (" ".join(L[-k:] + [a] + R[:k]), " ".join(L[-k:] + [a]), " ".join([a] + R[:k])):
            if text.count(win) == 1 and win.count(a) == 1:
                return win, win.replace(a, new, 1)
    return None


@app.command()
def rules(
    sites_path: Annotated[Path, typer.Argument(help="sites JSONL")],
    eye: Annotated[Path, typer.Argument(help="Eye verdicts: site<TAB>word, or site<TAB>KEEP")],
    text_dir: Annotated[Path, typer.Option(help="Where <unit>.md lives (the text the rules apply to)")],
) -> None:
    """Print ``unit<TAB>old<TAB>new<TAB>site`` for each eye-verdict change;
    refuse if a site is unknown or no unique window exists."""
    by = {f"{r['unit']}:{r['id']}": r for r in _load_jsonl(sites_path)}
    bad = []
    for line in eye.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        site, word = line.split("\t")[:2]
        if word == "KEEP":
            continue
        r = by.get(site)
        if r is None:
            bad.append(f"{site}: no such site")
            continue
        got = window((text_dir / f"{r['unit']}.md").read_text(encoding="utf-8"), r, word)
        if got is None:
            bad.append(f"{site}: no unique window for {r['a']!r}")
        elif got[0] != got[1]:
            typer.echo("\t".join((r["unit"], *got, site)))
    if bad:
        typer.echo("REFUSED:\n  " + "\n  ".join(bad), err=True)
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
