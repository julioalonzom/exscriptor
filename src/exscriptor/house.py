#!/usr/bin/env python3
"""The corpus-wide house rules that code applies, so no reader has to judge them.

Three rules, each applied in the edition layer by ``expand run`` and checked
on the manifest by ``preflight``:

1. **The spelling map** (``spelling-map.tsv``, found by walking up from the
   work dir, so one reviewed map serves every work): word-initial forms the
   corpus classicizes (``charit`` -> ``carit``, ``caeter`` -> ``ceter``) and
   forms it deliberately keeps (``intellig``, ``nunquam``). Columns:
   ``form  edition  reason``. ``form`` is a word-initial prefix; a trailing
   ``$`` makes it a whole word (``quum$``). A row whose edition equals its
   form is a KEEP row: it documents a decision and, as the longest match,
   shields a longer form from a shorter change row (``coetern`` keeps
   *coeternus* while ``coeter`` -> ``ceter``). A form with a capital matches
   case-sensitively (``Sylvi`` keeps the name *Sylvius*); a lower-case form
   matches any case and the replacement takes the word's case. The map is a
   closed list: a form not in it stays as printed, whatever a reader thinks
   of it. Rows are added only by review (``candidates`` lists the forms to
   review).
2. **Stop spacing** (CC Stylebook [2.10]): no space before ``. , ; : ? !``.
3. **Quotation marks in an English translation**: “…” with ‘…’ inside, never
   the Latin's « » (``quotes`` converts a file in place).

A punctuation/case pass (``punctuation.tsv``, the editor's closed-list
revision of the print's punctuation and capitals) is applied here too: its
rows may change punctuation or letter case, never a letter.

Usage:

    python3 -m exscriptor.house screen --manifest manifests/x.json   # what the map would still change
    python3 -m exscriptor.house apply 'transcription/*.md'           # a layer expand does not build
    python3 -m exscriptor.house quotes 'translation-en/*.md'
    python3 -m exscriptor.house candidates --lexicon .cache/latin-lexicon.json
"""
from __future__ import annotations

import csv
import glob as globmod
import hashlib
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import typer
from typing_extensions import Annotated

MAP_NAME = "spelling-map.tsv"
WORD = re.compile(r"[^\W\d_]+")
# a spaced ellipsis (. . .) is not a stop
STOP_SPACE = re.compile(r"(?<=\S)(?<!\.)[ \t ]+(?=(?:[,;:?!]|\.(?! ?\.))(?:[\s*_»”’)\]]|$))")


@dataclass(frozen=True)
class Row:
    form: str
    edition: str
    whole: bool
    exact_case: bool
    reason: str

    @property
    def keep(self) -> bool:
        return self.form == self.edition


def find_map(start: Path) -> Path | None:
    """The nearest ``spelling-map.tsv`` at or above ``start``."""
    for d in [start.resolve(), *start.resolve().parents]:
        if (d / MAP_NAME).is_file():
            return d / MAP_NAME
    return None


def read_map(path: Path) -> list[Row]:
    rows, seen = [], set()
    with path.open(encoding="utf-8", newline="") as f:
        for n, rec in enumerate(csv.DictReader(f, delimiter="\t"), start=2):
            form = (rec.get("form") or "").strip()
            if not form or form.startswith("#"):
                continue
            edition = (rec.get("edition") or "").strip()
            reason = (rec.get("reason") or "").strip()
            whole = form.endswith("$")
            form = form.rstrip("$")
            if not WORD.fullmatch(form) or not WORD.fullmatch(edition) or not reason:
                raise ValueError(f"{path}:{n}: a row needs a letters-only form and edition, and a reason")
            exact = form != form.lower()
            key = (form if exact else form.lower(), whole)
            if key in seen:
                raise ValueError(f"{path}:{n}: {form!r} is listed twice")
            seen.add(key)
            rows.append(Row(form if exact else form.lower(), edition if exact else edition.lower(),
                            whole, exact, reason))
    return sorted(rows, key=lambda r: (-len(r.form), not r.whole))


def map_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]


def _recase(word: str, target: str) -> str:
    letters = [c for c in word if c.isalpha()]
    if len(letters) > 1 and all(c.isupper() for c in letters):
        return target.upper()
    if letters and letters[0].isupper():
        return target[:1].upper() + target[1:]
    return target


