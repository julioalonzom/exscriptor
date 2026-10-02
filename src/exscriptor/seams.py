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
from pathlib import Path

import typer
from typing_extensions import Annotated

# A sentence may end inside emphasis or a quotation: `…Anno Domini 1585.*`.
_TERMINAL = re.compile(r"[.!?…]['\"”’»)\]»*_]*$")
_FN = re.compile(r"\^\[[^\]]*\]\s*$")
_COLON = re.compile(r":\s*$")
_LIST = re.compile(
    r"^\s*(?:\d+[.)]|\d+[°º](?:\.|\s)|[a-z]\)|[αβγδε]\)|[ivxlcdm]+\)|[•\-\u2013\u2014·]\s|"
    r"(?:Primero|Segundo|Tercero|Cuarto|Quinto)\s*[:.]|"
    r"\*{1,2}\s)")
# A leading ellipsis marks a DELIBERATE mid-phrase continuation (the print's
# dot-glyph convention in Felder's intro, pp. 2-3: '…de Deo rebusque
# divinis.'), not an accidental seam split — exempt from lowercase-start.
_ELLIPSIS = re.compile(r"^\s*…")
_STRUCT = re.compile(r"^\*{1,2}(?:SECCION|CAPITULO|EP[IÍ]LOGO|PR[OÓ]LOGO)", re.I)
_SHORT_BOLD = re.compile(
    r"^\*{1,2}[0-9IVXa-zA-ZÁÉÍÓÚÜÑáéíóúüñ\s.,;:\"'«»()\-\u2014\u2013]+\*{1,2}$")


def _heading(b: str) -> bool:
    return (bool(re.match(r"^\s*#{1,6}\s", b)) or bool(_STRUCT.match(b))
            or bool(b.startswith("*") and len(b) < 130
                    and (_SHORT_BOLD.match(b) or
                         (b.startswith("*") and b.endswith("*") and
                          not b.startswith("**")))))


def _first_letter(s: str) -> str:
    """First alphabetic character of a block, skipping leading quotes,
    brackets, dashes, bold markers, etc. The lowercase-start checks must
    look at the first LETTER: a block starting with '\"novam\"' is a
    lowercase start even though its first char is a quote."""
    for c in s:
        if c.isalpha():
            return c
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
        if i + 1 < len(blocks) and not _nterm(block):
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
