#!/usr/bin/env python3
"""Every pre-staging gate, run on the exact manifest that will be submitted.

A staged batch must be finished: nobody reviews it after the agent. Each gate
below exists because its defect reached production while every other check
passed. Running them by hand, from a checklist, is how one gets skipped; so
``preflight`` runs all of them on the manifest file itself and writes
``<manifest stem>.preflight.json`` beside it, bound to the file's sha256. A
submit wrapper accepts a manifest only with a passing report whose hash
matches -- edit one byte after preflight and it must run again.

Gates:

  residue      sentinels (⟦…⟧ ⟪…⟫), comments, zone markers, wrapper tags, soft
               hyphens, [illegible] / [?] / (?), TODO/TBD/FIXME, placeholder
               blocks; inline notes unclosed, doubled, nested or cut mid-word, or
               an editor's note standing in for a note's missing rest; and a
               batch title/summary that hands work to a person.
  metadata     every text has source_key, role, license_code, rights_basis;
               a transcription also has source_locator; every slug, path and
               key matches the platform's pattern (slugs a-z0-9-), and titles, loci,
               URLs and descriptions keep within its lengths.
  orthography  the Latin texts and titles carry no print letterforms
               (``orthography_screen``; ``<work>/orthography-allow.txt``).
  spelling     no form the corpus spelling map changes, and no space before a stop
               (``house``; the nearest ``spelling-map.tsv`` above the work dir).
  quotes       an English translation has “ ” and ‘ ’, never the Latin's « ».
  seams        no paragraph split or cut at a page seam, in any language
               (``seams.seam_violations``).
  parity       per section, every language has the same number of blocks,
               footnotes (``^[``) and citation links (``[[``).
  alignment    a batch carrying any translation (with the live source via
               ``--source`` when the batch has none) has a complete alignment report for its
               current text, one per translated language (``alignment check``; default
               ``<work>/alignment/<stem>.json`` and ``<stem>.<lang>.json``).
  duplicates   no block of 12 words or more occurs twice in one language: a
               section that carries its neighbour's text is clean block by block.
  source-order with a supplied source (``<work>/source-flow/*.txt``, one source
               paragraph per line, files in reading order; or ``--source-flow``),
               every transcription block matches the next source paragraph by its
               opening words: out of order, repeated, missing or foreign blocks fail.
               Companion batches approved together (a reconcile and the
               append_texts that follows it) are checked as one: ``--with``.
  title-page   no section is the title page: it is front matter, not the body.
  facsimile    a batch with a facsimile: in reading order its printed page
               numbers (labels ``p. N``) never go back, leave no page out, and
               each section's offsets rise with its pages. A blank leaf (its
               ``edition/`` page holds no text) is left out, and its gap is fine.
  facsimile-offsets  with page files (``<work>/edition/<leaf>.md``), each row's
               offset is where its leaf's opening sits in the section text
               (``exscriptor.facsimile``; ``--fix`` rewrites facsimile-manifest.json).
  print-reads  a translation's "the print reads X" note quotes an X some Latin note quotes.
  translation-avoid  no translation carries a rendering the work's calibration
               banned (``<work>/translation-avoid.tsv``: phrase<TAB>reason, matched
               case-insensitively).
  ledger       ``<work>/ledger.jsonl`` (or ``--ledger``): valid, no open row,
               and every correction present in this manifest's text.
  misreadings  with ``--lexicon`` (built without this work, else refused as info):
               a form seen once that is one letter from a form the corpus has 200+
               times is a likely misreading. A waiver holds only when its reason
               quotes ``blind read: <form>`` (a reader shown the line crop, never told
               either form, read the form itself). A printer's error is corrected
               with an editor's note, never waived. Unknown forms in general are info.

A finding that is genuinely acceptable is waived in
``<work>/preflight-waivers.json``: ``[{"gate": "seams", "finding": "<exact
finding text>", "reason": "..."}]``. Waivers are per finding, never per gate,
and appear in the report.

Usage:

    python3 -m exscriptor.preflight works/x/manifests/x-v3.json [--work-dir works/x] \\
        [--alignment ...] [--source live.json] [--ledger ...] [--lexicon .cache/latin-lexicon.json]

Exits 1 unless every gate passes.
"""
from __future__ import annotations

import datetime as dt
import difflib
import hashlib
import json
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

import typer
from typing_extensions import Annotated

from exscriptor import alignment, facsimile, house, ledger, lexicon, seams
from exscriptor.check_markers import NOTE_CUT, note_defects
from exscriptor.orthography_screen import failing, manifest_units, read_allow_file, screen_text

# XXX is also the numeral 30, and a citation marks it as one: after an
# abbreviation or a title (« qu. XXX », « *Prov.* XXX »), after a numbered
# noun (« chapters XXX », « Distinción XXX »), before a note, a stop or a list
# (« XXX^[Vers. 4.] », « XXX. Ad hoc », « XXX and LV »), or before
# « Distinction » (« in XXX Distinctione »). A placeholder XXX has none of these.
_NUMBERED = ("chapter", "chapters", "question", "questions", "cuestión", "cuestiones",
             "capítulo", "capítulos", "distinction", "distinción", "book", "libro",
             "number", "número", "lecture", "lección", "article", "artículo", "part", "parte")
XXX_PLACEHOLDER = (
    "".join(f"(?<!(?i:{w}) )" for w in _NUMBERED)
    + r"(?<![.*,] )\bXXX\b(?![.,;:)\]^])"
    + r"(?!\s+(?:and|et|y|e|ac|atque|vel|or|o)\s+[IVXLCDM]+\b)(?!\s+Distinc)"
)
# An asterisk after a space that opens nothing: an emptied italic (« ** »,
# « * * »), an italic closed after a space (« … - *^[ »), or a printed
# reference mark left beside its note (« propositum **^[ »). Markdown renders
# all of them as literal asterisks.
STRAY_ASTERISK = re.compile(r"(?<=[ \t])\*+(?=\s|[,.;:)\]]|\^\[|\[\*|$)", re.M)
RESIDUE = {
    "sentinel": re.compile(r"[⟦⟪][^⟧⟫]*[⟧⟫]"),
    "html comment": re.compile(r"<!--"),
    "zone marker": re.compile(r"<<<|>>>"),
    "wrapper tag": re.compile(r"</?content>"),
    "soft hyphen": re.compile("­"),
    "uncertainty mark": re.compile(r"\[illegible|\[\?\]|\(\?\)", re.I),
    "todo": re.compile(r"\b(?:TODO|TBD|FIXME)\b|" + XXX_PLACEHOLDER),
    "placeholder": re.compile(r"\[(?:Block|Translation|Paragraph) \d+[^\]]*\]"),
    "stray asterisk": STRAY_ASTERISK,
    # an italic span that swallows a paragraph numeral (« 1*. Ratio …* »,
    # « *27.* Ad »): rendered as a literal asterisk or an unnumbered paragraph
    "italic numeral": re.compile(r"^(?:\d+\*\.|\*\d+\.\*)\s", re.M),
    # a note cut at the page foot whose continuation was never joined (« ap-] »),
    # or an editor's note standing in for the missing rest
    "note cut mid-word": NOTE_CUT,
    "unfinished note": re.compile(r"Editor['’]s note:[^\]]*?(?:no continuation|ends the note here|"
                                  r"note (?:is )?(?:cut|truncated))", re.I),
}
# A space before a mark of punctuation (« sine causa ; tum »). Latin only:
# French sets a space before ; : ! ? by rule.
SPACE_BEFORE = re.compile(r"(?<=[^\s\"'“‘«(\[{—–-])[ \t]+[,;:!?](?=\s|$)", re.M)
HANDOFF = re.compile(r"\b(?:TODO|TBD|needs? (?:Julio|(?:human )?review)|for (?:Julio|the human)|"
                     r"flagged for|left for a later|later pass|fix (?:it )?in the UI|spot-check)\b", re.I)
FOOTNOTE = re.compile(r"\^\[")
# The one note allowed in one language only (schola-translate, "Footnotes"):
# parity counts the print's apparatus, not the editor's.
EDITORIAL = re.compile(r"\^\[(?:Editor(?:'|’)s|Editorial) note")
LINK = re.compile(r"(?<!\^)\[\[")  # « ^[[haec …] » is a note opening on a bracket


def sections_by_key(manifest) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = defaultdict(dict)
    for key, lang, content in ledger.manifest_texts(manifest):
        out[key][lang] = content
    return out


def text_records(manifest):
    """Every text object (dict) in the manifest with its section key."""
    return ledger.per_work(manifest, _records)


def _records(manifest):
    def walk(node, key=""):
        if isinstance(node, dict):
            if node.get("op") == "put_text":
                yield ledger.put_text_key(node), node
                return
            key = node.get("section_key") or node.get("slug") or str(node.get("id") or "") or key
            texts = node.get("texts")
            if isinstance(texts, list):
                for t in texts:
                    if isinstance(t, dict):
                        yield key, t
            for k, v in node.items():
                if k != "texts":
                    yield from walk(v, key)
        elif isinstance(node, list):
            for v in node:
                yield from walk(v, key)
    yield from walk(manifest)


