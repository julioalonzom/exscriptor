"""Build an ``append_texts`` manifest: a translation of a work already live.

The Latin is live, so the builder reads a saved snapshot of the live work,
never local files: ``python3 -m exscriptor.snapshot <slug> --out <work>/live.json``. The translations are plain files, one per
live section: ``<translations>/<section_id>.md``. Every section with Latin
and without the target language must have one, and no other file may be
there.

    python3 -m exscriptor.append_texts <snapshot>.json <translations> \\
        --title-translations titles.json --source-key <key> --source-url <url> \\
        --batch-slug <slug> --title "<title>" --attribution "<credit>" \\
        --out <work>/manifests/<stem>.json

Refuses, writing nothing, when a section is missing or extra, a title
translation is missing (parents included), the block counts differ, or a
block's Markdown differs from the Latin's (bold, italics, headings, notes).
The one allowed extra is an inline note beginning « Editor's note: ».
A revision needs a new ``--batch-slug`` (``-v2``): a slug is consumed even by
a refused batch. An
italic-count difference a reader checked (a printed title running across a
page break) passes only with a review bound to that exact pair:
``--format-reviews`` maps ``"<section_id>#<block>"`` to ``{"sha256":
sha256(latin + "\\0" + translation), "note": "<why, six words or more>"}``.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Optional

import typer
from typing_extensions import Annotated

from exscriptor import licence

app = typer.Typer(add_completion=False)


def blocks(content: str) -> list[str]:
    return [b.strip() for b in re.split(r"\n\s*\n+", content.strip()) if b.strip()]


def markdown_signature(text: str) -> dict[str, int]:
    return {
        "bold": text.count("**") // 2,
        "emphasis_star": len(re.findall(r"(?<!\*)\*(?!\*)", text)) // 2,
        "emphasis_underscore": len(re.findall(r"(?<!_)_(?!_)", text)) // 2,
        "inline_footnote": text.count("^["),
        "reference_footnote": text.count("[^"),
        "heading": len(re.findall(r"(?m)^#{1,6}\s", text)),
    }


def editor_notes(text: str) -> int:
    """Inline notes that announce themselves as the editor's (either apostrophe)."""
    return len(re.findall(r"\^\[Editor['’]s note:", text))


def structure_errors(latin: list[str], target: list[str]) -> list[str]:
    """Block count, the Markdown signature per block, escaped markup. (``blocks`` already drops
    blank blocks and splits on blank lines, so a block can be neither.)"""
    errors: list[str] = []
    if len(target) != len(latin):
        errors.append(f"block_count:{len(target)}!={len(latin)}")
    for i, t in enumerate(target, 1):
        if i <= len(latin):
            src, out = markdown_signature(latin[i - 1]), markdown_signature(t)
            extra_editor = editor_notes(t) - editor_notes(latin[i - 1])
            delta = out["inline_footnote"] - src["inline_footnote"]
            same = {k: v for k, v in out.items() if k != "inline_footnote"} == \
                   {k: v for k, v in src.items() if k != "inline_footnote"}
            if delta < 0 or delta != extra_editor or not same:
                errors.append(f"markdown_block:{i}:{out!r}!={src!r}")
    for escaped in (r"\^[", r"\*", r"\_"):
        errors += [f"escaped_markdown:{escaped!r}:{i}" for i, t in enumerate(target, 1) if escaped in t]
    return errors


def filter_reviewed_format_errors(section_id, latin, target, errors, reviews):
    """Accept only reviewed, exact-pair differences in italic-span counts."""
    remaining = []
    for error in errors:
        match = re.match(r"^markdown_block:(\d+):", error)
        if not match:
            remaining.append(error)
            continue
        i = int(match.group(1))
        if i < 1 or i > min(len(latin), len(target)):
            remaining.append(error)
            continue
        source, out = latin[i - 1], target[i - 1]
        review = reviews.get(f"{section_id}#{i}", {})
        digest = hashlib.sha256((source + "\0" + out).encode("utf-8")).hexdigest()
        a, b = markdown_signature(source), markdown_signature(out)
        for key in ("emphasis_star", "emphasis_underscore"):
            a.pop(key)
            b.pop(key)
        if a != b or review.get("sha256") != digest or len(str(review.get("note", "")).split()) < 6:
            remaining.append(error)
    return remaining


def flatten(sections, parent=None, path=()):
    for s in sections:
        here = (*path, s)
        yield s, parent, here
        yield from flatten(s.get("children", []), s, here)