def respell(word: str, rows: list[Row]) -> tuple[str, Row] | None:
    """The map's edition of ``word`` and the row that decided it, or None when
    no change row applies (no row, or a KEEP row matched first)."""
    low = word.lower()
    for r in rows:
        # a name row also matches its capitals: SYLVIUS in a heading is Sylvius
        subject, form = ((word, r.form.upper() if word.isupper() else r.form) if r.exact_case
                         else (low, r.form))
        if not (subject == form if r.whole else subject.startswith(form)):
            continue
        if r.keep:
            return None
        new = _recase(word, r.edition + low[len(r.form):])
        return (new, r) if new != word else None
    return None


def _segments(text: str) -> list[tuple[bool, str]]:
    from exscriptor.expand import split_protected  # expand imports this module
    return split_protected(text)


def apply_spelling(text: str, rows: list[Row], keep: set[str] = frozenset()) -> tuple[str, list]:
    """Apply the map outside comments, metadata markers and editor's notes
    (a note quotes the print). Returns the text and (old, new, row) changes."""
    changes = []

    def sub(m):
        w = m.group(0)
        hit = None if w in keep else respell(w, rows)
        if hit is None:
            return w
        changes.append((w, hit[0], hit[1]))
        return hit[0]

    out = "".join(s if prot else WORD.sub(sub, s) for prot, s in _segments(text))
    return out, changes


def fix_spacing(text: str) -> tuple[str, int]:
    """CC [2.10]: no space before a stop (the French-style ``est :``)."""
    n = 0
    parts = []
    for prot, s in _segments(text):
        if not prot:
            s, k = STOP_SPACE.subn("", s)
            n += k
        parts.append(s)
    return "".join(parts), n


def english_quotes(text: str) -> str:
    """« » (and ‹ ›) -> “ ” at the outer level, ‘ ’ inside; the French-style
    spaces inside the marks go."""
    out, depth, skip_space = [], 0, False
    for ch in text:
        if skip_space and ch in " \u00a0\u202f":
            continue
        skip_space = False
        if ch in "«‹":
            out.append("“" if depth % 2 == 0 else "‘")
            depth += 1
            skip_space = True
        elif ch in "»›":
            depth = max(depth - 1, 0)
            while out and out[-1] in " \u00a0\u202f":
                out.pop()
            out.append("”" if depth % 2 == 0 else "’")
        else:
            out.append(ch)
    return "".join(out)


def screen(text: str, rows: list[Row], allow: set[str] = frozenset()) -> Counter:
    """``form -> edition`` pairs the map would still change in a text (its
    editor's notes, comments and link targets excluded)."""
    from exscriptor.orthography_screen import _strip
    hits: Counter = Counter()
    for w in WORD.findall(_strip(text)):
        if w in allow:
            continue
        r = respell(w, rows)
        if r:
            hits[f"{w}->{r[0]}"] += 1
    return hits


def seam_fragments(paths: list[Path]) -> dict[Path, set[str]]:
    """The word halves a page break splits: leave them as printed.

    A page that ends ``simi-`` and declares ``joins-next: hyphen``, and a next
    page that opens ``liter``, carry one word. Respelling half of it corrupts
    the assembled word (``simi-`` + ``litter``), so both halves are kept.
    """
    out: dict[Path, set[str]] = {p: set() for p in paths}
    joins: dict[Path, bool] = {}
    for p in paths:
        notes = re.search(r"<!--[^>]*joins-next:\s*hyphen[^>]*-->", p.read_text(encoding="utf-8"), re.S)
        joins[p] = bool(notes)
    for i, p in enumerate(paths):
        words = WORD.findall(p.read_text(encoding="utf-8").split("<!--", 1)[0])
        if not words:
            continue
        if joins[p]:
            out[p].add(words[-1])
        if i and joins[paths[i - 1]]:
            out[p].add(words[0])
    return out


# --- the punctuation/case pass -------------------------------------------

