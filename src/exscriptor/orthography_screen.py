#!/usr/bin/env python3
"""Orthography screen for a normalized (edition-layer) Latin text.

An edition layer that has been "normalized" can still carry the print's own
letterforms: a scribal abbreviation mark (``nõ``, ``cõcursum``, ``ꝓ``, ``q;``
written as ``ꝗ``), a long s, a ligature glyph, an ampersand, a consonantal
``j``, a print accent, a vowel-value ``V`` in a capitals heading
(``PROBATVR``). Each of these reads acceptably to a model and to a hurried
eye, survives every count-based gate, and goes live. This screen names them.

Categories (all fail unless allow-listed):

* ``abbrev-mark`` -- unexpanded abbreviation marks: vowels carrying a tilde or
  macron (the nasal bar = omitted m/n), the medieval abbreviation letters of
  Unicode's Latin Extended-D block (ꝯ ꝰ ꝓ ꝑ ꝙ ꝗ ꝝ ꝫ ...), the Tironian et
  (⁊), e caudata (ę = ae), and combining abbreviation marks.
* ``long-s`` -- ſ.
* ``ligature`` -- æ œ and typographic ligature code points (ﬁ ﬂ ...).
* ``ampersand`` -- ``&``.
* ``consonantal-j`` -- any word with ``j``/``J``.
* ``accent`` -- grave/acute/circumflex on a vowel. Diaeresis is NOT flagged
  (``aër``, ``coöperatio`` are genuine and kept).
* ``caps-v`` -- vowel-value V in an all-capitals word (``PROBATVR``,
  ``QVOD``); Roman numerals are skipped.
* ``qv`` -- vowel-value ``v`` after ``q`` in lower case (``neqve``).

``ñ`` is reported separately as LOW (proper names such as *Peña*), never as a
failure. Allow-list tokens with ``--allow`` / ``--allow-file`` (e.g. an
accented author siglum the edition uses).

Inputs: Markdown/text files, or corpus-import manifests (``--manifest``),
whose Latin texts AND section titles are screened -- titles are metadata and
bypass every body-text gate.

Usage:

    ex-screen-orthography 'assembled/*.la.md'
    ex-screen-orthography --manifest manifests/work-v3.json --language la

Exits 1 when any failing hit is found. Work-agnostic.
"""
from __future__ import annotations

import glob as globmod
import json
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path

import typer
from typing_extensions import Annotated

COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
LINK_TARGET_RE = re.compile(r"\|[^\]|]*\]\]")  # right side of [[display|target]]
URL_RE = re.compile(r"https?://\S+")
WORD_RE = re.compile(r"[^\W\d_]+")
ROMAN_RE = re.compile(r"^[IVXLCDM]+$")

TIRONIAN_ET = "⁊"
E_CAUDATA = "ęĘ"
LIGATURE_CHARS = "æœÆŒ" + "".join(chr(c) for c in range(0xFB00, 0xFB07))
# Combining marks a scribe/printer uses for abbreviation: tilde, macron,
# overline, the combining superscript letters (U+0363..U+036F), and the
# medieval combining abbreviation marks (U+1DD3..U+1DF4 range is letters;
# U+1DE7..U+1DF4 included through the general rule below).
ABBREV_COMBINING = {0x0303, 0x0304, 0x0305, 0x033E} | set(range(0x0363, 0x0370))
ACCENT_COMBINING = {0x0300, 0x0301, 0x0302}  # grave, acute, circumflex
DIAERESIS = 0x0308
VOWELS = set("aeiouyAEIOUY")


def _decompose(ch: str) -> tuple[str, set[int]]:
    """Base letter and the set of combining code points of one character."""
    d = unicodedata.normalize("NFD", ch)
    return d[0], {ord(c) for c in d[1:]}


