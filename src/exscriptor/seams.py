#!/usr/bin/env python3
"""Paragraph-seam gate: paragraphs wrongly split or cut at a page seam.

A page-file pipeline joins pages mechanically, and the joins that go wrong
look like ordinary paragraphs to every count-based check. This module names
them.

Blocking violations (``seam_violations``; stage nothing until there are 0):

  1. LOWER-START : a non-list, non-heading paragraph starts with a lowercase
     letter (a continuation that was split off, or a miscapitalization).
  2. PAIR-SEAM   : paragraph i does not end with a sentence terminal AND the
     next paragraph (non-list) starts lowercase: one paragraph, split in two.
  3. TAIL-TERMINAL: the LAST paragraph does not end a sentence (or ends in a
     hyphen or an abbreviation such as ``etc.``): the text stops mid-sentence,
     so the next page was not transcribed or a chunk boundary cut it.
  4. NOTE-END (``note_violations``): an inline footnote body does not end
     with a terminal (or a non-Latin-script letter): the note was cut in
     half, usually a note continuing on the next page whose second half
     was parsed as body text.

Lists, structural headings, short bold title lines and colonic lead-ins
(``...las siguientes:``) are exempt; a trailing inline footnote is stripped
before the terminal check.

The strict audit (``paragraph_boundary_findings``, ``--boundary-audit``)
surfaces EVERY lowercase start and EVERY non-terminal ending, each bound to the
paragraph's sha256. A finding passes only with a disposition naming that hash
and a reason, so a disposition cannot outlive an edit to its paragraph.

Usage:

    python3 -m exscriptor.seams FILE [FILE ...]
    python3 -m exscriptor.seams --boundary-audit --dispositions d.json FILE

Dispositions JSON: ``[{"kind": "LOWER-START", "paragraph_sha256": "...",
"reason": "..."}]``. Exits 1 on any unresolved violation.
"""
from __future__ import annotations
import hashlib
import json
import re
import unicodedata
from pathlib import Path

import typer
from typing_extensions import Annotated

# A sentence may end inside emphasis or a quotation: `…Anno Domini 1585.*`.
_TERMINAL = re.compile(r"[.!?…][\s'\"”’»)\]*_]*$")
_FN = re.compile(r"\^\[[^\]]*\]\s*$")
_COLON = re.compile(r":\s*$")
_LIST = re.compile(
    # A number with an ordinal mark is a list label: masculine `1º`, feminine
    # `1ª` (Merkelbach numbers its points and sub-points `1ª est prudentia`),
    # and superscript forms handled in _first_letter.
    r"^\s*\*{0,2}(?:\d+[.)]|\d+[°ºª](?:\.|\s)|[a-z]\*{0,2}\)|[αβγδε]\*{0,2}\)|[ivxlcdm]+\)|[•\-\u2013\u2014·]\s|"
    r"(?:Primero|Segundo|Tercero|Cuarto|Quinto)\s*[:.]|"
    r"\*{1,2}\s)")
# A leading ellipsis marks a DELIBERATE mid-phrase continuation (the print's
# dot-glyph convention in Felder's intro, pp. 2-3: '…de Deo rebusque
# divinis.'), not an accidental seam split — exempt from lowercase-start.
_ELLIPSIS = re.compile(r"^\s*…")
# Superscript ordinal marks: the Latin ordinals a print writes after a figure
# — '1ᵐ', '3ⁱᵒ', '1ª', '2º', and Merkelbach's '1ᵘˢ est consiliari' (primus,
# secundus). Letters by Unicode, but list labels in prose. The modifier-letter
# blocks (U+02B0-02FF spacing modifiers, U+1D00-1DBF phonetic extensions,
# U+2070-209F super/subscripts) are all of them list marks after a digit.
_ORDINAL_MARK = re.compile(r"[ªº\u02B0-\u02FF\u1D00-\u1DBF\u2070-\u209F]")
_ENGLISH_ORDINAL = re.compile(r"^[\W_]*\d+(st|nd|rd|th)\b")
_STRUCT = re.compile(r"^\*{1,2}(?:SECCION|CAPITULO|EP[IÍ]LOGO|PR[OÓ]LOGO)", re.I)
_SHORT_BOLD = re.compile(
    r"^\*{1,2}[0-9IVXa-zA-ZÁÉÍÓÚÜÑáéíóúüñ\s.,;:\"'«»()\-\u2014\u2013]+\*{1,2}$")


def _heading(b: str) -> bool:
    return (bool(re.match(r"^\s*#{1,6}\s", b)) or bool(_STRUCT.match(b))
            or bool(b.startswith("*") and len(b) < 130
                    and (_SHORT_BOLD.match(b) or
                         (b.startswith("*") and b.endswith("*") and
                          not b.startswith("**")))))