PUNCTUATION_RULES = {
    "cc52.2-clause": "no comma before a subject or object clause when the main verb precedes (CC [52.2])",
    "cc52.2-indirect": "no comma before indirect speech or an indirect question when the main verb precedes (CC [52.2])",
    "cc52.2-restrictive": "no comma before a restrictive relative clause after its antecedent (CC [52.2]; DArIL 1.2.6)",
    "daril-et": "no comma before the et that ends a series (DArIL 1.2.6)",
    "daril-que": "no comma before a word with enclitic -que (DArIL 1.2.6)",
    "daril-quod": "no comma before declarative quod (DArIL 1.2.6)",
    "cc52.2-dash": "a dash only where the thought is interrupted, as a spaced en dash (CC [52.2], [2.10])",
}
CASE_RULES = {
    "case-sentence": "a capital at the start of a sentence (DArIL 1.2.4)",
    "cc40.3-title": "a capital on the first word of a work's title only (CC [40.3])",
    "cc40.4-nomen-sacrum": "a capital for the nomina sacra: Deus, Dominus, Scriptura, Apostolus = Paul (CC [40.4])",
    "cc40.5-proper": "a capital for proper names and the adjectives made from them (CC [40.5])",
    "case-common": "lower case for a common noun the print capitalized (CC [40.3]-[40.5]; DArIL 1.2.4)",
}
ALNUM = re.compile(r"[^\W_]")


@dataclass(frozen=True)
class Punct:
    page: str
    find: str
    occurrence: str
    replace: str
    rule: str
    evidence: str


def _letters(s: str) -> str:
    return "".join(ALNUM.findall(s))


def check_punct(row: Punct) -> str | None:
    """Why a row is refused, or None. The pass may move punctuation or change
    letter case; it may never change a letter."""
    if row.rule in PUNCTUATION_RULES:
        if _letters(row.find) != _letters(row.replace):
            return "a punctuation rule changed a letter or its case"
    elif row.rule in CASE_RULES:
        if _letters(row.find).casefold() != _letters(row.replace).casefold() \
                or ALNUM.sub("", row.find) != ALNUM.sub("", row.replace):
            return "a case rule changed a letter or a mark"
    else:
        return f"rule {row.rule!r} is not on the closed list ({', '.join([*PUNCTUATION_RULES, *CASE_RULES])})"
    if row.find == row.replace:
        return "find and replace are the same"
    return None


def read_punctuation(path: Path) -> list[Punct]:
    """punctuation.tsv: ``page  find  occurrence  replace  rule  evidence``
    (occurrence is the n-th match of ``find`` on the edition page, or ``*``)."""
    rows, bad = [], []
    with path.open(encoding="utf-8", newline="") as f:
        for n, rec in enumerate(csv.DictReader(f, delimiter="\t"), start=2):
            row = Punct(*(rec.get(k) or "" for k in
                          ("page", "find", "occurrence", "replace", "rule", "evidence")))
            why = check_punct(row) or (None if row.evidence.strip() else "no evidence")
            if why:
                bad.append(f"{path}:{n}: {why}: {row.find!r} -> {row.replace!r}")
            rows.append(row)
    if bad:
        raise ValueError("\n".join(bad))
    return rows


def apply_punctuation(text: str, page: str, rows: list[Punct]) -> tuple[str, list, list]:
    """(text, applied rows, stale rows). A row whose ``find`` no longer occurs
    on the page is stale: the page changed under it, and the editor re-reads."""
    applied, stale = [], []
    for row in (r for r in rows if r.page == page):
        starts = [m.start() for m in re.finditer(re.escape(row.find), text)]
        if row.occurrence == "*":
            if not starts:
                stale.append(row)
                continue
            text = text.replace(row.find, row.replace)
            applied += [row] * len(starts)
        else:
            k = int(row.occurrence) - 1
            if not 0 <= k < len(starts):
                stale.append(row)
                continue
            i = starts[k]
            text = text[:i] + row.replace + text[i + len(row.find):]
            applied.append(row)
    return text, applied, stale


# --- command line --------------------------------------------------------

app = typer.Typer(add_completion=False, help="The corpus-wide house rules: spelling map, stop spacing, quotes.")


def _paths(patterns: list[str]) -> list[Path]:
    return sorted({Path(p) for g in patterns for p in (globmod.glob(g, recursive=True) or [g])
                   if Path(p).is_file()})