def gate_residue(manifest) -> list[str]:
    out = []
    for key, langs in sections_by_key(manifest).items():
        for lang, content in langs.items():
            checks = {**RESIDUE, "space before punctuation": SPACE_BEFORE} if lang == "la" else RESIDUE
            for label, rx in checks.items():
                n = len(rx.findall(content))
                if n:
                    m = rx.search(content)
                    out.append(f"{key} [{lang}]: {n} × {label} near {content[max(0, m.start() - 30):m.end() + 30]!r}")
            for kind, at in note_defects(content):
                out.append(f"{key} [{lang}]: {kind} inline note near {content[max(0, at - 30):at + 50]!r}")
    if isinstance(manifest, dict):
        for field in ("title", "summary"):
            v = manifest.get(field)
            if isinstance(v, str) and HANDOFF.search(v):
                out.append(f"batch {field} hands work to a person: {HANDOFF.search(v).group(0)!r}")
    return out


# The platform's identifier patterns (corpus_import schema): a batch that
# breaks one is refused at submission, after every other gate has passed.
SLUG = re.compile(r"^[a-z0-9-]+$")
SLUG_PATH = re.compile(r"^[a-z0-9-]+(/[a-z0-9-]+)*$")
KEY = re.compile(r"^[a-z0-9][a-z0-9._:-]*$")
ID_PATTERNS = {"slug": SLUG, "author_slug": SLUG, "duplicate": SLUG, "section_path": SLUG_PATH,
               "parent_path": SLUG_PATH, "section_key": KEY, "parent_key": KEY,
               "source_key": KEY, "author_key": KEY}
MAX_LEN = {"title": 500, "original_title": 500, "canonical_locus": 500, "commented_locus": 500,
           "source_url": 1000, "license_url": 1000, "description": 10000}


def identifier_findings(node, where="") -> list[str]:
    out = []
    if isinstance(node, dict):
        where = node.get("section_key") if isinstance(node.get("section_key"), str) else where
        for k, v in node.items():
            pat = ID_PATTERNS.get(k)
            if pat and isinstance(v, str) and not pat.match(v):
                out.append(f"{where or 'batch'} {k} {v!r} is not {pat.pattern}")
            elif k in MAX_LEN and isinstance(v, str) and len(v) > MAX_LEN[k]:
                out.append(f"{where or 'batch'} {k} is {len(v)} characters, over the platform's {MAX_LEN[k]}")
            elif isinstance(v, (dict, list)):
                out += identifier_findings(v, where)
    elif isinstance(node, list):
        for v in node:
            out += identifier_findings(v, where)
    return out


def gate_metadata(manifest) -> list[str]:
    out = identifier_findings(manifest)
    for key, t in text_records(manifest):
        lang = t.get("language")
        if t.get("op") == "put_text" and t.get("expected_text_id"):
            continue  # a replacement inherits the live text's provenance
        missing = [f for f in ("language", "source_key", "role", "license_code", "rights_basis")
                   if not t.get(f)]
        if t.get("role") == "transcription" and not t.get("source_locator"):
            missing.append("source_locator")
        if missing:
            out.append(f"{key} [{lang}]: missing {', '.join(missing)}")
    # The platform warns on this: the edition's year is what makes the claim checkable.
    for src in manifest.get("sources", []):
        if src.get("rights_basis") == "public_domain_edition" and not src.get("publication_year"):
            out.append(f"source {src.get('source_key')}: public_domain_edition without publication_year "
                       "(the year of the edition transcribed)")
    return out


def gate_orthography(manifest, allow: set[str], language: str = "la") -> list[str]:
    out = []
    for label, text in manifest_units(manifest, language):
        bad = failing(screen_text(text, allow))
        for cat, counter in sorted(bad.items()):
            ex = ", ".join(f"{t}×{n}" for t, n in counter.most_common(5))
            out.append(f"{label}: {cat}: {ex}")
    return out


def gate_spelling(manifest, rows, allow: set[str], language: str = "la") -> list[str]:
    """Forms the corpus spelling map changes, or a space before a stop,
    left in the text (the work's edition was built without the map)."""
    out = []
    for label, text in manifest_units(manifest, language):
        hits = house.screen(text, rows, allow) if rows else Counter()
        if hits:
            ex = ", ".join(f"{k}×{n}" for k, n in hits.most_common(5))
            out.append(f"{label}: {sum(hits.values())} form(s) the spelling map changes: {ex}. "
                       "Re-run `expand run` (or `python3 -m exscriptor.house apply` on a legacy "
                       "transcription/ layer) and rebuild; for an edit batch over live text, apply "
                       "it to the live snapshot and rebuild with build_edit_manifest.py")
        spaced = house.fix_spacing(text)[1]
        if spaced:
            out.append(f"{label}: {spaced} space(s) before a stop (CC [2.10]). Re-run `expand run` "
                       "(or `python3 -m exscriptor.house apply`) and rebuild")
    return out


def gate_quotes(manifest) -> list[str]:
    """An English translation uses English quotation marks, never « »."""
    out = []
    for key, langs in sections_by_key(manifest).items():
        text = langs.get("en") or ""
        n = sum(text.count(c) for c in "«»‹›")
        if n:
            out.append(f"{key} en: {n} Latin quotation mark(s) « ». Run `python3 -m exscriptor.house "
                       "quotes` on the translation-en/ files and rebuild")
    return out


def gate_seams(manifest) -> list[str]:
    out = []
    for key, langs in sections_by_key(manifest).items():
        for lang, content in langs.items():
            for idx, kind, snip in seams.seam_violations(content):
                out.append(f"{key} [{lang}] block {idx + 1}: {kind}: {snip[:90]!r}")
            for idx, kind, snip in seams.note_violations(content):
                out.append(f"{key} [{lang}] block {idx + 1}: {kind}: {snip[:90]!r}")
    return out


def parity(langs: dict[str, str]) -> list[str]:
    """Block, footnote and link counts that differ across one section's languages."""
    out = []
    for label, measure in (("blocks", lambda c: len(alignment.blocks(c))),
                           ("footnotes", lambda c: len(FOOTNOTE.findall(c)) - len(EDITORIAL.findall(c))),
                           ("links", lambda c: len(LINK.findall(c)))):
        counts = {lang: measure(c) for lang, c in langs.items()}
        if len(set(counts.values())) > 1:
            out.append(f"{label} differ: " + ", ".join(f"{l}={n}" for l, n in sorted(counts.items())))
    return out


def gate_parity(manifest, sources: list[dict] = ()) -> list[str]:
    """``sources``: the live texts a translation-only batch is read against
    (``--source``), so its notes are counted against the Latin it pairs with."""
    secs = sections_by_key(manifest)
    for doc in sources:
        for key, langs in sections_by_key(doc).items():
            if key in secs:
                for lang, content in langs.items():
                    secs[key].setdefault(lang, content)
    return [f"{key}: {d}" for key, langs in secs.items()
            if len(langs) > 1 for d in parity(langs)]


def gate_alignment(manifest, reports, sources: list[dict], source_language: str = "la") -> list[str]:
    """One alignment report per translated language (« <stem>.json » or
    « <stem>.<lang>.json »): a batch carrying en and es needs both."""
    # Only a TRANSLATION is aligned to a source; an original text in another
    # language (a modern introduction) has nothing to pair with.
    # A reconcile's corrected translation has role « correction »: a language
    # is a target when it carries translations and is not a source language.
    # A correction of the source language itself (an edit to a text with no
    # provenance to inherit) is never a target.
    records = [t for _, t in text_records(manifest) if t.get("language")]
    originals = {source_language} | {t["language"] for t in records
                                     if t.get("role") in ("transcription", "source_text")}
    targets = sorted({t["language"] for t in records if t.get("role") == "translation"} |
                     {t["language"] for t in records
                      if t.get("role") == "correction" and t["language"] not in originals})
    if not targets:
        return []
    if isinstance(reports, (str, Path)) or reports is None:
        reports = [reports] if reports else []
    by_target = {}
    for path in reports:
        if path is not None and Path(path).exists():
            rep = json.loads(Path(path).read_text(encoding="utf-8"))
            by_target[rep.get("target")] = rep
    out = []
    for target in targets:
        rep = by_target.get(target)
        if rep is None and not alignment.pairs_by_section(manifest, "la", target, sources):
            continue  # a reconcile that changes nothing in this language
        if rep is None:
            out.append(f"batch carries {target!r} and no alignment report for it among "
                       f"{[str(p) for p in reports] or 'none'} "
                       f"(python3 -m exscriptor.alignment screen ... --target {target})")
            continue
        pairs = alignment.pairs_by_section(manifest, rep.get("source_language", "la"), target, sources)
        out += alignment.check(pairs, rep)
    return out


