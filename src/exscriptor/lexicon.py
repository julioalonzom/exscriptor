#!/usr/bin/env python3
"""A word-form lexicon built from the caller's own adjudicated texts.

Two jobs, both measured on a real early print before this module existed:

* **Out-of-vocabulary screen.** A misread that is not a Latin word
  (``virtuofioris``, ``viterius``, ``voluntaci``) passes every count-based
  check and is usually found only by a translator's ear. Against a lexicon of
  the corpus's own already-adjudicated Latin, it is a lookup. The screen is a
  triage list, never a verdict: proper names and genuine hapaxes are OOV too.
* **Nasal-bar expansion.** A tilde or macron over a vowel stands for an
  omitted ``m`` *or* ``n``; no positional rule decides which (word-final
  "means m" yields ``tamem`` and ``nom``). Generate both candidates per mark
  and let the lexicon decide; on one real print this settled most forms
  outright and left genuine variants (``numquam``/``nunquam``) to an edition
  policy and true garbles (``tõpus``) to the scan.

The lexicon is whatever the caller builds it from -- no word list ships with
the library. Exclude the text under examination from its own lexicon, or its
misreads become vocabulary.

Usage:

    ex-lexicon build 'corpus/**/*.json' 'corpus/**/*.la.md' --exclude '*draft*' --out lex.json
    ex-lexicon oov  'assembled/*.la.md' --lexicon lex.json
    ex-lexicon nasal 'assembled/*.la.md' --lexicon lex.json --tsv expansions.tsv
"""
from __future__ import annotations

import fnmatch
import glob as globmod
import itertools
import json
import re
import unicodedata
from collections import Counter
from pathlib import Path

import typer
from typing_extensions import Annotated

from exscriptor.orthography_screen import char_category, manifest_units

WORD_RE = re.compile(r"[^\W\d_]+")
COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
LINK_TARGET_RE = re.compile(r"\|[^\]|]*\]\]")
NASAL_MARKS = {0x0303, 0x0304, 0x0305}  # tilde, macron, overline
VOWELS = "aeiouy"

# A candidate chosen by frequency must beat the runner-up by this factor;
# anything closer is a genuine spelling variant for the edition policy.
DOMINANCE = 20


def tokens(text: str) -> list[str]:
    text = COMMENT_RE.sub(" ", text)
    text = LINK_TARGET_RE.sub("]]", text)
    return WORD_RE.findall(unicodedata.normalize("NFC", text))


def has_mark(token: str) -> bool:
    if token.isascii():
        return False
    return any(char_category(ch) == "abbrev-mark" for ch in token) or \
        any(ord(c) in NASAL_MARKS for c in unicodedata.normalize("NFD", token))


PRINT_FORM = re.compile(r"[jJ]|[qQ][vV]")


def is_print_form(token: str) -> bool:
    """A form the orthography screen fails (j, qv, accents, long s, ligatures,
    marks). Never vocabulary: a shipped text that kept one would teach the
    lexicon to 'correct' toward it."""
    if PRINT_FORM.search(token):
        return True
    if token.isascii():
        return False
    return any(char_category(ch) for ch in token) or has_mark(token)


def read_texts(patterns: list[str], exclude: list[str] | None = None,
               language: str = "la") -> list[tuple[str, str]]:
    """(label, text) for every matching .md/.txt file and every ``language``
    text in matching manifest JSON files."""
    exclude = exclude or []
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for pattern in patterns:
        for item in sorted(globmod.glob(pattern, recursive=True)) or [pattern]:
            p = Path(item)
            if not p.is_file() or str(p) in seen:
                continue
            if any(fnmatch.fnmatch(str(p), e) for e in exclude):
                continue
            seen.add(str(p))
            if p.suffix == ".json":
                try:
                    data = json.loads(p.read_text(encoding="utf-8"))
                except (ValueError, UnicodeDecodeError):
                    continue
                out.extend((f"{p}:{label}", text) for label, text in manifest_units(data, language)
                           if label.startswith("text:"))
            elif p.suffix in (".md", ".txt"):
                out.append((str(p), p.read_text(encoding="utf-8")))
    return out


def build(texts: list[str]) -> Counter:
    """Lower-cased form frequencies; texts are de-duplicated (manifest
    versions repeat the same section), print forms are never vocabulary."""
    forms: Counter = Counter()
    for text in dict.fromkeys(texts):
        for t in tokens(text):
            if not is_print_form(t):
                forms[t.lower()] += 1
    return forms


def save(forms: Counter, path: Path, sources: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"sources": sources, "tokens": sum(forms.values()),
                                "forms": dict(forms)}, ensure_ascii=False))


def load(path: Path) -> Counter:
    return Counter(json.loads(path.read_text(encoding="utf-8"))["forms"])


def oov(texts: list[str], lexicon: Counter, min_len: int = 4,
        min_count: int = 1) -> Counter:
    """Forms not in the lexicon (counted at least ``min_count`` times there).
    Tokens carrying an abbreviation mark are left to the orthography screen."""
    out: Counter = Counter()
    for text in texts:
        for t in tokens(text):
            low = t.lower()
            if len(low) < min_len or has_mark(t):
                continue
            if lexicon.get(low, 0) < min_count:
                out[low] += 1
    return out


