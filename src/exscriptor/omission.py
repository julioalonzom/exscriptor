#!/usr/bin/env python3
"""Token-level omission screen: did a page lose a run of words the witness has?

Why this screen exists next to ``exscriptor.coverage``. ``coverage`` compares a
page file with the OCR witness by character alignment, and the house's own
page-file contract moves text in two ways that break the alignment on most
pages: page files carry no running head, and every note is written at its
printed anchor inside the paragraph, while the witness keeps the notes at the
page's foot. The sequence therefore differs wherever a page has notes, and the
score collapses without anything being wrong with the reading. Measured on
Merkelbach II pp. 7-123 (2026-10-21): 43 of 117 pages below 0.9, the worst
0.49, on pages whose only absent witness words were the head, the OCR's own
hyphen fragments, and wire noise.

What a single-column page can still suffer is the omission ``coverage`` was
built for: a clause or paragraph silently dropped. That class is visible as a
*run* of consecutive witness words the page does not contain, compared
count-aware (a word the page has once cannot cover two witness occurrences, so
a dropped repetition shows too). A run is only reported when at least
``min_known`` of its words are in the corpus lexicon: the OCR of a bilevel scan
emits long runs of wire noise (``воьсе оріонет ідоні``), and those are not
omissions.

Usage:

    ex-omission --pages-dir works/x/diplomatic --witness works/x/tmp/ocr.json \\
        --range 7-123 --page-pattern 'pg-{page03}.md' \\
        --witness-key-patterns 'pg-{page03}.jpg' \\
        --drop-head-words summa,theologiae,moralis \\
        --lexicon .cache/latin-lexicon.json

Exits 1 while any page carries a reported run. Work-agnostic: names, patterns,
head words and thresholds all come from the caller.
"""
from __future__ import annotations

import json
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path

import typer
from typing_extensions import Annotated

from exscriptor.coverage import parse_pages, witness_text
from exscriptor.lexicon import load as load_lexicon

app = typer.Typer(add_completion=False, help="Token-level omission screen against an OCR witness.")

WORD_RE = re.compile(r"[^\W\d_]+", re.UNICODE)
COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
DEFAULT_WITNESS_KEYS = "pg-{page}.jpg,pg-{page},p{page}.md,{page}"


def _fold(token: str) -> str:
    """Lowercase, strip accents, long s -> s, and nothing else."""
    t = unicodedata.normalize("NFKD", token)
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return t.lower().replace("\u017f", "s")


def tokens(text: str) -> list[str]:
    return [_fold(w) for w in WORD_RE.findall(text)]


def missing_flags(page_text: str, witness_text_string: str) -> list[tuple[bool, str]]:
    """(absent?, word) for every witness token, count-aware against the page."""
    pool = Counter(tokens(page_text))
    out = []
    for word in tokens(witness_text_string):
        if pool[word] > 0:
            pool[word] -= 1
            out.append((False, word))
        else:
            out.append((True, word))
    return out


def runs(flags: list[tuple[bool, str]], minimum: int) -> list[list[str]]:
    """Maximal runs of at least ``minimum`` consecutive absent words."""
    found, current = [], []
    for absent, word in flags:
        if absent:
            current.append(word)
        else:
            if len(current) >= minimum:
                found.append(current)
            current = []
    if len(current) >= minimum:
        found.append(current)
    return found


def omission_runs(
    page_text: str,
    witness: str,
    min_run: int = 4,
    lexicon: set[str] | None = None,
    min_known: int = 3,
    drop_words: set[str] | None = None,
) -> tuple[int, int, list[list[str]]]:
    """Absent-token count, witness length, and the reported runs.

    ``drop_words`` are the running-head words, which are never text (house
    style 2) and so are never missing. ``lexicon`` filters out wire noise: a
    run survives only when ``min_known`` of its words are real corpus words.
    """
    drop = drop_words or set()
    body = COMMENT_RE.sub("", page_text)
    flags = [(absent, word) for absent, word in missing_flags(body, witness) if word not in drop]
    found = runs(flags, min_run)
    if lexicon is not None:
        found = [r for r in found if sum(1 for w in r if w in lexicon) >= min_known]
    return sum(1 for absent, _ in flags if absent), len(flags), found


@app.command()
def main(
    pages_dir: Annotated[Path, typer.Option(help="Directory holding the page files")],
    witness: Annotated[Path, typer.Option(help="Witness JSON or directory of per-page .txt")],
    range: Annotated[str, typer.Option(help="Pages to screen, e.g. '105-200,300'")],
    page_pattern: Annotated[str, typer.Option(help="Page file name pattern, {page} or {page03}")] = "p{page}.md",
    witness_key_patterns: Annotated[str, typer.Option(help="Comma-separated witness key patterns")] = DEFAULT_WITNESS_KEYS,
    min_run: Annotated[int, typer.Option(help="Shortest run of absent words worth reporting")] = 4,
    min_known: Annotated[int, typer.Option(help="Lexicon words a run must contain to be reported")] = 3,
    drop_head_words: Annotated[str, typer.Option(help="Comma-separated running-head words, never text")] = "",
    lexicon_path: Annotated[Path | None, typer.Option("--lexicon", help="Corpus lexicon (filters wire noise)")] = None,
    show: Annotated[int, typer.Option(help="Runs to print")] = 40,
    json_out: Annotated[Path | None, typer.Option(help="Write full results here")] = None,
) -> None:
    """Report pages that lost a run of text the OCR witness has."""
    pages = parse_pages(range)
    patterns = [p.strip() for p in witness_key_patterns.split(",") if p.strip()]
    drop = {w.strip().lower() for w in drop_head_words.split(",") if w.strip()}
    lex = set(load_lexicon(lexicon_path)) if lexicon_path else None
    if witness.is_dir():
        data = {p.stem: p.read_text(encoding="utf-8") for p in witness.glob("*.txt")}
    else:
        data = json.loads(witness.read_text(encoding="utf-8"))

    results, flagged = [], []
    for page in pages:
        path = pages_dir / page_pattern.format(page=page, page03=f"{page:03d}", page04=f"{page:04d}")
        if not path.exists():
            continue
        wit = witness_text(data, page, patterns)
        if not wit:
            continue
        missing, total, found = omission_runs(path.read_text(encoding="utf-8"), wit,
                                              min_run=min_run, lexicon=lex,
                                              min_known=min_known, drop_words=drop)
        results.append({"page": page, "file": str(path), "missing": missing,
                        "words": total, "runs": [" ".join(r) for r in found]})
        if found:
            flagged.append((page, found))

    print(f"pages screened: {len(results)}; pages with a run of >={min_run} absent words: {len(flagged)}")
    for page, found in flagged[:show]:
        for run in found:
            print(f"  p{page}: {' '.join(run)[:160]}")
    results.sort(key=lambda r: -r["missing"])
    print("--- most absent words (running head, OCR hyphen fragments, wire noise) ---")
    for row in results[:10]:
        print(f"  p{row['page']}: {row['missing']} of {row['words']}")
    if json_out:
        json_out.write_text(json.dumps(results, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"wrote {json_out}")
    if flagged:
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
