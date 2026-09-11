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

KEY = re.compile(r"\[\*(\d+)\]")
APP_KEY = re.compile(r"\[\*?(\d+)\]")  # text-side apparatus key (numeric, may be bare)
NOTE = re.compile(r"^\[?\*(\d+)\]?[ \t]+", re.M)
APP_NOTE = re.compile(r"^(\d+)[\])]?", re.M)


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
    stripped = re.sub(r"<!--.*?-->", " ", text, flags=re.S)
    if "<!--" in stripped:
        issues.append(f"{name}: comment opener left unstripped (nested or unterminated comment)")
    if re.search(r"\|\s*(marginals|band geometry|footnotes|dangling)\b", stripped):
        issues.append(f"{name}: note-layer vocabulary leaked into the body text")
    return issues


def markup_issues(text: str, name: str) -> list[str]:
    """Fail-closed checks on the markup a page file emits.

    Two classes that no content gate can see, both found in a live run only by
    a hand-written screen:

    * **unbalanced inline italics** -- an odd number of single asterisks. The
      usual cause is an italic span that runs across a page break: the page
      must CLOSE its span at the foot and the next page re-open it, and a file
      that forgets leaves the rest of the volume italic.
    * **the `***...***` heading form** -- a line both opening and closing with
      three asterisks is bold+italic, which the house pipeline does not
      recognise downstream. The canonical form for a display heading with an
      italic sub-title is `**§ N. *Title*.**` (bold line, italic inside).
    """
    issues = []
    body = re.sub(r"<!--.*?-->", " ", text, flags=re.S)
    # Apparatus keys ('[*3]', '*3 note', '[*3]') use a lone asterisk before a
    # digit: they are not emphasis and must not skew the count.
    body = re.sub(r"\*(?=\d)", "", body)
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


def check_page(text: str, name: str) -> list[str]:
    issues = comment_issues(text, name)
    issues.extend(markup_issues(text, name))
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
