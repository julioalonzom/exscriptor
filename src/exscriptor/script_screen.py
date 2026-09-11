#!/usr/bin/env python3
"""Non-Latin script screen for transcribed text.

A vision reader (and an OCR engine) occasionally emits a letter from another
script that is visually identical to a Latin one -- Cyrillic 'е' for Latin
'e', Greek 'ο' for 'o', a fullwidth or mathematical alphanumeric form. The
result is text that reads perfectly, diffs perfectly, and is invisible to
every count-based check, while it silently breaks token matching, search and
downstream normalization.

Two confidence bands, because a scholarly Latin text legitimately contains
Greek quotations:

* HIGH -- characters from a script that never appears in a Latin print
  (Cyrillic, Armenian, Cherokee, fullwidth/mathematical forms). Always an
  error.
* LOW -- Greek letters that have a Latin lookalike. Reported, not failed:
  check whether the passage is a genuine Greek quotation.

Usage:

    ex-screen-script --files 'transcription/*.md' [--glob ...] [--quiet]

Exits 1 when any HIGH hit is found. Work-agnostic: no edition knowledge, no
paths baked in.
"""
from __future__ import annotations

import glob as globmod
import re
import sys
import unicodedata
from pathlib import Path

import typer
from typing_extensions import Annotated

# Scripts that have no business in a Latin-script edition.
HARD_SCRIPTS = ("CYRILLIC", "ARMENIAN", "CHEROKEE", "HEBREW", "ARABIC", "THAI", "DEVANAGARI")
# Greek is reported separately: quotations are legitimate.
SOFT_SCRIPTS = ("GREEK",)

COMMENT_RE = re.compile(r"<!--.*?-->", re.S)


def script_of(ch: str) -> str | None:
    try:
        name = unicodedata.name(ch)
    except ValueError:
        return None
    for script in HARD_SCRIPTS + SOFT_SCRIPTS:
        if script in name:
            return script
    # Fullwidth / mathematical alphanumerics are letter lookalikes; their
    # non-letter cousins (⟦ ⟧ and other math brackets) are not, and a
    # pipeline is entitled to use such brackets as its own markers.
    if "FULLWIDTH" in name or "MATHEMATICAL" in name:
        if unicodedata.category(ch).startswith("L"):
            return "LOOKALIKE-FORM"
    return None


def suspicious(text: str, strip_comments: bool = True) -> dict[str, list[dict]]:
    """{'high': [{char, name, script, count, contexts}], 'low': [...]}"""
    if strip_comments:
        text = COMMENT_RE.sub(" ", text)
    found: dict[str, list[dict]] = {"high": [], "low": []}
    seen: dict[str, dict] = {}
    for ch in text:
        script = script_of(ch)
        if script is None:
            continue
        band = "low" if script in SOFT_SCRIPTS else "high"
        key = f"{band}:{ch}"
        if key not in seen:
            try:
                name = unicodedata.name(ch)
            except ValueError:
                name = "?"
            entry = {"char": ch, "name": name, "script": script, "count": 0, "contexts": []}
            seen[key] = entry
            found[band].append(entry)
        seen[key]["count"] += 1
        if len(seen[key]["contexts"]) < 3:
            for match in re.finditer(re.escape(ch), text):
                start = max(0, match.start() - 20)
                context = text[start : match.end() + 20].replace("\n", " ")
                seen[key]["contexts"].append(context)
                break
    return found


def screen_files(paths: list[Path], strip_comments: bool = True) -> list[dict]:
    report = []
    for path in paths:
        try:
            text = path.read_text()
        except (OSError, UnicodeDecodeError) as exc:  # unreadable/decoding
            report.append({"file": str(path), "error": str(exc), "high": [], "low": []})
            continue
        hits = suspicious(text, strip_comments=strip_comments)
        if hits["high"] or hits["low"]:
            report.append({"file": str(path), "high": hits["high"], "low": hits["low"]})
    return report


def _selftest() -> None:
    # Cyrillic 'е' and 'а' inside Latin words -> HIGH
    hits = suspicious("quia radic\u0435 jam explicata, et \u0430liter")
    assert len(hits["high"]) == 2, hits
    assert not hits["low"]
    # Greek quotation -> LOW, not HIGH
    hits = suspicious("ut habet \u03bb\u03cc\u03b3\u03bf\u03c2 Arist.")
    assert hits["high"] == []
    assert hits["low"], hits
    # comment layer excluded; clean Latin is clean
    assert suspicious("recte dicitur <!-- notes: \u0435 -->")["high"] == []
    assert suspicious("recte dicitur, prout in se est.") == {"high": [], "low": []}
    print("script_screen selftest OK")


def main(
    files: Annotated[list[str], typer.Argument(help="Files, directories or glob patterns to screen")] = None,
    keep_comments: Annotated[bool, typer.Option(help="Screen HTML comments too")] = False,
    quiet: Annotated[bool, typer.Option(help="Print only the summary")] = False,
    selftest: Annotated[bool, typer.Option(help="Run built-in checks and exit")] = False,
):
    """Screen text files for characters from a foreign (lookalike) script."""
    if selftest:
        _selftest()
        return
    if not files:
        raise typer.BadParameter("give at least one file, directory or glob (or --selftest)")
    paths: list[Path] = []
    for pattern in files:
        expanded = globmod.glob(pattern, recursive=True)
        if not expanded:
            expanded = [pattern]
        for item in expanded:
            p = Path(item)
            if p.is_dir():
                paths.extend(sorted(p.glob("*.md")) + sorted(p.glob("*.txt")))
            elif p.exists():
                paths.append(p)
    report = screen_files(paths, strip_comments=not keep_comments)
    hard = [r for r in report if r.get("high")]
    for row in report:
        if row.get("error"):
            print(f"  unreadable {row['file']}: {row['error']}")
            continue
        for band, label in (("high", "HIGH"), ("low", "low ")):
            for hit in row[band]:
                if quiet and band == "high":
                    continue
                print(
                    f"  {label} {row['file']}: U+{ord(hit['char']):04X} {hit['name']} "
                    f"x{hit['count']}  e.g. …{hit['contexts'][0]}…"
                )
    print(
        f"{len(paths)} files screened: "
        f"{len(hard)} with non-Latin-script characters, "
        f"{len([r for r in report if r.get('low')])} with Greek lookalikes"
    )
    if hard:
        sys.exit(1)


app = typer.Typer()
app.command()(main)


if __name__ == "__main__":
    app()