def nasal_candidates(token: str) -> list[str] | None:
    """Every m/n reading of a token whose only marks are nasal bars over
    vowels; None if it carries any other mark."""
    slots: list[list[str]] = []
    for ch in unicodedata.normalize("NFC", token):
        base, *marks = unicodedata.normalize("NFD", ch)
        codes = {ord(m) for m in marks}
        if codes & NASAL_MARKS:
            if base.lower() not in VOWELS or codes - NASAL_MARKS:
                return None
            slots.append([base + "m", base + "n"])
        elif char_category(ch) == "abbrev-mark":
            return None
        else:
            slots.append([ch])
    if all(len(s) == 1 for s in slots):
        return None
    return ["".join(c) for c in itertools.product(*slots)]


def expand_nasal(token: str, lexicon: Counter, prefer: Counter | None = None) -> dict:
    """Decide a nasal-bar token by the lexicon.

    status: ``unique`` (one candidate is a known form), ``frequency`` (one
    dominates by DOMINANCE×), ``prefer`` (a variant tie broken by the
    ``prefer`` counts -- e.g. the edition's own spelled-out habit),
    ``variant`` (undecided genuine alternatives), ``none`` (no candidate is a
    known form: send to the scan), ``other-marks`` (not a nasal-only token).
    """
    cands = nasal_candidates(token)
    if cands is None:
        return {"token": token, "status": "other-marks", "choice": None, "candidates": {}}
    counts = {c: lexicon.get(c.lower(), 0) for c in cands}
    known = sorted((c for c in cands if counts[c]), key=lambda c: -counts[c])
    status, choice = "none", None
    if len(known) == 1:
        status, choice = "unique", known[0]
    elif len(known) > 1:
        top, second = known[0], known[1]
        if counts[top] >= DOMINANCE * counts[second]:
            status, choice = "frequency", top
        elif prefer and prefer.get(top.lower(), 0) != prefer.get(second.lower(), 0):
            choice = max(known[:2], key=lambda c: prefer.get(c.lower(), 0))
            status = "prefer"
        else:
            status = "variant"
    return {"token": token, "status": status, "choice": choice,
            "candidates": {c: counts[c] for c in cands}}


app = typer.Typer(help="Corpus lexicon: build it, screen out-of-vocabulary forms, expand nasal bars.")


@app.command("build")
def build_cmd(
    sources: Annotated[list[str], typer.Argument(help="Globs of .md/.txt files and manifest .json files")],
    out: Annotated[Path, typer.Option(help="Lexicon JSON to write")],
    exclude: Annotated[list[str], typer.Option(help="fnmatch pattern to skip (repeatable)")] = None,
    language: Annotated[str, typer.Option(help="Manifest text language")] = "la",
):
    """Build a form-frequency lexicon from adjudicated texts."""
    texts = read_texts(sources, exclude, language)
    forms = build([t for _, t in texts])
    save(forms, out, len(texts))
    print(f"{len(texts)} texts -> {len(forms)} forms, {sum(forms.values())} tokens -> {out}")


@app.command("oov")
def oov_cmd(
    sources: Annotated[list[str], typer.Argument(help="Texts to screen")],
    lexicon: Annotated[Path, typer.Option(help="Lexicon JSON")],
    min_len: Annotated[int, typer.Option(help="Ignore shorter forms")] = 4,
    min_count: Annotated[int, typer.Option(help="Lexicon count below which a form counts as unknown")] = 1,
    top: Annotated[int, typer.Option(help="Forms to print")] = 60,
    report: Annotated[Path | None, typer.Option(help="Write every OOV form (TSV: form, count)")] = None,
    language: Annotated[str, typer.Option] = "la",
):
    """List forms absent from the lexicon (a triage list, not a verdict)."""
    texts = [t for _, t in read_texts(sources, None, language)]
    lex = load(lexicon)
    found = oov(texts, lex, min_len, min_count)
    total = sum(len([w for w in tokens(t) if len(w) >= min_len]) for t in texts)
    print(f"{len(found)} OOV forms, {sum(found.values())} of {total} tokens (len>={min_len})")
    for form, n in found.most_common(top):
        print(f"  {n:5d}  {form}")
    if report:
        report.write_text("".join(f"{f}\t{n}\n" for f, n in found.most_common()), encoding="utf-8")


@app.command("nasal")
def nasal_cmd(
    sources: Annotated[list[str], typer.Argument(help="Texts carrying nasal-bar tokens")],
    lexicon: Annotated[Path, typer.Option(help="Lexicon JSON")],
    tsv: Annotated[Path | None, typer.Option(help="Write token, count, status, choice, candidates")] = None,
    language: Annotated[str, typer.Option] = "la",
):
    """Propose an expansion for every nasal-bar token, decided by the lexicon."""
    texts = [t for _, t in read_texts(sources, None, language)]
    lex = load(lexicon)
    marked = Counter(t for text in texts for t in tokens(text) if has_mark(t))
    # The edition's own spelled-out habit breaks variant ties.
    own = build(texts)
    rows = [(expand_nasal(tok, lex, own), n) for tok, n in marked.items()]
    by_status: Counter = Counter()
    for r, n in rows:
        by_status[r["status"]] += n
    print("tokens by status: " + ", ".join(f"{k}={v}" for k, v in by_status.most_common()))
    if tsv:
        lines = ["token\tcount\tstatus\tchoice\tcandidates"]
        for r, n in sorted(rows, key=lambda x: (x[0]["status"], -x[1])):
            cands = " ".join(f"{c}:{k}" for c, k in r["candidates"].items())
            lines.append(f"{r['token']}\t{n}\t{r['status']}\t{r['choice'] or ''}\t{cands}")
        tsv.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"wrote {tsv}")


if __name__ == "__main__":
    app()