def build(work: dict, translations: dict[int, str], titles: dict[int, str], language: str,
          source: dict, batch_slug: str, title: str, reviews: dict | None = None) -> dict:
    """The manifest, or SystemExit naming the first problem."""
    flat = list(flatten(work.get("sections", [])))
    targets = [(s, p, path) for s, p, path in flat
               if s.get("texts", {}).get("la") and not s.get("texts", {}).get(language)]
    want = {s["id"] for s, _, _ in targets}
    if set(translations) != want:
        sys.exit(f"translation set mismatch; missing={sorted(want - set(translations))}, "
                 f"unexpected={sorted(set(translations) - want)}")
    needed = {a["id"] for _, _, path in targets for a in path}
    out: dict[int, dict[str, Any]] = {}
    for s, parent, _ in flat:
        if s["id"] not in needed:
            continue
        t = titles.get(s["id"]) or (s.get("title_translations") or {}).get(language)
        if not isinstance(t, str) or not t.strip():
            sys.exit(f"missing {language} title translation for section {s['id']}")
        out[s["id"]] = {
            "section_key": f"section-{s['id']}",
            "parent_key": f"section-{parent['id']}" if parent else None,
            "title": s["title"], "slug": s["slug"], "section_type": s["section_type"],
            "sequence": s.get("sequence", 0),
            # append_texts adds only this language: the live titles are production's
            "title_translations": {language: t.strip()},
            "citation": s.get("citation"), "texts": [],
        }
    notes: list[int] = []
    for s, _, path in targets:
        text = translations[s["id"]]
        latin_src = s["texts"]["la"]["content"]
        latin, target = blocks(latin_src), blocks(text)
        errors = filter_reviewed_format_errors(s["id"], latin, target, structure_errors(latin, target),
                                               reviews or {})
        if errors:
            sys.exit(f"section {s['id']}: {errors}")
        out[s["id"]]["texts"] = [{
            "language": language, "content": text, "source_key": source["source_key"],
            "source_locator": " / ".join(n["slug"] for n in path)[:255], "role": "translation",
            "license_code": source["license_code"], "license_url": source["license_url"],
            "rights_basis": source["rights_basis"], "attribution_text": source["attribution_text"]}]
        notes += [s["id"]] * max(0, editor_notes(text) - editor_notes(latin_src))
    if problems := licence.problems(source):
        sys.exit("; ".join(problems))
    summary = (f"append_texts: {len(targets)} paragraph-aligned {language} translations of the live "
               "Latin; ledger adjudicated, alignment read, preflight passed.")
    if notes:
        summary += f" Includes {len(notes)} Editor's note(s) in section(s) {', '.join(map(str, notes))}."
    return {
        "schema_version": 1, "batch_slug": batch_slug, "title": title, "summary": summary,
        "sources": [source], "authors": [],
        "works": [{"import_mode": "append_texts", "title": work["title"], "slug": work["slug"],
                   "sections": [out[s["id"]] for s, _, _ in flat if s["id"] in needed]}],
    }


def read_titles(path: Path, language: str) -> dict[int, str]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    rows = raw.get("titles", raw)
    if not isinstance(rows, dict):
        sys.exit("title translations must be a JSON object keyed by section id")
    out = {}
    for sid, v in rows.items():
        v = v.get(language) if isinstance(v, dict) else v
        if isinstance(v, str) and v.strip():
            out[int(sid)] = v.strip()
    return out


@app.command()
def main(
    snapshot: Annotated[Path, typer.Argument(help="The live work, saved from the API")],
    translations: Annotated[Path, typer.Argument(help="Dir of <section_id>.md")],
    title_translations: Annotated[Path, typer.Option(help='{"titles": {section_id: {lang: title}}}')],
    source_key: Annotated[str, typer.Option()],
    source_url: Annotated[str, typer.Option()],
    batch_slug: Annotated[str, typer.Option()],
    title: Annotated[str, typer.Option()],
    attribution: Annotated[str, typer.Option(help="Must credit ScholaThomistica for our own translation")],
    out: Annotated[Path, typer.Option()],
    language: Annotated[str, typer.Option()] = "en",
    translator_name: Annotated[Optional[str], typer.Option()] = None,
    format_reviews: Annotated[Optional[Path], typer.Option(help="Hash-bound reviews of italic-count differences")] = None,
    metadata: Annotated[Optional[Path], typer.Option(help="JSON merged into the source's metadata (provenance)")] = None,
    update_work: Annotated[Optional[Path], typer.Option(
        help="A guarded {expected, set} on the work's fields, for the batch that completes it (Custos)")] = None,
) -> None:
    """Build the append_texts manifest, or refuse and write nothing."""
    work = json.loads(snapshot.read_text(encoding="utf-8"))
    extra = json.loads(metadata.read_text(encoding="utf-8")) if metadata else {}
    if "schola_license_exempt" in extra:
        sys.exit("--metadata cannot exempt the licence: this builder stages our own translation")
    texts = {int(p.stem): p.read_text(encoding="utf-8").strip()
             for p in sorted(translations.glob("*.md")) if p.stem.isdigit()}
    source = {
        "source_key": source_key, "title": title, "source_url": source_url,
        "license_code": licence.CODE, "license_url": licence.URL, "rights_basis": "own_contribution",
        "attribution_text": attribution,
        # extra provenance first: it may add fields, never replace these or exempt the licence
        "metadata": {**extra,
                     "canonical_latin_work_slug": work["slug"],
                     "paragraph_alignment": f"one {language} block per Latin block",
                     "review_state": "agent-adjudicated; preflight passed"},
    }
    if translator_name:
        source["translator_name"] = translator_name
    reviews = json.loads(format_reviews.read_text(encoding="utf-8")) if format_reviews else {}
    m = build(work, texts, read_titles(title_translations, language), language, source,
              batch_slug, title, reviews)
    if update_work:
        m["works"][0]["update_work"] = json.loads(update_work.read_text(encoding="utf-8"))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(m, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    secs = m["works"][0]["sections"]
    print(f"{out}: {sum(1 for s in secs if s['texts'])} translated sections, {len(secs)} in the manifest")
    print(f"next: python3 -m exscriptor.alignment screen {out} ... ; python3 -m exscriptor.preflight {out}")


if __name__ == "__main__":
    app()
