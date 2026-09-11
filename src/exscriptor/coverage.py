#!/usr/bin/env python3
"""Coverage screen: how much of an OCR witness a transcription actually
contains, and how much of the transcription the witness actually contains.

Why a screen beyond token counts: counting words or diffing token sets
cannot see the two defect classes that matter most in a page-file pipeline
against a scanned print --

* OMISSION -- a chunk silently dropped where two columns meet (the reader
  jumped from the foot of the left column to the foot of the right one).
  The page keeps the right vocabulary and every count-based check passes.
* FABRICATION / self-echo -- fluent plausible text invented at a column or
  page seam, echoing material the reader already read on the same page and
  absent from every witness. A count-based screen passes it too.

Character-level alignment coverage catches both, because the two
directions of the metric fail differently:

    recall    = matched / len(witness)   falls when text is OMITTED
    precision = matched / len(file)      falls when text is INVENTED
    score     = min(recall, precision)

Calibrate the threshold per edition on pages you have adjudicated by hand:
complete pages cluster near 0.95-0.99 against a decent OCR witness, pages
with a dropped column chunk land in the 0.55-0.85 band. A witness entry
that is anomalously long for its page size (an OCR pass concatenated twice,
say) breaks the recall direction: treat the *file* as sound when precision
is high and the witness length is the outlier.

Usage (a workbench normally wraps this with its own page pattern/thresholds):

    ex-coverage --pages works/x/transcription --witness works/x/ocr.json \
        --range 105-200 --page-pattern 'p{page}.md' \
        --witness-key-patterns 'pg-{page}.jpg,{page}'

Every parameter is edition-agnostic: page file names, witness key shapes,
and thresholds are all supplied by the caller.
"""
from __future__ import annotations

import json
import re
import sys
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

import typer
from typing_extensions import Annotated

DEFAULT_WITNESS_KEYS = "pg-{page}.jpg,pg-{page},p{page}.md,{page}"
DEFAULT_PAGE_PATTERN = "p{page}.md"
COMMENT_RE = re.compile(r"<!--.*?-->", re.S)


def fold(text: str) -> str:
    """Lowercase, strip accents, drop everything but [a-z0-9]."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = text.lower().replace("\u017f", "s").replace("\u1e9b", "s")
    return re.sub(r"[^a-z0-9]+", "", text)


def coverage_detail(page_file: str, witness: str) -> tuple[float, float, float]:
    """(score, recall, precision) of a page file against its witness."""
    a, b = fold(page_file), fold(witness)
    if not a or not b:
        return 0.0, 0.0, 0.0
    matcher = SequenceMatcher(None, a, b, autojunk=False)
    matched = sum(block.size for block in matcher.get_matching_blocks())
    recall, precision = matched / len(b), matched / len(a)
    return min(recall, precision), recall, precision


def coverage(page_file: str, witness: str) -> float:
    return coverage_detail(page_file, witness)[0]


def strip_editorial_notes(text: str) -> str:
    """Drop HTML comments -- a page file's own note layer, not the text."""
    return COMMENT_RE.sub(" ", text)


def key_variants(page: int, patterns: list[str]) -> list[str]:
    return [p.replace("{page}", str(page)).replace("{page03}", f"{page:03d}") for p in patterns]


def witness_text(witness: dict, page: int, patterns: list[str]) -> str | None:
    for key in key_variants(page, patterns):
        for candidate in (key, key if isinstance(key, str) else str(key)):
            if candidate in witness:
                entry = witness[candidate]
                if isinstance(entry, dict):
                    if "left" in entry or "right" in entry:
                        return (entry.get("left") or "") + " " + (entry.get("right") or "")
                    for field in ("text", "content", "body"):
                        if field in entry:
                            return entry[field]
                    return None
                return entry
    return None


def load_witness(path: Path) -> dict:
    """A witness is either one JSON object keyed by page, or a directory of
    per-page text files (one file per page, stem = page identifier)."""
    if path.is_dir():
        return {p.stem: p.read_text() for p in sorted(path.glob("*.txt"))}
    data = json.loads(path.read_text())
    if isinstance(data, dict) and "pages" in data and isinstance(data["pages"], dict):
        data = data["pages"]
    if not isinstance(data, dict):
        raise typer.BadParameter(f"witness JSON must be an object keyed by page: {path}")
    return data


def parse_pages(spec: str) -> list[int]:
    pages: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            lo, hi = part.split("-", 1)
            pages.extend(range(int(lo), int(hi) + 1))
        else:
            pages.append(int(part))
    return pages


