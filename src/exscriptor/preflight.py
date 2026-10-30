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
  translation-avoid  no translation carries a rendering the work's calibration
               banned (``<work>/translation-avoid.tsv``: phrase<TAB>reason, matched
               case-insensitively).
  ledger       ``<work>/ledger.jsonl`` (or ``--ledger``): valid, no open row,
               and every correction present in this manifest's text.
  oov          informational only (``--lexicon``): unknown Latin forms; refused
               when the lexicon was built from this work's own files.

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
    return [p for p in out if "unit not found" not in p]


def read_avoid(path: Path) -> list[tuple[str, str]]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#"):
            phrase, _, reason = line.partition("\t")
            out.append((phrase.strip(), reason.strip()))
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
        "facsimile": gate_facsimile(manifest, blank_leaves(work_dir)),
        "facsimile-offsets": facsimile.gate(manifest, work_dir, source_language),
        "facsimile-start": gate_facsimile_start(manifest, _leaf_ocr(leaf_ocr or work_dir / "tmp" / "facsimile-ocr.json"),
                                                source_language),
        "translation-avoid": gate_translation_avoid(manifest, read_avoid(work_dir / "translation-avoid.tsv")),
        "ledger": gate_ledger(manifest, ledgers, ledger.read_layer(str(work_dir / "diplomatic" / "*.md"))),
    }
    waivers_path = work_dir / "preflight-waivers.json"
    waivers = json.loads(waivers_path.read_text(encoding="utf-8")) if waivers_path.exists() else []
    gates = {}
    for gate, items in findings.items():
        waived = []
        open_items = []
        for item in items:
            w = next((w for w in waivers if w.get("gate") == gate and w.get("finding") == item
                      and str(w.get("reason") or "").strip()), None)
            (waived.append({"finding": item, "reason": w["reason"]}) if w else open_items.append(item))
        gates[gate] = {"passed": not open_items, "findings": open_items, "waived": waived}
    info = {"spelling-map": {"path": str(map_path), "sha": house.map_hash(map_path)} if map_path
            else {"path": None}}
    why = lexicon_path and lexicon.contamination(lexicon_path, work_dir)
    if why:
        info["oov"] = {"refused": why}
    elif lexicon_path:
        lex = lexicon.load(lexicon_path)
        texts = [t for label, t in manifest_units(manifest, "la") if label.startswith("text:")]
        found = lexicon.oov(texts, lex)
        info["oov"] = {"forms": len(found), "tokens": sum(found.values()),
                       "top": found.most_common(40)}
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
