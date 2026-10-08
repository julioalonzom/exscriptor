#!/usr/bin/env python3
"""Assemble page files into section texts, failing closed on every seam.

One assembler for every work. Per-work assemblers each re-implemented the same
page loop and each rediscovered the same defects: a sentence split into two
paragraphs at a page break, a footnote whose second half became a body
paragraph, a heading welded onto the previous paragraph, an unterminated
comment that published the notes layer, a missing page joined straight across,
the commented author's text published under the commentator's name. Each is
handled here once, and each failure stops the build rather than printing a
warning someone has to notice.

Pipeline, in order:

1. **Load** the page files of a range. A missing page in the range is an
   error (never joined across). Each page's comment layer, markup and line
   structure are checked (``check_markers``); ``<!-- notes: ... -->`` (or a
   template's ``opens`` / ``formatting`` / ``catchword`` / ``folio`` comment)
   comments are harvested into the report and stripped.
2. **Join** the pages. A hyphen at a page's foot joins the word (also across
   an emphasis marker: ``testimo-*`` / ``*nio``); a page that opens on a
   heading starts a paragraph; a page that ends mid-sentence or whose next
   page opens lowercase continues the paragraph; otherwise a paragraph break.
   A page may declare ``joins-next: hyphen|space|para`` in its notes; the
   mechanical decision wins and a disagreement is reported.
   **Foot notes between the halves:** when a page ends in a run of ``^[...]``
   note blocks and the paragraph continues on the next page, the continuation
   rejoins the paragraph above the notes and the notes follow it (they never
   absorb the continuation's prose).
   **Footnote continuations:** a note cut at a page's foot carries
   ``⟦NOTE-CONTINUES⟧`` at the cut, and its continuation on the next page is a
   block opening ``⟦CONTINUED-NOTE⟧``; the continuation is fused into the note.
   An unmatched sentinel is an error.
   Optionally (``--seam-duplets``) a syllable the print repeats on both sides
   of a page break is dropped, and reported.
3. **Drop layers** the project does not publish (``layer_zones``:
   ``<<<NAME>>>`` ... ``<<<END NAME>>>``). Lines matching ``--keep`` patterns
   (the edition's own words caught inside a dropped zone) are hoisted out in
   place and reported.
4. **Edition rules** (optional): a work's ``edition_rules.py`` exposing
   ``edition(text)`` or ``apply(text)``.
5. **Renumber footnotes** 1..N in one pass (author notes ``^[N. ...`` and
   ``^[Editor's note: ...`` alike).
6. **Split** into sections by ``structure.json`` (see below). The split is
   checked to round-trip: section bodies plus removed heading lines rebuild
   the assembled text exactly, so nothing is lost or duplicated.
7. **Invariants** per section: non-empty; no sentinel ``⟦...⟧``, ``<<<``,
   ``<!--`` or ``</content>``; no soft hyphen; ``seams.seam_violations`` clean.

structure.json (the TOC, written at scouting before transcription)::

    {
      "headings": {"quaestio": "^\\*\\*QUAESTIO\\b", "articulus": "^\\*\\*ARTICULUS\\b"},
      "title_line": true,            # a bold line after a heading is its title, also removed
      "pre": "prooemium",            # section that owns text before the first heading
      "sections": [{"key": "q1", "type": "quaestio", ...}, ...]
    }

Sections whose ``type`` has a heading pattern are matched to heading lines by
type in document order; a heading that would skip a structure entry is an
error (the heading is missing from the transcription, or the map is wrong).
``"node_types": ["liber", "pars"]`` declares section types that may have no text of
their own (a book or part whose heading is followed at once by its first chapter): an
empty body is then no error and writes no file. ``"implicit_first": {"distinctio": "caput"}`` declares that the first child of
that type has no heading line of its own (a print that opens the first chapter
straight after the distinction's heading): the text after the parent's heading
belongs to that child, and the parent is a node without text. When the child's
heading follows the parent's at once, the child is matched as usual.
A range may cover part of the structure; sections outside it are not
required. Without ``--structure`` the whole range is one text.

Usage:

    python3 -m exscriptor.assemble --pages 'transcription/pg-{n:03d}.md' \\
        --range 12-85 --structure structure.json --out-dir assembled \\
        [--edition-rules edition_rules.py] [--drop-layer THOMAS] \\
        [--keep 'Conclusio\\b[^.\\n]*\\.'] [--seam-duplets]

Writes ``<out-dir>/<key>.md`` per section (or ``<out-dir>/assembled.md``) and
``<out-dir>/ASSEMBLY.json`` (pages with sha256, sections, report). Exits 1 on
any failure; nothing is written then.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import typer
from typing_extensions import Annotated

from exscriptor import check_markers, layer_zones, seams

NOTE_CONTINUES = "⟦NOTE-CONTINUES⟧"
CONTINUED_NOTE = "⟦CONTINUED-NOTE⟧"
NOTES_COMMENT = re.compile(rf"<!--\s*(?:{'|'.join(check_markers.COMMENT_KEYS)}):\s*(.*?)-->", re.S)
ANY_COMMENT = re.compile(r"<!--.*?-->", re.S)
JOINS = re.compile(r"joins-next:\s*(hyphen|space|para)\b")
FN_ANY = re.compile(r"\^\[(?:\d+\.\s*(?:Editor's note:\s)?|Editor's note:\s)")
TERMINAL = re.compile(r"[.!?…]['\"”’»)\]*_]*\s*$")
RESIDUE = {
    "sentinel ⟦…⟧": re.compile(r"⟦[^⟧]*⟧"),
    "zone marker <<<": re.compile(r"<<<"),
    "HTML comment": re.compile(r"<!--"),
    "wrapper tag": re.compile(r"</?content>"),
    "soft hyphen": re.compile("­"),
}
COMMON_WORDS = {
    "et", "non", "cum", "quam", "quod", "quia", "sed", "ut", "ad", "in", "est",
    "esse", "sunt", "tamen", "enim", "aut", "vel", "nec", "per", "ex", "de",
    "hoc", "haec", "hanc", "hic", "huic", "id", "ita", "sic", "si", "nam", "qui",
    "quae", "que", "etiam", "unde", "ergo", "autem", "atque", "nisi", "quasi",
    "tanquam", "velut", "sicut", "item", "idem",
}


class AssemblyError(Exception):
    """The build refuses: the message lists every reason."""


@dataclass
class Page:
    name: str
    n: int
    path: Path
    body: str
    notes: list[str] = field(default_factory=list)
    declared: str | None = None
    sha256: str = ""


def page_paths(pattern: str, first: int, last: int) -> tuple[list[tuple[int, Path]], list[int]]:
    """(n, path) for each existing page in the range, and the missing numbers.
    ``pattern`` is a format string over ``n``: ``'pages/p{n:03d}.md'``."""
    found, missing = [], []
    for n in range(first, last + 1):
        p = Path(pattern.format(n=n))
        (found.append((n, p)) if p.exists() else missing.append(n))
    return found, missing


def load_page(path: Path, n: int, *, check_wrap: bool = True) -> tuple[Page, list[str]]:
    raw = path.read_text(encoding="utf-8")
    name = path.stem
    problems = check_markers.comment_issues(raw, name) + check_markers.markup_issues(raw, name)
    if check_wrap:
        problems += check_markers.wrap_issues(raw, name)
    notes = [m.group(1).strip() for m in NOTES_COMMENT.finditer(raw)]
    declared = None
    for note in notes:
        m = JOINS.search(note)
        if m:
            declared = m.group(1)
    body = ANY_COMMENT.sub("", raw).strip()
    page = Page(name, n, path, body, notes, declared,
                hashlib.sha256(raw.encode("utf-8")).hexdigest())
    return page, problems


def _first_letter(s: str) -> str:
    for c in s:
        if c.isalpha():
            return c
    return ""


def join_kind(prev: str, nxt: str) -> str:
    """'hyphen' | 'space' | 'para' for a page boundary."""
    tail, head = prev.rstrip(), nxt.lstrip()
    if not tail or not head:
        return "para"
    if re.search(r"[A-Za-zÀ-ÿſ]-[*_]*$", tail):
        return "hyphen"
    if head.startswith("#"):
        return "para"
    if head.startswith("**") and not head.startswith("***"):
        first_bold_letter = _first_letter(head[2:])
        if not (first_bold_letter and first_bold_letter.islower()):
            return "para"
    first = _first_letter(head)
    if first and first.islower():
        return "space"
    stripped = re.sub(r"\^\[[^\]]*\]\s*$", "", tail).rstrip() or tail
    if not TERMINAL.search(stripped) and not stripped.endswith(":"):
        return "space"
    return "para"


def _seam_duplet(prev: str, nxt: str) -> tuple[str, str | None]:
    """Drop a fragment of 4+ letters the print repeats across the break."""
    tail = re.findall(r"([^\W\d_]{4,})\s*[.,;:]?\s*$", prev.rstrip())
    head = re.match(r"\s*([^\W\d_]{4,})", nxt)
    if tail and head and tail[-1].lower() == head.group(1).lower() \
            and tail[-1].lower() not in COMMON_WORDS:
        return nxt[head.end(1):].lstrip(), head.group(1)
    return nxt, None


def _trailing_notes(text: str) -> tuple[str, str]:
    """Split ``text`` into (body, notes): the maximal run of trailing blocks
    that open ``^[`` (a page's foot apparatus). ``notes`` is empty when the
    text does not end in such a run or is nothing but notes."""
    blocks = re.split(r"\n\s*\n", text.rstrip())
    k = len(blocks)
    while k > 0 and blocks[k - 1].lstrip().startswith("^["):
        k -= 1
    if k == 0 or k == len(blocks):
        return text.rstrip(), ""
    return "\n\n".join(blocks[:k]), "\n\n".join(blocks[k:])


def join_pages(pages: list[Page], *, duplets: bool = False) -> tuple[str, list[str], list[str]]:
    """Join page bodies. Returns (text, report lines, errors)."""
    report: list[str] = []
    errors: list[str] = []
    out = ""
    prev: Page | None = None
    for page in pages:
        body = page.body
        blocks = [b.strip() for b in re.split(r"\n\s*\n", body) if b.strip()]
        conts = [i for i, b in enumerate(blocks) if b.startswith(CONTINUED_NOTE)]
        for i in reversed(conts):
            cont = blocks.pop(i)[len(CONTINUED_NOTE):].strip()
            if NOTE_CONTINUES not in out:
                errors.append(f"{page.name}: {CONTINUED_NOTE} with no {NOTE_CONTINUES} before it")
                continue
            cut = out.rfind(NOTE_CONTINUES)
            prefix = out[:cut].rstrip()
            joiner = " "
            if prefix.endswith("-"):
                prefix = prefix[:-1]
                joiner = ""
            out = prefix + joiner + cont + out[cut + len(NOTE_CONTINUES):].lstrip(" ")
            report.append(f"{page.name}: footnote continuation fused into the note on the previous page")
        body = "\n\n".join(blocks)
        if prev is None or not out.strip():
            out = body
            prev = page
            continue
        if duplets:
            body, frag = _seam_duplet(out, body)
            if frag:
                report.append(f"{prev.name}->{page.name}: repeated seam fragment {frag!r} dropped")
        held = ""
        seam_tail = out
        if not body.lstrip().startswith("^["):
            main, notes = _trailing_notes(out)
            if notes:
                seam_tail = main
            if notes and join_kind(main, body) in ("space", "hyphen"):
                # The page ended in its foot notes and the paragraph goes on
                # on the next page: the continuation rejoins the paragraph
                # above the notes, and the notes follow it.
                out, held = main, notes
                report.append(f"{prev.name}->{page.name}: page-foot notes held until the "
                              f"continued paragraph ends")
        kind = join_kind(seam_tail, body)
        tail = out.rstrip()
        rest = ""
        if held:
            body, _, rest = body.lstrip().partition("\n\n")
        if kind == "hyphen":
            m = re.search(r"-([*_]*)$", tail)
            closing = m.group(1)
            tail = tail[:m.start()]
            head = body.lstrip()
            if closing and head.startswith(closing):
                head = head[len(closing):]
            out = tail + head
        elif kind == "space":
            out = tail + " " + body.lstrip()
        else:
            out = tail + "\n\n" + body.lstrip()
        if held:
            out = out + "\n\n" + held + (("\n\n" + rest) if rest else "")
        if prev.declared and prev.declared != kind:
            report.append(f"{prev.name}->{page.name}: declared {prev.declared}, joined as {kind}")
        prev = page
    if NOTE_CONTINUES in out:
        errors.append(f"{out.count(NOTE_CONTINUES)} {NOTE_CONTINUES} with no continuation on the next page")
    return out, report, errors


def drop_layers(text: str, zones: tuple[str, ...], keep: tuple[str, ...] = ()) -> tuple[str, list[str], list[str]]:
    """Drop marked zones; lines matching a ``keep`` pattern inside a zone are
    hoisted out in place. Returns (text, report, errors)."""
    if not zones:
        return text, [], []
    keep_res = [re.compile(k) for k in keep]
    hoisted: list[str] = []
    if keep_res:
        lines, open_name = [], None
        markers = [(z, layer_zones._marker_re(z)) for z in zones]
        for line in text.split("\n"):
            hit = next(((z, m) for z, rx in markers if (m := rx.match(line))), None)
            if hit:
                open_name = None if hit[1].group("kind") else hit[0]
                lines.append(line)
                continue
            if open_name:
                found = [m.group(0).strip() for rx in keep_res for m in rx.finditer(line)]
                if found:
                    # close the zone, emit the edition's words, reopen
                    lines += [f"<<<END {open_name}>>>", "", *found, "", f"<<<{open_name}>>>"]
                    hoisted += found
                    rest = line
                    for f in found:
                        rest = rest.replace(f, "")
                    if rest.strip():
                        lines.append(rest)
                    continue
            lines.append(line)
        text = "\n".join(lines)
    res = layer_zones.filter_layers(text, zones)
    errors = [f"layer markers: {u}" for u in res["unbalanced"]]
    report = [f"dropped {len(res['dropped_nonblank'])} lines of {', '.join(zones)}"]
    report += [f"hoisted out of a dropped zone: {h[:70]}" for h in hoisted]
    kept = re.sub(r"\n{3,}", "\n\n", res["kept"])
    return kept, report, errors


def renumber_footnotes(text: str, *, numbered_author_notes: bool = True) -> str:
    counter = 0

    def repl(m: re.Match) -> str:
        nonlocal counter
        counter += 1
        if "Editor's note" in m.group(0):
            return f"^[{counter}. Editor's note: "
        return f"^[{counter}. "

    # With unnumbered author notes, a leading numeral belongs to the citation.
    pattern = FN_ANY if numbered_author_notes else re.compile(r"\^\[(?:\d+\.\s*)?Editor's note:\s*")
    return pattern.sub(repl, text)


def load_edition_rules(path: Path):
    spec = importlib.util.spec_from_file_location(f"edition_rules_{abs(hash(str(path)))}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    fn = getattr(mod, "edition", None) or getattr(mod, "apply", None)
    if fn is None:
        raise AssemblyError(f"{path}: defines neither edition(text) nor apply(text)")
    return fn


def split_sections(text: str, structure: dict) -> tuple[dict[str, str], list[str]]:
    """Cut the text at heading lines matched to structure entries in order.
    Returns ({key: body}, errors). Round-trips by construction and by check."""
    patterns = {t: re.compile(p, re.M) for t, p in (structure.get("headings") or {}).items()}
    if not patterns:
        raise AssemblyError("structure.json has no 'headings' patterns")
    ordered = [s for s in structure["sections"] if s.get("type") in patterns]
    title_line = structure.get("title_line", False)
    heads = []
    for m in re.finditer(r"^.*$", text, re.M):
        line = m.group(0)
        typ = next((t for t, rx in patterns.items() if rx.match(line)), None)
        if typ is None:
            continue
        end = m.end()
        if title_line:
            t = re.match(r"\n\s*\n?(\*\*[^\n]+\*\*)[ \t]*(?=\n|$)", text[end:])
            if t:
                end += t.end()
        heads.append((m.start(), end, typ, line.strip()))
    errors: list[str] = []
    out: dict[str, str] = {}
    pieces: list[str] = []
    first = heads[0][0] if heads else len(text)
    pre = text[:first]
    pointer = 0
    if pre.strip():
        key = structure.get("pre")
        if not key:
            errors.append(f"{len(pre.split())} words before the first heading and no 'pre' section")
        else:
            out[key] = pre.strip()
            keys = [s["key"] for s in ordered]
            if key in keys:
                pointer = keys.index(key) + 1
    pieces.append(pre)
    for i, (start, end, typ, label) in enumerate(heads):
        found = next((j for j in range(pointer, len(ordered)) if ordered[j]["type"] == typ), None)
        if found is None:
            errors.append(f"no structure entry left for heading {label[:60]!r}")
            break
        if found > pointer and out:
            skipped = [s["key"] for s in ordered[pointer:found]]
            errors.append(f"heading {label[:60]!r} matched {ordered[found]['key']!r} but skips {skipped}")
        stop = heads[i + 1][0] if i + 1 < len(heads) else len(text)
        key = ordered[found]["key"]
        body = text[end:stop]
        pieces += [text[start:end], body]
        child = ordered[found + 1] if found + 1 < len(ordered) else None
        if (child and body.strip() and child.get("parent") == key
                and child["type"] == (structure.get("implicit_first") or {}).get(typ)):
            # The print gives the first child no heading of its own: the text
            # after the parent's heading is the child's (the parent is a node).
            key, pointer = child["key"], found + 2
        else:
            pointer = found + 1
            if not body.strip() and (typ in (structure.get("implicit_first") or {})
                                     or typ in (structure.get("node_types") or [])):
                continue  # a parent that is only a node: its first child follows at once
        out[key] = (out[key] + "\n\n" if key in out else "") + body.strip()
    if not errors and "".join(pieces) != text:
        errors.append("split does not round-trip: text lost or duplicated")
    return out, errors


def invariants(key: str, body: str) -> list[str]:
    errs = []
    if not body.strip():
        errs.append(f"{key}: empty section")
    for label, rx in RESIDUE.items():
        n = len(rx.findall(body))
        if n:
            errs.append(f"{key}: {n} × {label}")
    for idx, kind, snip in seams.seam_violations(body):
        errs.append(f"{key}: seam {kind} at block {idx}: {snip[:90]!r}")
    return errs


@dataclass
class Assembly:
    sections: dict[str, str]
    pages: list[Page]
    report: list[str]
    errors: list[str]


def assemble(pages: list[Page], *, structure: dict | None = None, zones: tuple[str, ...] = (),
             keep: tuple[str, ...] = (), edition=None, duplets: bool = False,
             numbered_author_notes: bool = True) -> Assembly:
    text, report, errors = join_pages(pages, duplets=duplets)
    text, r, e = drop_layers(text, zones, keep)
    report += r
    errors += e
    if edition is not None:
        text = edition(text)
    text = renumber_footnotes(text, numbered_author_notes=numbered_author_notes)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"
    if structure:
        sections, e = split_sections(text, structure)
        errors += e
    else:
        sections = {"assembled": text.strip()}
    for key, body in sections.items():
        errors += invariants(key, body)
    return Assembly(sections, pages, report, errors)


def parse_range(spec: str) -> tuple[int, int]:
    a, _, b = spec.partition("-")
    return int(a), int(b or a)


def main(
    pages: Annotated[str, typer.Option(help="Page path pattern over n, e.g. 'transcription/pg-{n:03d}.md'")],
    range_: Annotated[str, typer.Option("--range", help="First-last page number, e.g. 12-85")],
    out_dir: Annotated[Path, typer.Option(help="Directory for section files and ASSEMBLY.json")],
    structure: Annotated[Path | None, typer.Option(help="structure.json (TOC with heading patterns)")] = None,
    edition_rules: Annotated[Path | None, typer.Option(help="Python file exposing edition(text)")] = None,
    drop_layer: Annotated[list[str], typer.Option(help="Zone name to drop (repeatable)")] = None,
    keep: Annotated[list[str], typer.Option(help="Regex of edition text to hoist out of dropped zones")] = None,
    seam_duplets: Annotated[bool, typer.Option(help="Drop a fragment repeated across a page break")] = False,
    unnumbered_author_notes: Annotated[bool, typer.Option(help="Preserve leading citation numerals; renumber only editor notes")] = False,
    no_wrap_check: Annotated[bool, typer.Option(help="Skip the hard-wrap check (verse, tables)")] = False,
):
    """Assemble page files into section texts; refuse on any seam or shape defect."""
    first, last = parse_range(range_)
    found, missing = page_paths(pages, first, last)
    errors = [f"missing page {n}: {pages.format(n=n)}" for n in missing]
    loaded = []
    for n, p in found:
        page, problems = load_page(p, n, check_wrap=not no_wrap_check)
        loaded.append(page)
        errors += problems
    if not loaded:
        errors.append("no page files in range")
    result = None
    if not errors:
        try:
            result = assemble(
                loaded,
                structure=json.loads(structure.read_text(encoding="utf-8")) if structure else None,
                zones=tuple(drop_layer or ()), keep=tuple(keep or ()),
                edition=load_edition_rules(edition_rules) if edition_rules else None,
                duplets=seam_duplets, numbered_author_notes=not unnumbered_author_notes)
        except AssemblyError as exc:
            errors.append(str(exc))
        else:
            errors += result.errors
    if result:
        for line in result.report:
            print("  ", line)
        for page in result.pages:
            for note in page.notes:
                print(f"   note {page.name}: {note[:110]}")
    if errors:
        print(f"ASSEMBLY REFUSED: {len(errors)} problem(s)")
        for e in errors:
            print("  ", e)
        raise typer.Exit(1)
    out_dir.mkdir(parents=True, exist_ok=True)
    for key, body in result.sections.items():
        (out_dir / f"{key}.md").write_text(body.strip() + "\n", encoding="utf-8")
    record = {
        "pages": [{"name": p.name, "path": str(p.path), "sha256": p.sha256} for p in result.pages],
        "sections": {k: {"words": len(v.split()),
                         "sha256": hashlib.sha256(v.strip().encode("utf-8")).hexdigest()}
                     for k, v in result.sections.items()},
        "report": result.report,
    }
    (out_dir / "ASSEMBLY.json").write_text(json.dumps(record, ensure_ascii=False, indent=1) + "\n",
                                           encoding="utf-8")
    words = sum(s["words"] for s in record["sections"].values())
    print(f"assembled {len(result.pages)} pages -> {len(result.sections)} section(s), {words} words -> {out_dir}")


app = typer.Typer(add_completion=False)
app.command()(main)


if __name__ == "__main__":
    app()