def _map(spelling_map: Path | None, start: Path) -> tuple[Path, list[Row]]:
    path = spelling_map or find_map(start)
    if path is None:
        raise typer.BadParameter(f"no {MAP_NAME} at or above {start}; pass --spelling-map")
    return path, read_map(path)


@app.command("screen")
def screen_cmd(
    files: Annotated[list[str], typer.Argument(help="Latin text files or globs")] = None,
    manifest: Annotated[list[Path], typer.Option(help="Manifest JSON (repeatable): its Latin texts")] = None,
    spelling_map: Annotated[Path | None, typer.Option(help=f"Default: the nearest {MAP_NAME} above")] = None,
    allow_file: Annotated[Path | None, typer.Option(help="orthography-allow.txt: tokens left as printed")] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Print {form->edition: count} as JSON")] = False,
):
    """Count what the map would still change. Exits 1 when anything would."""
    from exscriptor.orthography_screen import manifest_units, read_allow_file
    start = (manifest or [Path(f) for f in files or []] or [Path.cwd()])[0]
    _, rows = _map(spelling_map, start if start.is_dir() else start.parent)
    allow = read_allow_file(allow_file) if allow_file else set()
    hits: Counter = Counter()
    for p in _paths(files or []):
        hits += screen(p.read_text(encoding="utf-8"), rows, allow)
    for m in manifest or []:
        data = json.loads(m.read_text(encoding="utf-8"))
        for _, text in manifest_units(data, "la"):
            hits += screen(text, rows, allow)
    if as_json:
        print(json.dumps(dict(hits.most_common()), ensure_ascii=False))
    else:
        for k, n in hits.most_common():
            print(f"{n:7d}  {k}")
        print(f"{sum(hits.values())} tokens, {len(hits)} forms the map would change")
    if hits:
        raise typer.Exit(1)


@app.command("apply")
def apply_cmd(
    files: Annotated[list[str], typer.Argument(help="Latin page files or globs, rewritten in place")],
    spelling_map: Annotated[Path | None, typer.Option(help=f"Default: the nearest {MAP_NAME} above")] = None,
    allow_file: Annotated[Path | None, typer.Option(help="orthography-allow.txt: tokens left as printed")] = None,
):
    """Apply the map and stop spacing to a Latin layer ``expand`` does not
    build (a legacy ``transcription/``). Never to ``diplomatic/``."""
    from exscriptor.orthography_screen import read_allow_file
    paths = _paths(files)
    if any(p.parent.name == "diplomatic" for p in paths):
        raise typer.BadParameter("diplomatic pages record the print: the map applies in expand, not here")
    if not paths:
        raise typer.BadParameter("no files matched")
    _, rows = _map(spelling_map, paths[0].parent)
    allow = read_allow_file(allow_file) if allow_file else set()
    fragments = seam_fragments(paths)
    total, spaced = Counter(), 0
    for p in paths:
        text = p.read_text(encoding="utf-8")
        new, changes = apply_spelling(text, rows, allow | fragments[p])
        new, k = fix_spacing(new)
        spaced += k
        total.update(f"{a}->{b}" for a, b, _ in changes)
        if new != text:
            p.write_text(new, encoding="utf-8")
    print(f"{len(paths)} files: {sum(total.values())} respelled ({len(total)} forms), {spaced} stop spaces removed")


def rekey_joins(joins: dict, old: dict[str, str], new: dict[str, str], rows: list[Row],
                keep: dict[str, set[str]] | None = None) -> tuple[dict, list[str]]:
    """Carry ``assemble --join-decisions`` across a house pass.

    A join decision is bound to both pages' sha256; a house pass changes
    neither seam, only words and stop spacing. A decision is rebound when each
    of its pages is still the page it was adjudicated on, or that page with
    the house pass applied and nothing else. ``old``/``new``: {page stem: text}.
    Returns (carried decisions, problems)."""
    sha = lambda t: hashlib.sha256(t.encode("utf-8")).hexdigest()
    keep = keep or {}
    carried, problems = {}, []
    for boundary, d in joins.items():
        names = boundary.split("->")
        bound = {"left_sha256": None, "right_sha256": None}
        for side, name in zip(bound, names):
            if name not in old or name not in new:
                problems.append(f"{boundary}: {name} is missing")
                break
            if sha(old[name]) != d.get(side) and sha(new[name]) != d.get(side):
                problems.append(f"{boundary}: {name} is not the page this decision was adjudicated on")
                break
            housed = fix_spacing(apply_spelling(old[name], rows, keep.get(name, set()))[0])[0]
            if new[name] not in (old[name], housed):
                problems.append(f"{boundary}: {name} changed beyond the house pass: re-adjudicate")
                break
            bound[side] = sha(new[name])
        else:
            carried[boundary] = {**d, **bound}
    return carried, problems