def section_slugs(manifest) -> dict[tuple[str | None, str], str]:
    """{(work slug, section slug): manifest key}, plus (None, slug) when the
    slug is unambiguous; keys are qualified as in a multi-work manifest."""
    works = manifest.get("works") if isinstance(manifest, dict) else None
    if not isinstance(works, list):
        return {}
    out: dict = {}
    seen: dict = {}
    for w in works:
        for s in w.get("sections") or []:
            if not (isinstance(s, dict) and s.get("slug") and s.get("section_key")):
                continue
            key = f"{w.get('slug')}/{s['section_key']}" if len(works) > 1 else s["section_key"]
            out[(w.get("slug"), s["slug"])] = key
            seen.setdefault(s["slug"], set()).add(key)
    out.update({(None, slug): next(iter(keys)) for slug, keys in seen.items() if len(keys) == 1})
    return out


NOTE_OPEN = "^["


def strip_notes(text: str) -> str:
    """Text without its inline notes (« ^[…] », brackets nested)."""
    out, i, depth = [], 0, 0
    while i < len(text):
        if depth == 0 and text.startswith(NOTE_OPEN, i):
            depth, i = 1, i + 2
            continue
        if depth:
            depth += {"[": 1, "]": -1}.get(text[i], 0)
        else:
            out.append(text[i])
        i += 1
    return "".join(out)


def words(text: str) -> list[str]:
    """Lowercased words of a block, notes and markup ignored."""
    return re.findall(r"[^\W_]+", strip_notes(text).lower())


DUPLICATE_MIN_WORDS = 12


def gate_duplicates(manifest) -> list[str]:
    seen: dict[tuple[str, str], str] = {}
    out = []
    for key, lang, content in ledger.manifest_texts(manifest):
        for i, block in enumerate(alignment.blocks(content)):
            w = words(block)
            if len(w) < DUPLICATE_MIN_WORDS:
                continue
            k = (lang, " ".join(w))
            if k in seen:
                out.append(f"{key} [{lang}] block {i + 1} repeats {seen[k]}: {block[:80]!r}")
            else:
                seen[k] = f"{key} block {i + 1}"
    return out


def read_source_flow(paths) -> list[str]:
    """Source paragraphs in reading order: files given, or a directory's
    ``*.txt`` in name order; one paragraph per non-empty line."""
    files: list[Path] = []
    for p in map(Path, paths):
        files += sorted(p.glob("*.txt")) if p.is_dir() else [p]
    return [line for f in files for line in f.read_text(encoding="utf-8").splitlines() if line.strip()]


SOURCE_KEY_WORDS = 8


def gate_source_order(manifest, flow: list[str], language: str = "la") -> list[str]:
    """Every transcription block, in manifest order, is the next paragraph of
    the supplied source, matched by its opening words.

    A source line skipped between two matched blocks must be accounted for:
    a label in capitals (« SECTIO II », « PROOEMIUM »), or present in the batch
    as a title, a note or inside a block, with or without a leading label and
    numeral (« SECTIO II Utrum … » against the title « Utrum … »). A short
    line is no exception: a dropped marginal is two or three words.

    An edit batch replaces some texts, not the work: each of its texts is
    checked on its own, and the source between them is not missing."""
    if not flow:
        return []
    partial = any(w.get("import_mode") == "edit" for w in manifest.get("works") or [])
    src = [words(line) for line in flow]
    index: dict[tuple[str, ...], list[int]] = defaultdict(list)
    for j, w in enumerate(src):
        index[tuple(w[:SOURCE_KEY_WORDS])].append(j)
    texts = [(k, c) for k, lang, c in ledger.manifest_texts(manifest) if lang == language]
    titles = [str(t) for t in _titles(manifest)]
    whole = " " + " ".join(" ".join(words(x)) for x in titles + [c for _, c in texts]
                           + re.findall(r"\^\[([^\]]*)\]", " ".join(c for _, c in texts))) + " "

    def covered(k: int) -> bool:
        w, line = src[k], flow[k].strip()
        if not w or (len(w) <= 2 and line == line.upper()):
            return True
        return f" {' '.join(w)} " in whole or (len(w) > 3 and f" {' '.join(w[2:])} " in whole)

    def find(w: list[str], cursor: int, used: dict) -> int | None:
        hits = index.get(tuple(w[:SOURCE_KEY_WORDS]))
        if not hits:   # a reading corrected inside the opening words
            head = w[:12]
            hits = [j for j, s in enumerate(src)
                    if s and difflib.SequenceMatcher(None, s[:12], head).ratio() >= 0.75]
        if not hits:
            return None
        return next((j for j in hits if j > cursor and j not in used),
                    next((j for j in hits if j not in used), hits[0]))

    out, used, cursor = [], {}, -1
    for key, content in texts:
        if partial:
            cursor = -1
        for i, block in enumerate(alignment.blocks(content)):
            w = words(block)
            if len(w) < 4:
                continue
            where = f"{key} block {i + 1}"
            j = find(w, cursor, used)
            if j is None:
                out.append(f"{where}: not in the source: {block[:70]!r}")
                continue
            if j in used:
                out.append(f"{where}: repeats source paragraph {j + 1}, already at {used[j]}: {block[:60]!r}")
            elif j < cursor:
                out.append(f"{where}: out of order, source paragraph {j + 1} after {cursor + 1}: {block[:60]!r}")
            else:
                if cursor >= 0:
                    out += [f"source paragraph {k + 1} missing before {where}: {flow[k][:70]!r}"
                            for k in range(cursor + 1, j) if not covered(k)]
                cursor = j
            used.setdefault(j, where)
    return out


def _sections(node):
    if isinstance(node, dict):
        if "section_key" in node or "section_type" in node:
            yield node
        for k, v in node.items():
            if k != "texts":
                yield from _sections(v)
    elif isinstance(node, list):
        for v in node:
            yield from _sections(v)


def with_companions(manifest, companions: list) -> dict:
    """One manifest out of batches staged together: the fullest tree, with
    every other batch's texts added to its sections (by key, else slug)."""
    if not companions:
        return manifest
    batches = [manifest, *companions]
    tree = max(batches, key=lambda m: sum(1 for _ in _sections(m)))
    merged = json.loads(json.dumps(tree))
    index = {}
    for sec in _sections(merged):
        for k in (sec.get("section_key"), sec.get("slug")):
            if k:
                index.setdefault(k, sec)
    for m in batches:
        if m is tree:
            continue
        for sec in _sections(m):
            target = index.get(sec.get("section_key")) or index.get(sec.get("slug"))
            if target is None:
                raise ValueError(f"companion section {sec.get('section_key') or sec.get('slug')} "
                                 "is not in the fullest batch's tree")
            target.setdefault("texts", []).extend(json.loads(json.dumps(sec.get("texts") or [])))
    return merged


# « p. 12 », or « t. II, p. 12 » in a multi-volume work: each volume numbers anew.
PAGE_LABEL = re.compile(r"^(?:(?P<vol>[^,]+),\s*)?p\.\s*(?P<n>\d+)$")


def blank_leaves(work_dir: Path) -> set[str]:
    """Leaves whose edition page holds no text (comments, and the layers the
    assembly drops, aside): blank pages, or a verso with only an owner's mark."""
    pages = work_dir / "edition"
    if not pages.is_dir():
        return set()
    record = work_dir / "assembled" / "ASSEMBLY.json"
    zones = json.loads(record.read_text(encoding="utf-8")).get("drop_layers", []) if record.exists() else []
    drop = [re.compile(rf"<<<{re.escape(z)}>>>.*?<<<END {re.escape(z)}>>>", re.S) for z in zones]

    def text(p):
        t = re.sub(r"<!--.*?-->", "", p.read_text(encoding="utf-8"), flags=re.S)
        for rx in drop:
            t = rx.sub("", t)
        return t.strip()
    return {p.stem for p in pages.glob("*.md") if not text(p)}


def _leaves_between(a: str, b: str) -> set[str]:
    """The leaf stems strictly between two filenames (``pg-183.jpg``, ``pg-185.jpg`` -> {pg-184})."""
    ma, mb = (re.fullmatch(r"(.*?)(\d+)", Path(f).stem) for f in (a, b))
    if not (ma and mb) or ma[1] != mb[1]:
        return set()
    width = len(ma[2])
    return {f"{ma[1]}{k:0{width}d}" for k in range(int(ma[2]) + 1, int(mb[2]))}