def is_list_label(line: str) -> bool:
    """True when a block OPENS with a list label rather than with prose.

    A page file records no indents, so the print's own item start has to be
    recognised from the label: `a) opinio aliquando vocatur dubium late dictum`
    begins a real item even when the sentence before it runs on
    (`…ideo` / `a) …`), and so does `1ᵘˢ est *consiliari*`. Consumers that
    must not treat such a start as a mid-sentence line break (the hard-wrap
    screen) ask this instead of re-deriving the label set.
    """
    if _LIST.match(line):
        return True
    # Superscript ordinals (Merkelbach's '1ᵘˢ', '1ᵐ') are in _ORDINAL_MARK,
    # not in _LIST's '°ºª' class: a digit followed by one is a label.
    head = line.lstrip()[:4]
    return any(c.isdigit() for c in head) and bool(_ORDINAL_MARK.search(head))


def _first_letter(s: str) -> str:
    """First alphabetic character of a block, skipping leading quotes,
    brackets, dashes, bold markers, etc. The lowercase-start checks must
    look at the first LETTER: a block starting with '\"novam\"' is a
    lowercase start even though its first char is a quote. A superscript
    ordinal after a digit ('1ᵐ *Testimonium*', '3ⁱᵒ. Deus') is a list label,
    not a lowercase letter."""
    if _ENGLISH_ORDINAL.match(s):
        # an English list label: '1st *Testimony*', '*5th Testimony:*'
        return ""
    after_digit = False
    marked = False
    for c in s:
        if c.isdigit():
            after_digit = True
            marked = False
        elif after_digit and _ORDINAL_MARK.match(c):
            marked = True
        elif c.isalpha():
            return "" if marked else c
        elif marked and c in ".,;:*)\u2014\u2013 \t":
            return ""
        else:
            after_digit = False
            marked = False
    return ""


def _nterm(b: str) -> bool:
    strip = (_FN.sub("", b).strip() or b)
    # Latin abbreviations are not sentence terminals (e. g. / i. e. / v. g.
    # / sc. / scil. / etc.) — a block ending in one is mid-sentence. The
    # corpus spells 'e. g.' with a space between the letters.
    strip = re.sub(r"\b(?:e\. ?g\.|i\. ?e\.|v\. ?g\.|sc\.|scil\.|etc\.)\s*$", "", strip)
    if _COLON.search(strip):
        return True          # colonic lead-in is a legitimate non-terminal end
    return bool(_TERMINAL.search(strip))


_ETC_END = re.compile(r"\betc\.\s*$")


def _closes_on_etc(block: str, nxt: str | None) -> bool:
    """A paragraph that ends 'ergo etc.' and is followed by a block starting
    with a capital is complete: the author broke the paragraph there. A page
    seam cut mid-sentence continues in lower case, which stays flagged."""
    if not nxt or not _ETC_END.search(_FN.sub("", block).strip() or block):
        return False
    first = _first_letter(nxt)
    return bool(first) and first.isupper()


def _note_end_ok(body: str) -> bool:
    """A footnote body is complete when it ends in a sentence terminal
    (possibly inside emphasis/quotes), or in a non-Latin-script letter
    (Greek/Hebrew/Syriac quotations carry no terminal punctuation).
    A body ending in a comma, a conjunction or a lowercase Latin word was
    cut in half: the rest of the note was parsed as body text."""
    strip = body.strip()
    strip = re.sub(r"[\*\_»\"'’”\)\]]+$", "", strip).rstrip()
    if not strip:
        return True
    if _TERMINAL.search(strip) or strip.endswith(":") or strip.endswith(";"):
        return True
    last = strip[-1]
    while len(strip) > 1 and not last.isalpha():
        # a trailing vowel point or other combining mark belongs to the
        # letter before it (Hebrew pointings end many notes)
        if unicodedata.category(last) not in ("Mn", "Me"):
            break
        strip = strip[:-1]
        last = strip[-1]
    return last.isalpha() and not last.isascii()


_OPEN_NOTE = re.compile(r"\^\[(?:\d+\.\s*)?")


def _note_bodies(block: str):
    """Yield footnote bodies, honouring nested [...] brackets."""
    for m in _OPEN_NOTE.finditer(block):
        depth = 1
        i = m.end()
        while i < len(block) and depth:
            if block[i] == "[":
                depth += 1
            elif block[i] == "]":
                depth -= 1
            i += 1
        if depth == 0:
            yield block[m.end():i - 1]


def note_violations(text: str):
    """Flag inline footnotes whose body does not end (NOTE-END).

    Catches the classic cut-note: a note starting on one page and
    continuing on the next whose second half was parsed as body text,
    leaving the first half ending mid-sentence. Only closed notes are
    examined; unclosed ones belong to the expand layer.
    Returns [(block_index, "NOTE-END", snippet)]."""
    out = []
    blocks = [x.strip() for x in text.split("\n\n") if x.strip()]
    for i, b in enumerate(blocks):
        if _LIST.match(b) or _heading(b):
            continue
        for body in _note_bodies(b):
            if not _note_end_ok(body):
                out.append((i, "NOTE-END", f"note ends {body[-40:]!r}"))
    return out


