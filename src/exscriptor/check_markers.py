#!/usr/bin/env python3
"""Marker-balance screen for zoned pages: [*N] keys vs marginalia lines,
[N] apparatus keys vs apparatus lines, per page.

Zone names default to the two-voice (author/commentator) convention; override
with DIGITIZE_ZONES="A,B" (comma-separated) for other editions.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import typer
from typing_extensions import Annotated

from exscriptor import seams

# The same pattern as preflight's residue screen, here on page files, where
# the reference mark shows as « *[*3] ».
STRAY_ASTERISK = re.compile(r"(?<=[ \t])\*+(?=\s|[,.;:)\]]|\^\[|\[\*|$)")
KEY = re.compile(r"\[\*(\d+)\]")
APP_KEY = re.compile(r"\[\*?(\d+)\]")  # text-side apparatus key (numeric, may be bare)
NOTE = re.compile(r"^\[?\*(\d+)\]?[ \t]+", re.M)
APP_NOTE = re.compile(r"^(\d+)[\])]?", re.M)
# A note closed on a word broken at the line end: cut at the page foot, so it
# ends « ⟦NOTE-CONTINUES⟧] » and its rest opens the next page's last block.
NOTE_CUT = re.compile(r"[^\W\d_]-\]")


# Comment keys a page file may open with. 'notes' is the house form; the others
# are the page templates' own (a page's opening/joining declaration, its
# formatting record, a catchword, a folio, a chapter or seam remark).
COMMENT_KEYS = ("notes", "opens", "formatting", "catchword", "folio", "chapter", "seam")


def note_defects(s: str) -> list[tuple[str, int]]:
    """Inline notes the platform refuses: unclosed, doubled (« ^[^[ ») or with
    a note nested inside (an editor's note on a footnote goes at its end, in
    plain brackets: « ^[1. … [Editor's note: …]] »)."""
    out, i = [], 0
    while i < len(s):
        if s[i] == "\\":
            i += 2
            continue
        if not s.startswith("^[", i):
            i += 1
            continue
        depth, j, inner = 1, i + 2, []
        while j < len(s) and depth:
            if s[j] == "\\":
                j += 2
                continue
            if s.startswith("^[", j):
                inner.append(j)
            depth += {"[": 1, "]": -1}.get(s[j], 0)
            j += 1
        if depth:
            out.append(("unclosed", i))
            i += 2
            continue
        out += [("doubled" if k == i + 2 else "nested", k) for k in inner]
        i = j
    return out


def comment_issues(text: str, name: str) -> list[str]:
    """Fail-closed check on the HTML comment layer of a page file.

    A page file's editorial notes live in a trailing HTML comment that the
    assembler strips by regex. An UNTERMINATED comment is not stripped at
    all, so the whole note layer -- band geometry, marginals, flags, the
    pipeline's own vocabulary -- flows into the assembled body text and can
    reach publication while every other gate passes. Balance is therefore a
    hard gate, not a style point.
    """
    issues = []
    opens, closes = text.count("<!--"), text.count("-->")
    if opens != closes:
        issues.append(f"{name}: unbalanced HTML comment layer: {opens} '<!--' vs {closes} '-->'")
    # House form: every comment OPENER is '<!-- <key>:' with a key from
    # COMMENT_KEYS ('notes', and the page templates' 'opens', 'formatting', ...).
    # A comment that opens any other way ('<!-- supersedes previous version', a
    # stray '<!--') is not harvested by the assembler and leaks pipeline
    # vocabulary into the published body while the balance checks above pass.
    for m in re.finditer(rf"<!--(?! (?:{'|'.join(COMMENT_KEYS)}):)[^\n]{{0,60}}", text):
        issues.append(f"{name}: comment not in house form '<!-- notes:' (or one of "
                      f"{', '.join(COMMENT_KEYS)}) -> {m.group()[:60]!r}")
    stripped = re.sub(r"<!--.*?-->", " ", text, flags=re.S)
    if "<!--" in stripped:
        issues.append(f"{name}: comment opener left unstripped (nested or unterminated comment)")
    if re.search(r"\|\s*(marginals|band geometry|footnotes|dangling)\b", stripped):
        issues.append(f"{name}: note-layer vocabulary leaked into the body text")
    return issues


def markup_issues(text: str, name: str, apparatus_keys: bool = False) -> list[str]:
    """Fail-closed checks on the markup a page file emits.

    Two classes that no content gate can see, both found in a live run only by
    a hand-written screen:

    * **unbalanced inline italics** -- an odd number of asterisks on one line.
      The usual cause is an italic span that runs across a paragraph or page
      break without being closed and re-opened: markdown ends the emphasis at
      the blank line, so the text renders with literal asterisks. The
      convention is to close at the break and re-open after it.
    * **the `***...***` heading form** -- a line both opening and closing with
      three asterisks is bold+italic, which the house pipeline does not
      recognise downstream. The canonical form for a display heading with an
      italic sub-title is `**§ N. *Title*.**` (bold line, italic inside).

    `apparatus_keys=True` additionally ignores the zoned-pipeline apparatus
    convention (`[*3]` keys and `*3 note` marginalia), whose lone asterisk
    before a digit is not emphasis. Leave it False for page files that use
    `*...*` for emphasis only: there, an italic run may legitimately open on a
    paragraph number (`*9 Ad primam respondet...*`), and stripping it would
    report a false imbalance.
    """
    issues = []
    body = re.sub(r"<!--.*?-->", " ", text, flags=re.S)
    # Before the apparatus convention is stripped: « *[*1] » is the doubled mark.
    for line in body.splitlines():
        for m in STRAY_ASTERISK.finditer(line):
            issues.append(f"{name}: stray asterisk (a doubled reference mark, or an italic "
                          f"emptied or closed after a space): {line[max(0, m.start() - 30):m.end() + 20]!r}")
    for kind, at in note_defects(body):
        issues.append(f"{name}: {kind} inline note (an editor's note on a footnote goes at its end, "
                      f"in plain brackets: ^[1. … [Editor's note: …]]): {body[max(0, at - 30):at + 40]!r}")
    for m in NOTE_CUT.finditer(body):
        issues.append(f"{name}: note ends mid-word (a note cut at the page foot ends "
                      f"⟦NOTE-CONTINUES⟧]): {body[max(0, m.start() - 40):m.end()]!r}")
    if apparatus_keys:
        body = re.sub(r"(?m)^\*(?=\d+\s)|\[\*(?=\d+\])", "", body)
    # A note whose printed mark is an asterisk (`^[* text]`, `^[*. text]`) is not emphasis.
    body = re.sub(r"\^\[\*+(?=[ .])", "^[", body)
    # One paragraph = one line, and an italic span never crosses a line (a span
    # that runs across a PAGE break is closed at the foot and re-opened at the
    # next page's head). So every LINE carries an even number of asterisks:
    # '**…**' contributes 2, '*…*' contributes 2, and the heading form
    # '**§ N. *Title*.**' contributes 6. An odd line means a span was opened
    # and never closed (or vice versa).
    for line in body.splitlines():
        stripped = line.rstrip()
        if stripped.count("*") % 2:
            issues.append(
                f"{name}: unbalanced italic markers on one line "
                f"({stripped.count('*')} asterisks): {stripped[:70]!r}"
            )
        if stripped.startswith("***") and stripped.endswith("***"):
            issues.append(f"{name}: forbidden heading form `***…***`: {stripped[:60]!r}")
    return issues


def wrap_issues(text: str, name: str, term: str = '.:;!?»"', min_breaks: int = 3) -> list[str]:
    """Flag a page file that kept the PRINT's line breaks (hard wrapping).

    The house style is one paragraph per line: a printed line that ends
    mid-sentence is joined onto its continuation, and a new line begins only
    where the print begins a new paragraph. A file that instead preserves every
    printed line break produces spurious paragraph breaks in the assembled text
    — and it also forces italic markers to be closed and re-opened at each
    printed line, hiding the quotation's real span. `min_breaks` keeps single
    legitimate-looking breaks (a seam at a page edge) from raising noise.
    """
    lines = [l.strip() for l in re.sub(r"<!--.*?-->", " ", text, flags=re.S).splitlines() if l.strip()]
    breaks = []
    for a, b in zip(lines, lines[1:]):
        if a.startswith(("*", "#", "<")) or b.startswith(("*", "#", "<")):
            continue
        if a[-1] in term or a.endswith("-"):
            continue
        # A block that opens on a list label is the print's own item start,
        # not a printed line break kept as a paragraph: the sentence before it
        # may legitimately run on ('…ideo' / 'a) opinio aliquando …').
        if b[:1].islower() and not seams.is_list_label(b):
            breaks.append((a[-40:], b[:40]))
    if len(breaks) >= min_breaks:
        sample = f"{breaks[0][0]!r} / {breaks[0][1]!r}"
        return [
            f"{name}: {len(breaks)} mid-sentence line breaks — the page looks hard-wrapped "
            f"(the print's line breaks kept as paragraphs); first: {sample}"
        ]
    return []


def check_page(text: str, name: str) -> list[str]:
    issues = comment_issues(text, name)
    issues.extend(markup_issues(text, name, apparatus_keys=True))
    zones = {}
    cur = None
    for line in text.splitlines():
        if line.startswith("<<<"):
            cur = line.strip("<>")
            zones.setdefault(cur, [])
        elif cur is not None:
            zones[cur].append(line)
    # per-zone balance: each zone's keys against ITS OWN marginalia
    zone_names = [z.strip() for z in os.environ.get("DIGITIZE_ZONES", "AUTHOR,COMMENTATOR").split(",")]
    for zname in zone_names:
        body = " ".join(zones.get(zname, []))
        marg = "\n".join(zones.get(f"{zname}-MARGINALIA", []))
        star_keys = {k for k in KEY.findall(body)}
        star_notes = {k for k in NOTE.findall(marg)}
        for k in sorted(star_keys - star_notes):
            issues.append(f"{name}: {zname} [*{k}] has no marginalia line")
        for k in sorted(star_notes - star_keys):
            issues.append(f"{name}: {zname} marginalia *{k} has no text key")
    app = " ".join(zones.get(f"{zone_names[0]}-APPARATUS", []))
    app_notes = [m.group(1) for m in APP_NOTE.finditer(app)]
    if app and len(app_notes) == 0:
        issues.append(f"{name}: apparatus present but no numbered notes parsed")
    return issues


def main(
    pages: Annotated[str, typer.Option(help='Pages to check, e.g. "1-50,77"')],
    runs: Annotated[list[Path], typer.Argument(help="Run dirs containing pg-NNN.md files")],
):
    """Check zone-marker / marginalia balance on transcribed pages."""
    nums = []
    for part in pages.split(","):
        if "-" in part:
            lo, hi = part.split("-")
            nums.extend(range(int(lo), int(hi) + 1))
        else:
            nums.append(int(part))
    all_issues = []
    for num in nums:
        for run in runs:
            f = run / f"pg-{num:03d}.md"
            if f.is_file():
                all_issues.extend(check_page(f.read_text(), f.parent.name + "/" + f.stem))
    if all_issues:
        print(f"{len(all_issues)} marker issues:")
        for i in all_issues[:60]:
            print("  ", i)
        raise typer.Exit(1)
    print("marker screen clean")


app = typer.Typer()
app.command()(main)


if __name__ == "__main__":
    app()