def gate_facsimile(manifest, blank: set[str] = frozenset()) -> list[str]:
    """Pages in reading order: no step back, no gap, offsets rising per
    section from 0 (a first page at a later offset leaves the opening on none).

    A page may be listed twice in a row (it ends one section and opens the
    next); a page listed earlier than its predecessor, or a page number
    skipped, is what a facsimile aligned against the wrong text looks like.
    A volume prefix (« t. II, p. 1 ») starts the count again. A blank leaf
    (``blank``, from ``blank_leaves``) is no page of the work: its row is
    refused, and the gap it leaves is not."""
    out = []
    for w in manifest.get("works") or []:
        rows = w.get("facsimile") or []
        order = {}
        for r in rows:
            order.setdefault(r.get("section_path"), len(order))
        rows = sorted(rows, key=lambda r: (order[r.get("section_path")], r.get("sequence") or 0))
        prev = vol = prev_file = None
        last_offset: dict = {}
        for r in rows:
            where = f"{r.get('section_path')} {r.get('page_label')}"
            off, path = r.get("text_offset"), r.get("section_path")
            if Path(str(r.get("filename"))).stem in blank:
                out.append(f"{where}: {r.get('filename')} is a blank leaf: leave it out of the facsimile")
            if path not in last_offset and off:
                out.append(f"{where}: the section's first page starts at offset {off}: its opening is on no page")
            if off is not None and last_offset.get(path) is not None and off < last_offset[path]:
                out.append(f"{where}: offset {off} before the previous page's {last_offset[path]}")
            if off is not None:
                last_offset[path] = off
            m = PAGE_LABEL.match(str(r.get("page_label") or "").strip())
            if not m:
                continue
            n = int(m.group("n"))
            if m.group("vol") != vol:
                prev, vol = None, m.group("vol")
            if prev is not None and n < prev:
                out.append(f"{where}: page {n} after page {prev} in reading order")
            elif prev is not None and n > prev + 1:
                skipped = _leaves_between(prev_file, r.get("filename")) if prev_file else set()
                if not (skipped and len(skipped) == n - prev - 1 and skipped <= blank):
                    gap = f"{prev + 1}" if n == prev + 2 else f"{prev + 1}-{n - 1}"
                    out.append(f"{where}: no row for p. {gap}")
            if prev is None or n >= prev:
                prev_file = r.get("filename")
            prev = n if prev is None else max(prev, n)
    return out


TITLE_PAGE = re.compile(r"(titulus|title[- ]?page|frontispi\w*)", re.I)


def gate_title_page(manifest) -> list[str]:
    """The title page is front matter, not the work's body (Julio, 2026-10-30)."""
    out = []
    for w in manifest.get("works") or []:
        for s in w.get("sections") or []:
            key = s.get("section_key") or s.get("slug") or ""
            if TITLE_PAGE.fullmatch(key) or TITLE_PAGE.fullmatch(str(s.get("title") or "").strip()):
                out.append(f"{key}: a title-page section. The title page is front matter, not the work's "
                           "body: drop it (its edition, place and year belong in the source record)")
    return out


def gate_guillemets(manifest) -> list[str]:
    """Every « closes. A print that opens each line of a quotation with « leaves
    marks the diplomatic contract drops (§5); one kept reads as a quote that
    never closes, and breaks the English conversion (Billot 1906, 19 sites)."""
    from exscriptor.house import english_quotes
    out = []
    for w in manifest.get("works") or []:
        for s in w.get("sections") or []:
            for t in s.get("texts") or []:
                try:
                    english_quotes(t.get("content") or "")
                except ValueError as e:
                    out.append(f"{s.get('section_key')} [{t.get('language')}]: {str(e).split(':')[0]}: drop the "
                               "line-start repetition marks in the page files (diplomatic §5), or place a lost one")
    return out


STRUCTURE_LABEL = re.compile(r"\b(?:[A-Z]{0,3}SECTIO|DISP[UV]TATIO|QU?AESTIO|ARTICULUS|CAPUT|LIBER|LECTIO|"
                             r"TRACTATUS|LIBELLUS|PARS)\s+[IVXLCDM]+\b\.?", re.I)
HEADING_BLOCK = re.compile(r"\*\*[^*\n]+\*\*")


def gate_structure(manifest) -> list[str]:
    """The printed hierarchy is in the sections, not in their text (Hurtado 1624, pilot 3):
    no section is an empty shell, no heading stands as a line of text, no title holds two
    headings, and no two siblings carry the same label (Summulae and Logica each have a
    Disputatio I: they need their book as parent)."""
    out = []
    for w in manifest.get("works") or []:
        secs = w.get("sections") or []
        parents = {s.get("parent_key") for s in secs}
        labels: dict[tuple, str] = {}
        sequences: dict[tuple, str] = {}
        for s in secs:
            key = s.get("section_key") or s.get("slug") or ""
            # The server refuses siblings that share a sequence (pilot 3: Logica's sectiones all 1).
            if s.get("sequence") is not None:
                k = (s.get("parent_key"), s["sequence"])
                if k in sequences:
                    out.append(f"{key}: same sequence {s['sequence']} as its sibling {sequences[k]}: "
                               "number siblings in print order in structure.json, or leave sequence out")
                else:
                    sequences[k] = key
            texts = [t for t in s.get("texts") or [] if (t.get("content") or "").strip()]
            title_text = str(s.get("title") or "").strip()
            section_type = str(s.get("section_type") or "").lower()
            toc = section_type in {"toc", "contents", "table_of_contents"} or bool(
                re.fullmatch(r"(?:table of contents|contents|tabula (?:contentorum|materiarum)|index capitulorum)", title_text, re.I))
            is_index = section_type == "index" or bool(re.match(r"^index\b", title_text, re.I))
            locator_list = False
            if is_index:
                for t in texts:
                    blocks = [b.strip() for b in alignment.blocks(t["content"]) if b.strip()]
                    locators = sum(bool(re.search(r"\b\d{1,4}[.\s*]*$", b)) for b in blocks)
                    all_text = t["content"]
                    numbers = len(re.findall(r"\b\d{1,4}\b", all_text))
                    words = len(re.findall(r"[^\W\d_]+", all_text, re.UNICODE))
                    if ((len(blocks) >= 10 and locators * 2 >= len(blocks))
                            or (re.search(r"\b(?:sententiarum|rerum|materiarum|locorum|verborum|"
                                          r"nominum|copiosissimus)\b", title_text, re.I)
                                and numbers >= 10 and numbers * 100 >= words * 7)):
                        locator_list = True
                        break
            if toc or locator_list:
                out.append(f"{key}: printed navigation list in the reader body: exclude the contents or "
                           "page-locator index from the section tree and rebuild; retain substantive text")
            if not texts and key not in parents and w.get("import_mode") != "update_metadata":
                out.append(f"{key}: no text and no subsections: drop the section, or give it what the print has under it")
            for t in texts:
                for i, block in enumerate(alignment.blocks(t["content"])):
                    b = block.strip()
                    if HEADING_BLOCK.fullmatch(b) and STRUCTURE_LABEL.match(b.strip("*")):
                        out.append(f"{key} [{t.get('language')}] block {i + 1} is a heading, not text: "
                                   f"{b[:70]!r}. Make it a section (structure.json) and rebuild")
            title = str(s.get("title") or "")
            found = STRUCTURE_LABEL.findall(title)
            if len(found) > 1:
                out.append(f"{key}: one title holds two headings {found}: the second is a section of its own")
            if found and title.lstrip().upper().startswith(found[0].upper()):
                label = re.sub(r"\W+", " ", found[0]).strip().upper()
                k = (s.get("parent_key"), label)
                if k in labels:
                    out.append(f"{key}: sibling of {labels[k]} with the same label {found[0]!r}: the print groups "
                               "them under different parents (a book, a part): give each its printed parent")
                else:
                    labels[k] = key
    return out


LONG_S_MIN, LONG_S_SHARE = 30, 0.1
MEDIAL_S = re.compile(r"(?<=[a-zæœ])s(?=[a-zæœ])")


BLIND_READ = re.compile(r"blind read:\s*(\S+?)[;,.]?(?:\s|$)", re.I)


def blind_read_is(form: str, reason: str) -> bool:
    """A misreadings waiver holds only when it quotes a blind read (a reader
    shown the line crop, never told either form) that gives the form itself.
    A reader told the form confirms it (Hurtado, p3-007)."""
    m = BLIND_READ.search(reason)
    return bool(m) and reads_as(m.group(1), form)


def site_reading_files(work_dir: Path) -> list[Path]:
    """Every run of exscriptor.gemini_sites under tmp/ (it writes jobs.json beside its readings):
    a run kept outside one fixed path was never reconciled (Hurtado p3-018: spiritalis)."""
    return sorted(p for p in (work_dir / "tmp").glob("**/readings.jsonl") if (p.parent / "jobs.json").is_file())


def site_pages(work_dir: Path) -> dict[str, str]:
    """Each page's diplomatic reading and its edition together: the reader gives the print's
    form (primę, authores), the edition may modernize it."""
    out: dict[str, str] = {}
    for d in ("diplomatic", "edition"):
        for p in (work_dir / d).glob("*.md"):
            out[p.stem] = out.get(p.stem, "") + "\n" + p.read_text(encoding="utf-8")
    return out