def screen(
    pages_dir: Path,
    witness: dict,
    pages: list[int],
    page_pattern: str,
    witness_keys: list[str],
    threshold: float,
    watch: float,
    strip_comments: bool = True,
) -> list[dict]:
    results = []
    for page in pages:
        name = page_pattern.replace("{page}", str(page)).replace("{page03}", f"{page:03d}")
        path = pages_dir / name
        if not path.exists():
            results.append({"page": page, "file": str(path), "status": "missing"})
            continue
        text = path.read_text()
        if strip_comments:
            text = strip_editorial_notes(text)
        wit = witness_text(witness, page, witness_keys)
        if not wit:
            results.append({"page": page, "file": str(path), "status": "no-witness"})
            continue
        score, recall, precision = coverage_detail(text, wit)
        status = "ok" if score >= watch else ("watch" if score >= threshold else "fail")
        results.append(
            {
                "page": page,
                "file": str(path),
                "status": status,
                "score": round(score, 3),
                "recall": round(recall, 3),
                "precision": round(precision, 3),
                "words": len(text.split()),
            }
        )
    return results


def _selftest() -> None:
    wit = "Nam sicut specificatio sumitur a forma, ita individuatio a materia."
    assert coverage(wit, wit) > 0.999
    # omission: a file that dropped half the print fails
    assert coverage("Nam sicut specificatio sumitur a forma.", wit) < 0.75
    # fabrication: a file padded with invented text fails
    padded = wit + (
        " Unde haec objectio non destruit conclusionem nostram, ideo in praesenti "
        "consulto omittimus, ut ex dictis constat omnino."
    )
    assert coverage(padded, wit) < 0.90, coverage(padded, wit)
    assert coverage("", wit) == 0.0
    # accent / case / punctuation insensitivity
    assert coverage("NAM sícut specificátio, sumitur: a forma, ita individuátio a matériá.", wit) > 0.9
    # witness key shapes
    assert witness_text({"pg-12.jpg": "x"}, 12, ["pg-{page}.jpg"]) == "x"
    assert witness_text({"pg-012.jpg": "x"}, 12, ["pg-{page03}.jpg"]) == "x"
    assert witness_text({"3": {"left": "a", "right": "b"}}, 3, ["{page}"]) == "a b"
    assert parse_pages("1-3,7") == [1, 2, 3, 7]
    print("coverage selftest OK")


def main(
    pages_dir: Annotated[Path, typer.Option(help="Directory holding the page files")],
    witness_path: Annotated[Path, typer.Option("--witness", help="Witness JSON or directory of per-page .txt")],
    page_range: Annotated[str, typer.Option("--range", help='Pages to screen, e.g. "105-200,300"')],
    page_pattern: Annotated[str, typer.Option(help="Page file name pattern, {page} or {page03}")] = DEFAULT_PAGE_PATTERN,
    witness_key_patterns: Annotated[
        str, typer.Option(help="Comma-separated witness key patterns, {page}/{page03}")
    ] = DEFAULT_WITNESS_KEYS,
    threshold: Annotated[float, typer.Option(help="Score below which a page FAILS")] = 0.90,
    watch: Annotated[float, typer.Option(help="Score at or above which a page is clean")] = 0.94,
    keep_comments: Annotated[bool, typer.Option(help="Keep HTML comments in the page text")] = False,
    json_out: Annotated[Path | None, typer.Option("--json-out", help="Write full results here")] = None,
    quiet: Annotated[bool, typer.Option(help="Only print the summary")] = False,
    selftest: Annotated[bool, typer.Option(help="Run built-in checks and exit")] = False,
):
    """Screen transcribed page files against an OCR witness by alignment coverage."""
    if selftest:
        _selftest()
        return
    witness = load_witness(witness_path)
    pages = parse_pages(page_range)
    results = screen(
        pages_dir,
        witness,
        pages,
        page_pattern,
        [p for p in witness_key_patterns.split(",") if p.strip()],
        threshold,
        watch,
        strip_comments=not keep_comments,
    )
    for row in results:
        if row["status"] in ("missing", "no-witness"):
            if not quiet:
                print(f"  {row['status']:>11} p{row['page']}")
        elif row["status"] != "ok" and not quiet:
            print(
                f"  {row['status']:>11} p{row['page']}  score {row['score']:.2f} "
                f"(recall {row['recall']:.2f} / precision {row['precision']:.2f}, {row['words']} words)"
            )
    counts = {}
    for row in results:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    print(
        f"pages {page_range}: "
        + ", ".join(f"{n} {status}" for status, n in sorted(counts.items()))
        + f" (threshold {threshold}, clean at {watch})"
    )
    failing = [r for r in results if r["status"] == "fail"]
    if failing:
        print("FAIL: " + ", ".join(f"p{r['page']} {r['score']:.2f}" for r in failing))
    if json_out:
        json_out.write_text(json.dumps(results, indent=2))
        print(f"wrote {json_out}")
    if any(r["status"] == "fail" for r in results):
        sys.exit(1)


app = typer.Typer()
app.command()(main)


if __name__ == "__main__":
    app()