def char_category(ch: str) -> str | None:
    """Failing category of a single character, or None."""
    cp = ord(ch)
    if ch == "ſ":
        return "long-s"
    if ch in LIGATURE_CHARS:
        return "ligature"
    if ch == "&":
        return "ampersand"
    if ch == TIRONIAN_ET or ch in E_CAUDATA or 0xA730 <= cp <= 0xA7FF:
        return "abbrev-mark"
    if cp in ABBREV_COMBINING or 0x1DD3 <= cp <= 0x1DFF:
        return "abbrev-mark"
    if ch in "ñÑ":
        return None  # reported as LOW by the caller
    base, marks = _decompose(ch)
    if not marks:
        return None
    if marks & {0x0303, 0x0304, 0x0305}:
        return "abbrev-mark"
    if base in VOWELS and marks & ACCENT_COMBINING:
        return "accent"
    if base in "dDhHlLbB" and unicodedata.name(ch, "").find("STROKE") >= 0:
        return "abbrev-mark"
    return None


EDITORIAL_NOTE_RE = re.compile(r"^(?:\d+\.\s*)?(?:Editor['’]s note|Editorial note)", re.I)


def drop_editorial_notes(text: str) -> str:
    """Remove ``^[...]`` footnotes that are the editor's own apparatus (written
    in the editor's language, not the edition's), bracket-balanced."""
    out, i = [], 0
    while True:
        j = text.find("^[", i)
        if j < 0:
            out.append(text[i:])
            return "".join(out)
        depth, k = 0, j + 1
        while k < len(text):
            if text[k] == "[":
                depth += 1
            elif text[k] == "]":
                depth -= 1
                if depth == 0:
                    break
            k += 1
        body = text[j + 2:k]
        out.append(text[i:j])
        if not EDITORIAL_NOTE_RE.match(body.strip()):
            out.append(text[j:k + 1])
        i = k + 1


def _strip(text: str) -> str:
    text = drop_editorial_notes(text)
    text = COMMENT_RE.sub(" ", text)
    text = LINK_TARGET_RE.sub("]]", text)
    return URL_RE.sub(" ", text)


def screen_text(text: str, allow: set[str] | None = None) -> dict[str, Counter]:
    """Map category -> Counter of offending tokens (``low-enye`` is LOW)."""
    allow = allow or set()
    out: dict[str, Counter] = {}
    clean = _strip(text)

    def hit(cat: str, token: str) -> None:
        if token in allow:
            return
        out.setdefault(cat, Counter())[token] += 1

    for m in re.finditer(r"\S+", clean):
        raw = m.group(0)
        token = raw.strip(".,;:!?()[]«»\"'*_^")
        if not token or token in allow:
            continue
        cats = {c for c in (char_category(ch) for ch in token) if c}
        for cat in cats:
            hit(cat, token)
        if "ñ" in token or "Ñ" in token:
            hit("low-enye", token)
    for word in WORD_RE.findall(clean):
        if word in allow:
            continue
        if "j" in word or "J" in word:
            hit("consonantal-j", word)
        if len(word) >= 3 and word.isupper() and not ROMAN_RE.match(word):
            if re.search(r"QV|V(?=[^AEIOUY])|V$", word):
                hit("caps-v", word)
        if re.search(r"[qQ]v", word):
            hit("qv", word)
    return out


def failing(result: dict[str, Counter]) -> dict[str, Counter]:
    return {k: v for k, v in result.items() if not k.startswith("low-")}