def _reading_rows(paths) -> list[dict]:
    paths = [paths] if isinstance(paths, Path) else paths
    return [json.loads(l) for p in paths if p.is_file() for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def _plain(s: str) -> str:
    s = "".join(c for c in unicodedata.normalize("NFD", s.lower()) if not unicodedata.combining(c))
    for a, b in (("ſ", "s"), ("æ", "ae"), ("œ", "oe"), ("v", "u"), ("j", "i")):
        s = s.replace(a, b)
    return re.sub(r"[^\w]", "", s)


def reads_as(word: str, form: str) -> bool:
    """Does a blind reading give this edition form? Case, ſ, ligatures, u/v, i/j, hyphens and
    stops fold; an accented or barred vowel may stand for the vowel plus m/n (the nasal stroke)."""
    pat = ""
    for ch in unicodedata.normalize("NFD", word):
        if unicodedata.combining(ch):
            pat += "[mn]?"
        elif ch.isalnum():
            pat += re.escape(_plain(ch))
    return re.fullmatch(pat, _plain(form)) is not None


def site_readings(paths) -> dict[str, list[str]]:
    """The hard-site reader's words, by the edition form each site flagged."""
    out: dict[str, list[str]] = {}
    for r in _reading_rows(paths):
        if r.get("found") and r.get("edition") and r.get("word"):
            out.setdefault(_plain(r["edition"]), []).append(r["word"])
    return out


def _site_position(line: str, word: str, page: str) -> tuple[int, str] | None:
    """(index, word) on the page where a line of print puts ``word``: the line's other words
    anchor it, so a word printed twice on the page is checked at its own spot. None when the
    line does not place it on the page once."""
    def toks(t):
        return [_plain(w) for w in re.findall(r"[^\W\d_]+(?:-[^\W\d_]+)?", t)]
    page = re.sub(r"-[ \t]*\n\s*", "", re.sub(r"<!--.*?-->|\^\[[^\]]*\]", " ", page, flags=re.S))
    lt, pt, w = toks(line), toks(page), _plain(word)
    if w not in lt:
        return None
    i = lt.index(w)
    scores = [sum(1 for k, t in enumerate(lt) if k != i and 0 <= j - i + k < len(pt) and pt[j - i + k] == t)
              for j in range(len(pt))]
    best = max(scores, default=0)
    return (scores.index(best), pt[scores.index(best)]) if best >= 2 and scores.count(best) == 1 else None


def unreconciled_sites(paths, texts: list[str], pages: dict[str, str] | None = None,
                       diplomatic: dict[str, str] | None = None) -> list[str]:
    """Every site the reader read lands in the batch: its word in the text, or named in the
    editor's note that corrects it. Otherwise the reading was overruled silently (Hurtado
    p3-013: the reader gave ſiſti; the page said conſiſti, then conſiſtit 'from the context')."""
    from exscriptor.expand import QUE_MARK
    def words(text):
        return {_plain(t) for t in re.findall(r"[^\W\d_]+(?:-[^\W\d_]+)?", text)}
    tokens = words(" ".join(texts))
    page_tokens = {u: words(t) for u, t in (pages or {}).items()}
    out = []
    for r in _reading_rows(paths):
        word = QUE_MARK.sub("que", r.get("word") or "")
        if not r.get("found") or not word:
            continue
        # On its own page when the page is known: the word elsewhere in the work proves nothing.
        if not any(reads_as(word, t) for t in page_tokens.get(r.get("unit"), tokens)):
            out.append(f"site {r.get('id')} ({r.get('unit')}): the site reader read {r['word']!r} where the page had "
                       f"{r.get('edition')!r}; the batch has neither that word nor a note naming it. Print it, or "
                       "correct a printer's error with a note saying the print reads it")
            continue
        # At its own spot (Hurtado p3-022: ſecũda and ſecunda, both on p. 35, each put on
        # the other's line). A note on the page naming the reading answers it.
        dip = (diplomatic or {}).get(r.get("unit"))
        hit = dip and r.get("printed_line") and _site_position(r["printed_line"], r["word"], dip)
        # The reader's line and the site's own words fall on one spot; otherwise the reader
        # read a look-alike line, and its word settles nothing (Hurtado p3-021, p. 35).
        site = dip and hit and r.get("context") and _site_position(
            r["context"].replace("[…]", f" {r.get('edition') or ''} "), r.get("edition") or "", dip)
        if site and abs(site[0] - hit[0]) > 1:
            out.append(f"site {r.get('id')} ({r.get('unit')}): the reader's line {r['printed_line']!r} is another "
                       "place on the page than the site: it read a look-alike line. Resend it with its page: "
                       f"python3 -m exscriptor.gemini_sites ... --wide {r.get('id')}")
            continue
        at = hit and hit[1]
        if at and at != _plain(r["word"]) and _plain(r["word"]) not in _plain(
                " ".join(re.findall(r"\^\[[^\]]*\]", (pages or {}).get(r.get("unit"), "")))):
            out.append(f"site {r.get('id')} ({r.get('unit')}): the site reader read {r['word']!r} in the line "
                       f"{r['printed_line']!r}; the diplomatic page has {at!r} there. The word is printed elsewhere "
                       "on the page: put it on the reader's line, or name it in a note")
    return out


def unread_sites(run_files, ledger_rows: list[dict]) -> list[str]:
    """Every site sent to the reader has a reading. A site whose reading was not found, or
    whose row was deleted, was settled on nothing (Hurtado p3-019: three verdicts on no
    reading). Re-run gemini_sites, which resends it; or take the unsettled route, an
    escalated ledger row on that page naming the form."""
    escalated = {}
    for r in ledger_rows:
        if r.get("escalate") is True:
            escalated.setdefault(r.get("unit"), []).append(_plain(f"{r.get('quoted', '')} {r.get('proposed', '')}"))
    out = []
    for path in run_files:
        jobs = json.loads((path.parent / "jobs.json").read_text(encoding="utf-8"))
        rows = {r.get("id"): r for r in _reading_rows(path)}
        for job in jobs:
            for sid in job.get("ids", []) if job.get("harvested") else []:
                r = rows.get(sid) or {}
                if r.get("found") and r.get("word"):
                    continue
                form = _plain(r.get("edition") or "")
                if form and any(form in e for e in escalated.get(r.get("unit"), [])):
                    continue
                where = r.get("unit") or "its row deleted"
                out.append(f"site {sid} ({path.parent.parent.name}/{path.parent.name}, {where}): sent to the site "
                           "reader, no reading. "
                           "Re-run gemini_sites (it resends sites without a reading), or take the unsettled route")
    return out


def misreading_waived(form: str, reason: str, readings: dict[str, list[str]]) -> bool:
    """`blind read: <form>` in the reason, and, where the site reader read the site, its
    word is the form: a quoted read the reader never gave holds nothing (Hurtado p3-010:
    'blind read: testimonnio' over Gemini's teſtimomnio, a misprint waived as a word)."""
    words = readings.get(_plain(form))
    return blind_read_is(form, reason) and (not words or any(reads_as(w, form) for w in words))


def gate_long_s(work_dir: Path) -> list[str]:
    """An old print's page keeps its long s (diplomatic contract). A page where ſ is under a
    tenth of the medial s, in a work that has ſ, was not read against the print: its draft's
    normalized s went through (Hurtado 1624 pp. 75-105, pilot 3; Alvarez pp. 24, 57, 60, 61)."""
    try:
        work = json.loads((work_dir / "work.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    pf = work.get("page_files") or {}
    if pf.get("print") != "old":
        return []
    span = work.get("pages") or {}
    first, last = span.get("first", 0), span.get("last", 10 ** 6)
    counts = {}
    for f in sorted((work_dir / (pf.get("dir") or "diplomatic")).glob("pg-*.md")):
        m = re.match(r"pg-(\d+)", f.stem)
        if not m or not first <= int(m.group(1)) <= last:
            continue
        text = re.sub(r"<!--.*?-->", "", f.read_text(encoding="utf-8"), flags=re.S)
        counts[f.stem] = text.count("ſ"), len(MEDIAL_S.findall(text))
    if not any(ls for ls, _ in counts.values()):
        return []  # the print has no long s
    return [f"{page}: {ls} long s against {ms} medial s: the print sets ſ, so this reading was not made "
            "against the scan. Read the page again against its image (the draft's s is not evidence)"
            for page, (ls, ms) in counts.items() if ms >= LONG_S_MIN and ls / (ls + ms) < LONG_S_SHARE]


def contextual_waiver_allowed(gate: str, finding: str) -> bool:
    return not (gate == "long-s" and finding.startswith(("decisions.tsv: wildcard ", "decisions.tsv: scan method ", "old-print long-s screen needs ", "unresolved long-s ")))


def gate_long_s_decisions(work_dir: Path, lex: dict | None) -> list[str]:
    """A contextual f/long-s ambiguity cannot be closed for a whole work."""
    from exscriptor.expand import long_s_report, read_decisions
    try:
        work = json.loads((work_dir / "work.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if (work.get("page_files") or {}).get("print") != "old":
        return []
    if lex is None:
        return ["old-print long-s screen needs --lexicon with the work excluded"]
    out = []
    decisions = read_decisions(work_dir / "decisions.tsv")
    pf = work.get("page_files") or {}
    span = work.get("pages") or {}
    pages = []
    for page in sorted((work_dir / (pf.get("dir") or "diplomatic")).glob("pg-*.md")):
        m = re.match(r"pg-(\d+)", page.stem)
        if m and span.get("first", 0) <= int(m.group(1)) <= span.get("last", 10 ** 6):
            pages.append(page)
    for word, count, alternate, _, kind in long_s_report(
            [p.read_text(encoding="utf-8") for p in pages], lex, [p.stem for p in pages], decisions):
        out.append(f"unresolved long-s {word!r}: {count} occurrence(s), possible {alternate!r} ({kind}); "
                   "inspect each occurrence on the scan and record page-specific decisions")
    for row in decisions:
        token = row.token.lower().replace("ſ", "s")
        if len(token) < 2:
            continue
        broad = row.page == "*"
        if not broad and row.occurrence == "*" and re.fullmatch(r"pg-\d+", row.page):
            page = work_dir / ((work.get("page_files") or {}).get("dir") or "diplomatic") / (row.page + ".md")
            if page.exists():
                text = re.sub(r"<!--.*?-->", "", page.read_text(encoding="utf-8"), flags=re.S)
                broad = len(re.findall(r"(?<!\w)" + re.escape(row.token) + r"(?!\w)", text)) > 1
        for i, char in enumerate(token):
            alt = token[:i] + "s" + token[i + 1:]
            if char == "f" and lex.get(alt, 0):
                if broad:
                    out.append(f"decisions.tsv: wildcard {row.token!r} suppresses context-sensitive "
                               f"{token!r}/{alt!r} readings across multiple occurrences; review them "
                               "and record decisions by page and occurrence with scan evidence")
                elif row.method != "scan":
                    out.append(f"decisions.tsv: scan method required for {row.page} {row.token!r} "
                               f"occurrence {row.occurrence}: {token!r}/{alt!r} requires scan evidence")
                break
    return out


def gate_long_s_witness(work_dir: Path, lex: dict | None) -> list[str]:
    """Find unknown diplomatic f-words contradicted by a same-page OCR long-s witness.

    OCR is only a witness: each flagged occurrence needs a scan decision. Exact
    per-page matching avoids treating an unrelated page's word as evidence.
    """
    try:
        work = json.loads((work_dir / "work.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    pf, wit = work.get("page_files") or {}, work.get("witness")
    if pf.get("print") != "old" or not wit:
        return []
    if lex is None:
        return ["long-s witness screen needs --lexicon for this old-print work"]
    data = json.loads((work_dir / wit["path"]).read_text(encoding="utf-8"))
    span = work.get("pages") or {}
    out = []
    for page in sorted((work_dir / (pf.get("dir") or "diplomatic")).glob("pg-*.md")):
        m = re.match(r"pg-(\d+)", page.stem)
        if not m or not span.get("first", 0) <= int(m.group(1)) <= span.get("last", 10 ** 6):
            continue
        n = int(m.group(1))
        witness = data.get(wit.get("key", "pg-{page03}.jpg").format(page=n, page03=f"{n:03d}"), "")
        if not isinstance(witness, str):
            continue
        raw = page.read_text(encoding="utf-8")
        text = re.sub(r"<!--.*?-->", "", raw, flags=re.S).lower()
        words = set(re.findall(r"[^\W\d_]+", witness.lower(), re.UNICODE))
        for word in sorted(set(re.findall(r"[^\W\d_]+", text, re.UNICODE))):
            if len(word) < 5 or "f" not in word or lex.get(word.replace("ſ", "s"), 0):
                continue
            for i, char in enumerate(word):
                alternate = word[:i] + "ſ" + word[i + 1:]
                if char == "f" and alternate in words:
                    sha = hashlib.sha256(raw.encode("utf-8")).hexdigest()
                    out.append(f"{page.stem} sha256={sha}: unknown {word!r} conflicts with the "
                               f"same-page OCR reading {alternate!r}; inspect every occurrence on the "
                               "scan and correct the diplomatic page, or waive with scan evidence")
    return out


OMISSION_RUN = 8


def gate_omission(work_dir: Path, lex: set[str] | None = None) -> list[str]:
    """A page that lost a run of words its OCR witness has. A reader can stop at the foot of the
    first column or skip at a heading (lector ft5 on Hurtado p. 75; the lector-4b card: "it can stop
    at the foot of the first column"), and a corrector who reads its draft against the scan can miss
    it. Runs only where work.json declares ``witness`` ({"path", "key": "pg-{page03}.jpg"}); an old
    print folds the OCR's long s, read as f (Soto 1550)."""
    from exscriptor.omission import _fold, omission_runs
    try:
        work = json.loads((work_dir / "work.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    wit = work.get("witness")
    if not wit:
        return []
    pf = work.get("page_files") or {}
    old = pf.get("print") == "old"
    data = json.loads((work_dir / wit["path"]).read_text(encoding="utf-8"))
    known = {_fold(w, old) for w in lex} if lex else None
    span = work.get("pages") or {}
    first, last = span.get("first", 0), span.get("last", 10 ** 6)
    out = []
    for f in sorted((work_dir / (pf.get("dir") or "diplomatic")).glob("pg-*.md")):
        m = re.match(r"pg-(\d+)", f.stem)
        if not m or not first <= int(m.group(1)) <= last:
            continue
        n = int(m.group(1))
        text = data.get(wit.get("key", "pg-{page03}.jpg").format(page=n, page03=f"{n:03d}"))
        if not text:
            continue
        _, _, runs = omission_runs(f.read_text(encoding="utf-8"), text, min_run=OMISSION_RUN, lexicon=known,
                                   drop_words=set(wit.get("drop_words", ())), old_print=old)
        out += [f"{f.stem}: {len(r)} consecutive words of the OCR witness are not on the page "
                f"({' '.join(r[:10])} …): a skipped passage. Read that place again against the scan and "
                "restore it; if the witness is wrong there (a duplicated line, noise), waive it with what the scan shows"
                for r in runs]
    return out


START_WORDS, START_MIN, START_GAP = 30, 45, 15


def gate_facsimile_start(manifest, ocr: dict[str, str] | None, language: str = "la") -> list[str]:
    """Each section's first filed leaf holds its opening: title and first words.

    The offset audit cannot see a section filed one leaf early or late: every
    offset is then consistent with the wrong leaf. The opening, read against
    the leaf's own OCR, can. A leaf scores the share of the opening's long
    words found, near-spelled, in one stretch of it; an unrelated leaf of the
    same work scores 10-40. Flagged: under ``START_MIN``, or the next leaf
    better by ``START_GAP``. ``ocr`` is ``{filename: text}``, or per column
    (``<leaf>-c1``, ``-c2``…, joined in order); None with facsimile rows
    present is a finding. A flag is settled on the image: a fix, or a waiver
    saying what the leaf shows. The probe is the ``language`` text (the
    print's), never a translation."""
    from exscriptor.shared import IMAGE_EXT, _distance, norm
    rows = [r for w in manifest.get("works") or [] for r in w.get("facsimile") or []]
    if not rows:
        return []
    if ocr is None:
        return ["facsimile rows but no leaf OCR to check section starts against "
                "(<work>/tmp/facsimile-ocr.json, or --leaf-ocr)"]
    cols: dict[str, list] = defaultdict(list)
    for k, v in ocr.items():
        m = re.match(r"(.*?)(?:-c(\d+))?$", IMAGE_EXT.sub("", k))
        cols[m.group(1)].append((int(m.group(2) or 0), v))
    leaves = {k: [t for _, v in sorted(cs) for t in map(norm, v.split()) if t] for k, cs in cols.items()}
    texts = {k: langs.get(language) or next(iter(langs.values()), "") for k, langs in sections_by_key(manifest).items()}
    titles = {}
    for sec in _sections(manifest):
        for k in (sec.get("section_key"), sec.get("slug")):
            if k and isinstance(sec.get("title"), str):
                titles[k] = sec["title"]

    def near(a: str, b: str) -> bool:
        return a == b or (abs(len(a) - len(b)) <= 1 and a[0] == b[0]
                          and _distance(a, b) <= (1 if len(a) < 9 else 2))

    def score(probe: list[str], leaf: str | None) -> float:
        words = leaves.get(IMAGE_EXT.sub("", leaf or ""), [])
        hits = [[i for i, w in enumerate(words) if near(p, w)] for p in probe]
        span, best = len(probe) * 3, 0
        for s in sorted({i for h in hits for i in h}):
            best = max(best, sum(any(s <= i < s + span for i in h) for h in hits))
        return 100.0 * best / max(len(probe), 1)

    by: dict[str, list] = defaultdict(list)
    for r in rows:
        by[r.get("section_path")].append(r)
    out = []
    for path, rs in by.items():
        key = str(path).split("/")[-1]
        content = texts.get(key)
        if not content:
            continue  # a section whose text is not in this batch
        rs.sort(key=lambda r: r.get("sequence") or 0)
        lines = [titles.get(key, "")] + [ln for ln in strip_notes(content).splitlines() if not ln.startswith("#")]
        probe = [w for w in (norm(x) for ln in lines for x in ln.split()) if len(w) >= 5][:START_WORDS]
        first = rs[0]["filename"]
        nxt = next((r["filename"] for r in rs[1:] if r["filename"] != first), None)
        s0, s1 = score(probe, first), score(probe, nxt)
        if s0 < START_MIN or s1 > s0 + START_GAP:
            better = f", {nxt} {s1:.0f}" if nxt else ""
            out.append(f"{path}: opening not found on its first leaf {first} ({s0:.0f}{better})")
    return out


def _titles(node):
    if isinstance(node, dict):
        for k, v in node.items():
            if k in ("title", "title_translations") and isinstance(v, str):
                yield v
            elif k != "texts":
                yield from _titles(v)
    elif isinstance(node, list):
        for v in node:
            yield from _titles(v)


def gate_ledger(manifest, paths: list[Path], pages: dict[str, str] | None = None) -> list[str]:
    """Every ledger decision visible in the batch. A ``page_metadata`` row (a
    page comment: joins-next, catchword, running head) is proven in ``pages``,
    the work's page files: a manifest carries no page comments."""
    rows = [r for p in paths if p.exists() for r in ledger.load(p)]
    if not rows:
        return []
    out = ledger.validate(rows)
    sections = sections_by_key(manifest)
    layers: dict[str, dict[str, str]] = defaultdict(dict)
    for key, langs in sections.items():
        for lang, content in langs.items():
            layers[f"manifest@{lang}"][key] = content
    works = {w.get("slug") for w in manifest.get("works", []) if isinstance(w, dict)} \
        if isinstance(manifest, dict) else set()
    # A row may name its section by the live slug (« quaestio-12-articulus-3 »)
    # rather than the manifest key (« q12-a3 »): resolve it within its work.
    slugs = section_slugs(manifest)
    rows = [dict(r, unit=slugs.get((r.get("work"), r["unit"]), slugs.get((None, r["unit"]), r["unit"])))
            for r in rows]
    in_scope = [r for r in rows if (not r.get("work") or r["work"] in works) and
                (r["verdict"] == "open" or any(ledger.unit_matches(r["unit"], k) for k in sections))]
    meta = [r for r in in_scope if r.get("proof_target") == "page_metadata"]
    out += ledger.check([r for r in in_scope if r not in meta], dict(layers))
    out += ledger.check(meta, {"pages": pages or {}})
    # Page-unit rows (pg-097) are out of the section scope above but are still this batch's.
    mine = [r for r in rows if not r.get("work") or r["work"] in works]
    out += escalations_without_note(mine, pages or {}, layers)
    return [p for p in out if "unit not found" not in p]


def escalations_without_note(rows, pages: dict[str, str], layers) -> list[str]:
    """An unsettled reading (escalate=true) stands in the text with an editor's note saying
    what the print has (AGENTS.md); without it the best guess reads as the print
    (Hurtado p3-012: consisti made consistit, silently)."""
    out = []
    for r in rows:
        final = r.get("final")
        if not r.get("escalate") or r.get("verdict") == "open" or not final:
            continue
        texts = [t for name, t in pages.items() if ledger.unit_matches(r["unit"], Path(name).stem)]
        texts += [t for layer in layers.values() for k, t in layer.items() if ledger.unit_matches(r["unit"], k)]
        hits = [t[i:i + len(final) + 300] for t in texts for i in [t.find(final)] if i >= 0]
        if hits and not any(re.search(r"\^\[Editor['’]s note", h) for h in hits):
            out.append(f"{r.get('id')}: escalated reading {final!r} has no editor's note saying what the "
                       "print has: add ^[Editor's note: the print reads ...; read ...] at the site")
    return out


def read_avoid(path: Path) -> list[tuple[str, str]]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#"):
            phrase, _, reason = line.partition("\t")
            out.append((phrase.strip(), reason.strip()))
    return out


PRINT_READS = re.compile(r"Editor['’]s note:\s*the print reads\s+([^;\]]+?)\s*;", re.I)
NOTE_READS = re.compile(r"the print reads\s+([^;\]]+?)\s*;\s*read\s+([^.\]]+)", re.I)


def gate_print_reads(manifest) -> list[str]:
    """A translation's note on what the print reads quotes the Latin's own note: a copy
    left stale names a reading the print never had (Hurtado p3-014: the English said
    'testimonnio' after the Latin note was corrected to teſtimomnio)."""
    latin = {m for _, t in manifest_units(manifest, "la") for m in PRINT_READS.findall(t)}
    out = []
    for lang in {l for _, langs in sections_by_key(manifest).items() for l in langs} - {"la"}:
        for label, t in manifest_units(manifest, lang):
            out += [f"{label}: its note says the print reads {m!r}, which no Latin note says: copy the Latin note's reading"
                    for m in PRINT_READS.findall(t) if m not in latin]
    # A note whose reading is the print's form says nothing (Hurtado p3-021: 'the print
    # reads ſecunda; read ſecunda' covered a site the reader never found).
    for lang in {l for _, langs in sections_by_key(manifest).items() for l in langs}:
        for label, t in manifest_units(manifest, lang):
            out += [f"{label}: its note says the print reads {a!r} and to read {b!r}, the same word: a note "
                    "says what the print has where the text differs from it, or there is no note"
                    for a, b in NOTE_READS.findall(t) if _plain(a) == _plain(b)]
    return out


def gate_translation_avoid(manifest, avoid: list[tuple[str, str]]) -> list[str]:
    """Banned renderings (a calibration's calques) in any translation block.

    A translator's brief that bans « no inconvenience » for *nullum
    inconveniens* is prose a reviser can skip; this list is checked."""
    out = []
    for sec in _sections(manifest):
        for t in sec.get("texts") or []:
            if t.get("role") != "translation":
                continue
            for i, block in enumerate(t["content"].split("\n\n")):
                low = block.lower()
                for phrase, reason in avoid:
                    if phrase.lower() in low:
                        out.append(f"{sec.get('section_key')} {t['language']} block {i}: « {phrase} » ({reason})")
    return out


def gate_revision(manifest_path: Path, raw: bytes, work_dir: Path) -> list[str]:
    """A staged manifest is never revised in place: its batch slug is spent (HTTP 409, Hurtado
    p3-023). The revision is <stem>-v2.json, which build_manifest gives its own slug."""
    staged = work_dir / "staged.jsonl"
    rows = [json.loads(l) for l in staged.read_text(encoding="utf-8").splitlines() if l.strip()] if staged.is_file() else []
    sha = hashlib.sha256(raw).hexdigest()
    return [f"{manifest_path.name} was staged as batch {r.get('batch_id')} and has changed since: build the "
            f"revision as manifests/{re.sub(r'-v[0-9]+$', '', manifest_path.stem)}-v<n+1>.json (its own batch "
            "slug), then preflight it and pass --supersedes-batch-id"
            for r in rows if r.get("manifest") == manifest_path.name and r.get("sha256") != sha]


def _leaf_ocr(path: Path) -> dict[str, str] | None:
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return {k: v if isinstance(v, str) else "\n".join(l[0] for l in v) for k, v in data.items()}


def run(manifest_path: Path, *, work_dir: Path, alignment_report=None,
        sources: list[Path] = (), ledgers: list[Path] = (), lexicon_path: Path | None = None,
        source_flow: list[Path] = (), source_language: str = "la",
        companions: list[Path] = (), leaf_ocr: Path | None = None) -> dict:
    raw = manifest_path.read_bytes()
    manifest = json.loads(raw.decode("utf-8"))
    others = [json.loads(Path(p).read_text(encoding="utf-8")) for p in companions]
    allow_path = work_dir / "orthography-allow.txt"
    allow = read_allow_file(allow_path) if allow_path.exists() else set()
    src_docs = [json.loads(Path(p).read_text(encoding="utf-8")) for p in sources]
    if not alignment_report:
        adir = work_dir / "alignment"
        alignment_report = [adir / f"{manifest_path.stem}.json",
                            *sorted(adir.glob(f"{manifest_path.stem}.*.json"))]
    ledgers = list(ledgers) or [work_dir / "ledger.jsonl"]
    map_path = house.find_map(work_dir)
    spelling = house.read_map(map_path) if map_path else None
    why = lexicon_path and lexicon.contamination(lexicon_path, work_dir)
    misreadings, lex = [], None
    oov_info = {"refused": why} if why else {}
    if lexicon_path and not why:
        lex = lexicon.load(lexicon_path)
        texts = [t for label, t in manifest_units(manifest, "la") if label.startswith("text:")]
        found = lexicon.oov(texts, lex)
        oov_info = {"forms": len(found), "tokens": sum(found.values()), "top": found.most_common(40)}
        misreadings = [f"{w}: once in the batch, one letter from {near!r} ({lex[near]} in the corpus): a likely "
                       "misreading. Have a blind reader (the line crop only, no form named) read it: fix the page, or "
                       "correct a printer's error with an editor's note, or waive a genuine form with "
                       "'blind read: <its reading>' in the reason"
                       for w, near in lexicon.near_misses(found, lex)]
    findings = {
        "residue": gate_residue(manifest),
        "metadata": gate_metadata(manifest),
        "orthography": gate_orthography(manifest, allow),
        "spelling": gate_spelling(manifest, spelling, allow) if map_path else [
            f"no {house.MAP_NAME} above {work_dir}: every Latin edition takes the corpus spelling map, "
            "and expand found none either. Install it at the repository or job root, re-run `expand run`, rebuild"],
        "quotes": gate_quotes(manifest),
        "seams": gate_seams(manifest),
        "parity": gate_parity(manifest, src_docs),
        "alignment": gate_alignment(manifest, alignment_report, src_docs, source_language),
        "duplicates": gate_duplicates(manifest),
        "source-order": gate_source_order(
            with_companions(manifest, others), read_source_flow(list(source_flow) or
                                       [p for p in [work_dir / "source-flow"] if p.is_dir()]),
            source_language),
        "title-page": gate_title_page(manifest),
        "guillemets": gate_guillemets(manifest),
        "structure": gate_structure(manifest),
        "revision": gate_revision(manifest_path, raw, work_dir),
        "long-s": gate_long_s(work_dir) + gate_long_s_decisions(work_dir, lex),
        "long-s-witness": gate_long_s_witness(work_dir, lex),
        "omission": gate_omission(work_dir, lex),
        "misreadings": misreadings + unreconciled_sites(
            site_reading_files(work_dir), [t for label, t in manifest_units(manifest, "la") if label.startswith("text:")],
            site_pages(work_dir), {p.stem: p.read_text(encoding="utf-8") for p in (work_dir / "diplomatic").glob("*.md")}
        ) + unread_sites(
            site_reading_files(work_dir), [r for p in ledgers if Path(p).exists() for r in ledger.load(Path(p))]),
        "facsimile": gate_facsimile(manifest, blank_leaves(work_dir)),
        "facsimile-offsets": facsimile.gate(manifest, work_dir, source_language),
        "facsimile-start": gate_facsimile_start(manifest, _leaf_ocr(leaf_ocr or work_dir / "tmp" / "facsimile-ocr.json"),
                                                source_language),
        "print-reads": gate_print_reads(manifest),
        "translation-avoid": gate_translation_avoid(manifest, read_avoid(work_dir / "translation-avoid.tsv")),
        "ledger": gate_ledger(manifest, ledgers, ledger.read_layer(str(work_dir / "diplomatic" / "*.md"))),
    }
    readings = site_readings(site_reading_files(work_dir))
    waivers_path = work_dir / "preflight-waivers.json"
    waivers = json.loads(waivers_path.read_text(encoding="utf-8")) if waivers_path.exists() else []
    gates = {}
    for gate, items in findings.items():
        waived = []
        open_items = []
        for item in items:
            w = next((w for w in waivers if w.get("gate") == gate and w.get("finding") == item
                      and str(w.get("reason") or "").strip()
                      and contextual_waiver_allowed(gate, item)
                      and (gate != "misreadings" or misreading_waived(item.split(":")[0], w["reason"], readings))), None)
            (waived.append({"finding": item, "reason": w["reason"]}) if w else open_items.append(item))
        gates[gate] = {"passed": not open_items, "findings": open_items, "waived": waived}
        if gate == "misreadings":
            refused = {f.split(":")[0]: readings[_plain(f.split(":")[0])] for f in open_items
                       if readings.get(_plain(f.split(":")[0]))}
            if refused:
                gates[gate]["site_reader_read"] = refused
    info = {"spelling-map": {"path": str(map_path), "sha": house.map_hash(map_path)} if map_path
            else {"path": None}}
    if oov_info:
        info["oov"] = oov_info
    return {
        "manifest": manifest_path.name,
        "sha256": hashlib.sha256(raw).hexdigest(),
        **({"companions": {Path(p).name: hashlib.sha256(Path(p).read_bytes()).hexdigest()
                           for p in companions}} if companions else {}),
        "passed": all(g["passed"] for g in gates.values()),
        "created": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "gates": gates,
        "info": info,
    }


def report_path(manifest_path: Path) -> Path:
    return manifest_path.with_name(f"{manifest_path.stem}.preflight.json")


def verify(manifest_path: Path) -> str | None:
    """None if a passing report matches the manifest bytes, else the reason."""
    rp = report_path(manifest_path)
    if not rp.exists():
        return f"no preflight report ({rp.name}); run: python3 -m exscriptor.preflight {manifest_path}"
    rep = json.loads(rp.read_text(encoding="utf-8"))
    if rep.get("sha256") != hashlib.sha256(manifest_path.read_bytes()).hexdigest():
        return "the manifest changed after preflight; run preflight again"
    if not rep.get("passed"):
        failed = [g for g, v in rep.get("gates", {}).items() if not v.get("passed")]
        return f"preflight failed: {', '.join(failed)}"
    return None


def default_work_dir(manifest_path: Path) -> Path:
    p = manifest_path.resolve().parent
    while p.name in ("manifests", "superseded") or p.parent.name == "manifests":
        p = p.parent
    return p


def main(
    manifest: Annotated[Path, typer.Argument(help="The manifest that will be submitted")],
    work_dir: Annotated[Path | None, typer.Option(help="Work dir (default: the manifests dir's parent)")] = None,
    alignment_report: Annotated[list[Path], typer.Option("--alignment", help="Alignment report JSON, one per target language (repeatable)")] = None,
    source: Annotated[list[Path], typer.Option(help="Live snapshot with the source text (translate-only)")] = None,
    ledger_path: Annotated[list[Path], typer.Option("--ledger", help="Ledger JSONL (repeatable)")] = None,
    lexicon_path: Annotated[Path | None, typer.Option("--lexicon", help="Corpus lexicon (OOV info)")] = None,
    source_flow: Annotated[list[Path], typer.Option("--source-flow", help="Supplied source, one paragraph per line (file or dir; default <work>/source-flow/)")] = None,
    source_language: Annotated[str, typer.Option(help="Language of the transcription the source flow checks")] = "la",
    companion: Annotated[list[Path], typer.Option("--with", help="A companion batch staged with this one; source order is checked over both (repeatable)")] = None,
    leaf_ocr: Annotated[Path | None, typer.Option(help="OCR of the facsimile leaves, {filename: text} (default <work>/tmp/facsimile-ocr.json)")] = None,
):
    """Run every pre-staging gate; write the hash-bound report."""
    wd = work_dir or default_work_dir(manifest)
    rep = run(manifest, work_dir=wd, alignment_report=alignment_report, sources=source or [],
              ledgers=ledger_path or [], lexicon_path=lexicon_path,
              source_flow=source_flow or [], source_language=source_language,
              companions=companion or [], leaf_ocr=leaf_ocr)
    out = report_path(manifest)
    out.write_text(json.dumps(rep, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    for gate, g in rep["gates"].items():
        mark = "pass" if g["passed"] else "FAIL"
        extra = f" ({len(g['waived'])} waived)" if g["waived"] else ""
        print(f"  {mark} {gate:12s} {len(g['findings'])} finding(s){extra}")
        for f in g["findings"][:12]:
            print(f"       {f[:150]}")
        for form, words in g.get("site_reader_read", {}).items():
            print(f"       site reader read {form!r} as {', '.join(words)}: fix the page or note a printer's error")
        if len(g["findings"]) > 12:
            print(f"       … {len(g['findings']) - 12} more in {out.name}")
    if "oov" in rep["info"]:
        o = rep["info"]["oov"]
        print(f"  info oov          refused: {o['refused']}" if "refused" in o else
              f"  info oov          {o['forms']} forms / {o['tokens']} tokens unknown to the lexicon")
    print(("PASSED" if rep["passed"] else "FAILED") + f" -> {out}")
    if not rep["passed"]:
        raise typer.Exit(1)


app = typer.Typer(add_completion=False)
app.command()(main)


if __name__ == "__main__":
    app()