@app.command("joins")
def joins_cmd(
    joins: Annotated[Path, typer.Argument(help="The assemble --join-decisions JSON, rewritten in place")],
    old_pages: Annotated[Path, typer.Option(help="The edition pages the decisions were adjudicated on (a copy)")],
    pages: Annotated[Path, typer.Option(help="The edition pages after the house pass")],
    spelling_map: Annotated[Path | None, typer.Option(help=f"Default: the nearest {MAP_NAME} above")] = None,
    allow_file: Annotated[Path | None, typer.Option(help="orthography-allow.txt: tokens left as printed")] = None,
):
    """Rebind join decisions after ``expand run`` applied the house pass; exit 1
    and change nothing if any decision's pages changed in any other way."""
    from exscriptor.orthography_screen import read_allow_file
    decisions = json.loads(joins.read_text(encoding="utf-8"))
    names = {n for b in decisions for n in b.split("->")}
    read = lambda d: {n: (d / f"{n}.md").read_text(encoding="utf-8") for n in names if (d / f"{n}.md").exists()}
    old, new = read(old_pages), read(pages)
    _, rows = _map(spelling_map, pages)
    allow = read_allow_file(allow_file) if allow_file else set()
    frags = seam_fragments(sorted(old_pages.glob("*.md")))
    keep = {p.stem: allow | f for p, f in frags.items()}
    carried, problems = rekey_joins(decisions, old, new, rows, keep)
    for p in problems:
        print("  ", p)
    if problems:
        raise typer.Exit(1)
    joins.write_text(json.dumps(carried, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{len(carried)} join decisions carried across the house pass")


@app.command("quotes")
def quotes_cmd(files: Annotated[list[str], typer.Argument(help="English translation files or globs, rewritten in place")]):
    """« » -> “ ” (‘ ’ inside) in English translation files."""
    n = 0
    for p in _paths(files):
        text = p.read_text(encoding="utf-8")
        new = english_quotes(text)
        if new != text:
            p.write_text(new, encoding="utf-8")
            n += 1
    print(f"{n} files converted")


VARIANTS = [("ae", "e"), ("oe", "e"), ("y", "i"), ("th", "t"), ("ch", "c"), ("ph", "f"),
            ("ci", "ti"), ("l", "ll"), ("t", "tt"), ("e", "ae")]


@app.command("candidates")
def candidates_cmd(
    lexicon: Annotated[Path, typer.Option(help="Corpus lexicon JSON")],
    spelling_map: Annotated[Path | None, typer.Option(help=f"Default: the nearest {MAP_NAME} above")] = None,
    floor: Annotated[int, typer.Option(help="Minimum count of the rarer form")] = 5,
    top: Annotated[int, typer.Option(help="Rows to print")] = 60,
):
    """Spelling pairs the corpus has both of and the map does not decide yet:
    the review list for new rows. Prints, never writes the map."""
    from exscriptor import lexicon as lx
    _, rows = _map(spelling_map, Path.cwd())
    lex = lx.load(lexicon)
    out = []
    for w, n in lex.items():
        if n < floor or respell(w, rows) or any(w.startswith(r.form) for r in rows if r.keep):
            continue
        for a, b in VARIANTS:
            i = w.find(a)
            if i < 0:
                continue
            alt = w[:i] + b + w[i + len(a):]
            if lex.get(alt, 0) >= floor and alt != w:
                out.append((min(n, lex[alt]), w, n, alt, lex[alt]))
    for _, w, n, alt, m in sorted(out, reverse=True)[:top]:
        print(f"{w}\t{n}\t{alt}\t{m}")


if __name__ == "__main__":
    app()