def manifest_units(manifest: dict, language: str = "la", titles: bool | None = None):
    """Yield (label, text) for every text in ``language`` found anywhere in a
    corpus-import manifest, plus section titles. ``titles=None`` (auto)
    screens a work's titles when it declares ``original_language`` equal to
    ``language``, or -- when it declares none (append/metadata manifests) --
    when the manifest carries texts in ``language``. Pass True to force titles
    for a titles-only Latin manifest, False to skip them."""
    root = manifest.get("manifest", manifest) if isinstance(manifest, dict) else manifest

    def has_language_text(node) -> bool:
        if isinstance(node, dict):
            t = node.get("texts")
            if isinstance(t, list) and any(isinstance(x, dict) and x.get("language") == language for x in t):
                return True
            if isinstance(t, dict) and language in t:
                return True
            return any(has_language_text(v) for k, v in node.items() if k != "texts")
        if isinstance(node, list):
            return any(has_language_text(v) for v in node)
        return False

    auto_titles = has_language_text(root) if titles is None else titles

    def walk(node, key_hint="", work_lang=None):
        if isinstance(node, dict):
            work_lang = node.get("original_language", work_lang)
            key = node.get("section_key") or node.get("slug") or key_hint
            if "section_key" in node and isinstance(node.get("title"), str) \
                    and (work_lang == language if work_lang and titles is None
                         else auto_titles):
                yield f"title:{key}", node["title"]
            texts = node.get("texts")
            if isinstance(texts, list):
                for t in texts:
                    if isinstance(t, dict) and t.get("language") == language \
                            and isinstance(t.get("content"), str):
                        yield f"text:{key}", t["content"]
            elif isinstance(texts, dict):
                t = texts.get(language)
                if isinstance(t, dict) and isinstance(t.get("content"), str):
                    yield f"text:{key}", t["content"]
                elif isinstance(t, str):
                    yield f"text:{key}", t
            for k, v in node.items():
                if k != "texts":
                    yield from walk(v, key, work_lang)
        elif isinstance(node, list):
            for v in node:
                yield from walk(v, key_hint, work_lang)

    yield from walk(root)


def _expand_paths(patterns: list[str]) -> list[Path]:
    paths: list[Path] = []
    for pattern in patterns:
        expanded = globmod.glob(pattern, recursive=True) or [pattern]
        for item in expanded:
            p = Path(item)
            if p.is_dir():
                paths.extend(sorted(p.glob("*.md")) + sorted(p.glob("*.txt")))
            elif p.exists():
                paths.append(p)
    return paths


def main(
    files: Annotated[list[str], typer.Argument(help="Files, directories or globs of edition text")] = None,
    manifest: Annotated[list[Path], typer.Option(help="Corpus-import manifest JSON (repeatable)")] = None,
    language: Annotated[str, typer.Option(help="Manifest text language to screen")] = "la",
    titles: Annotated[bool | None, typer.Option("--titles/--no-titles", help="Screen section titles (default: auto)")] = None,
    allow: Annotated[list[str], typer.Option(help="Token to allow (repeatable)")] = None,
    allow_file: Annotated[Path | None, typer.Option(help="File of allowed tokens, one per line")] = None,
    examples: Annotated[int, typer.Option(help="Example tokens shown per category")] = 8,
):
    """Fail on print letterforms left in a normalized Latin text."""
    allowed = set(allow or [])
    if allow_file:
        allowed |= {ln.strip() for ln in allow_file.read_text().splitlines() if ln.strip()}
    units: list[tuple[str, str]] = []
    for p in _expand_paths(files or []):
        units.append((str(p), p.read_text(encoding="utf-8")))
    for mpath in manifest or []:
        data = json.loads(mpath.read_text(encoding="utf-8"))
        units.extend((f"{mpath.name}:{label}", text) for label, text in manifest_units(data, language, titles))
    if not files and not manifest:
        raise typer.BadParameter("nothing to screen: give files and/or --manifest")
    if not units:
        print(f"0 units in language {language!r}: nothing to screen")
        return
    totals: dict[str, Counter] = {}
    bad_units = 0
    for label, text in units:
        res = screen_text(text, allowed)
        if failing(res):
            bad_units += 1
        for cat, counter in res.items():
            totals.setdefault(cat, Counter()).update(counter)
    for cat in sorted(totals):
        c = totals[cat]
        band = "low " if cat.startswith("low-") else "FAIL"
        ex = ", ".join(f"{t}×{n}" for t, n in c.most_common(examples))
        print(f"  {band} {cat:14s} {sum(c.values()):6d} tokens {len(c):5d} forms  e.g. {ex}")
    print(f"{len(units)} units screened, {bad_units} failing")
    if any(not k.startswith("low-") for k in totals):
        sys.exit(1)


app = typer.Typer()
app.command()(main)


if __name__ == "__main__":
    app()