def seam_violations(text: str):
    blocks = [x.strip() for x in text.split("\n\n")
              if x.strip() and not x.strip().startswith("^[")]
    out = []
    for i, b in enumerate(blocks):
        if not b or _LIST.match(b) or _heading(b):
            continue
        # 1) lower-start
        fl = _first_letter(b)
        if fl and fl.islower() and not _ELLIPSIS.match(b):
            out.append((i, "LOWER-START", b[:80]))
            continue
        # 2) pair-seam: this block doesn't end with a terminal, next starts lowercase
        if i + 1 < len(blocks) and not _nterm(b):
            nxt = blocks[i + 1]
            nfl = _first_letter(nxt) if nxt else ""
            if nxt and nfl and nfl.islower() and not _ELLIPSIS.match(nxt) \
                    and not _LIST.match(nxt) and not _heading(nxt):
                out.append((i, "PAIR-SEAM", f"{b[-40:]} || {nxt[:40]}"))
    # 3) tail-terminal: the last block must end a sentence (unless heading/list)
    if blocks:
        last = blocks[-1]
        if not _LIST.match(last) and not _heading(last):
            strip = _FN.sub("", last).strip() or last
            if strip.endswith("-"):
                out.append((len(blocks) - 1, "TAIL-TERMINAL",
                            f"ends with hyphen: {strip[-60:]}"))
            elif not _TERMINAL.search(strip):
                out.append((len(blocks) - 1, "TAIL-TERMINAL",
                            f"no sentence-terminal: {strip[-60:]}"))
    return out


def paragraph_boundary_findings(text: str):
    """Strict staging audit: surface every lowercase start and every
    non-terminal prose-block ending. Findings require correction or an exact,
    reasoned disposition; they are not all automatic defects.
    """
    blocks = [x.strip() for x in text.split("\n\n")
              if x.strip() and not x.strip().startswith("^[")]
    out = []
    for i, block in enumerate(blocks):
        if _LIST.match(block) or _heading(block):
            continue
        first = _first_letter(block)
        digest = hashlib.sha256(block.encode("utf-8")).hexdigest()
        if first and first.islower() and not _ELLIPSIS.match(block):
            out.append({"index": i, "kind": "LOWER-START", "sha256": digest,
                        "snippet": block[:100]})
        if i + 1 < len(blocks) and not _nterm(block) \
                and not _closes_on_etc(block, blocks[i + 1]):
            out.append({"index": i, "kind": "NONTERMINAL-END", "sha256": digest,
                        "snippet": f"{block[-60:]} || {blocks[i + 1][:60]}"})
        elif i + 1 == len(blocks) and not _nterm(block):
            out.append({"index": i, "kind": "NONTERMINAL-END", "sha256": digest,
                        "snippet": block[-100:]})
    return out


def check_files(paths: list[Path], strict: bool = False,
                dispositions: list[dict] | None = None) -> int:
    """Print findings per file; return the number of unresolved ones."""
    dispositions = list(dispositions or [])
    bad = 0
    for path in paths:
        text = Path(path).read_text(encoding="utf-8")
        vs = paragraph_boundary_findings(text) if strict else seam_violations(text)
        print(f"== {path}: {len(vs)} violation(s)")
        for v in vs:
            if strict:
                matches = [d for d in dispositions if d.get("kind") == v["kind"]
                           and d.get("paragraph_sha256") == v["sha256"]
                           and d.get("reason", "").strip()]
                if matches:
                    dispositions.remove(matches[0])
                    print(f"   [{v['index']}] REVIEWED {v['kind']:16s} {v['snippet']!r}")
                else:
                    bad += 1
                    print(f"   [{v['index']}] UNRESOLVED {v['kind']:14s} sha256={v['sha256']} {v['snippet']!r}")
            else:
                bad += 1
                idx, kind, snip = v
                print(f"   [{idx}] {kind:12s} {snip!r}")
    if strict and dispositions:
        bad += len(dispositions)
        print(f"   UNMATCHED DISPOSITIONS: {len(dispositions)}")
    print("TOTAL VIOLATIONS:", bad)
    return bad


def main(
    files: Annotated[list[Path], typer.Argument(help="Assembled text files")],
    boundary_audit: Annotated[bool, typer.Option(help="Strict audit: every lowercase start and non-terminal end")] = False,
    dispositions: Annotated[Path | None, typer.Option(help="JSON list of hash-bound dispositions")] = None,
):
    """Fail on paragraphs split or cut at a page seam."""
    disp = []
    if dispositions:
        disp = json.loads(dispositions.read_text(encoding="utf-8"))
        if not isinstance(disp, list):
            raise typer.BadParameter("dispositions must be a JSON list")
    if check_files(files, boundary_audit, disp):
        raise typer.Exit(1)


app = typer.Typer(add_completion=False)
app.command()(main)


if __name__ == "__main__":
    app()
