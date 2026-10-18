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
               blocks; and a batch title/summary that hands work to a person.
  metadata     every text has source_key, role, license_code, rights_basis;
               a transcription also has source_locator.
  orthography  the Latin texts and titles carry no print letterforms
               (``orthography_screen``; ``<work>/orthography-allow.txt``).
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
  facsimile    a batch with a facsimile: in reading order its printed page
               numbers (labels ``p. N``) never go back, leave no page out, and
               each section's offsets rise with its pages.
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

from exscriptor import alignment, ledger, lexicon, seams
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
}
HANDOFF = re.compile(r"\b(?:TODO|TBD|needs? (?:Julio|(?:human )?review)|for (?:Julio|the human)|"
                     r"flagged for|left for a later|later pass|fix (?:it )?in the UI|spot-check)\b", re.I)
FOOTNOTE = re.compile(r"\^\[")
LINK = re.compile(r"\[\[")


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
            for label, rx in RESIDUE.items():
                n = len(rx.findall(content))
                if n:
                    m = rx.search(content)
                    out.append(f"{key} [{lang}]: {n} × {label} near {content[max(0, m.start() - 30):m.end() + 30]!r}")
    if isinstance(manifest, dict):
        for field in ("title", "summary"):
            v = manifest.get(field)
            if isinstance(v, str) and HANDOFF.search(v):
                out.append(f"batch {field} hands work to a person: {HANDOFF.search(v).group(0)!r}")
    return out


def gate_metadata(manifest) -> list[str]:
    out = []
    for key, t in text_records(manifest):
        lang = t.get("language")
        missing = [f for f in ("language", "source_key", "role", "license_code", "rights_basis")
                   if not t.get(f)]
        if t.get("role") == "transcription" and not t.get("source_locator"):
            missing.append("source_locator")
        if missing:
            out.append(f"{key} [{lang}]: missing {', '.join(missing)}")
    return out


def gate_orthography(manifest, allow: set[str], language: str = "la") -> list[str]:
    out = []
    for label, text in manifest_units(manifest, language):
        bad = failing(screen_text(text, allow))
        for cat, counter in sorted(bad.items()):
            ex = ", ".join(f"{t}×{n}" for t, n in counter.most_common(5))
            out.append(f"{label}: {cat}: {ex}")
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
                           ("footnotes", lambda c: len(FOOTNOTE.findall(c))),
                           ("links", lambda c: len(LINK.findall(c)))):
        counts = {lang: measure(c) for lang, c in langs.items()}
        if len(set(counts.values())) > 1:
            out.append(f"{label} differ: " + ", ".join(f"{l}={n}" for l, n in sorted(counts.items())))
    return out


def gate_parity(manifest) -> list[str]:
    return [f"{key}: {d}" for key, langs in sections_by_key(manifest).items()
            if len(langs) > 1 for d in parity(langs)]


def gate_alignment(manifest, reports, sources: list[dict]) -> list[str]:
    """One alignment report per translated language (« <stem>.json » or
    « <stem>.<lang>.json »): a batch carrying en and es needs both."""
    # Only a TRANSLATION is aligned to a source; an original text in another
    # language (a modern introduction) has nothing to pair with.
    # A reconcile's corrected translation has role « correction »: a language
    # is a target when it carries translations and is not a source language.
    records = [t for _, t in text_records(manifest) if t.get("language")]
    originals = {t["language"] for t in records if t.get("role") in ("transcription", "source_text")}
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
    under four words (a heading label), or present in the batch as a title, a
    note or inside a block, with or without a leading label and numeral
    (« SECTIO II Utrum … » against the title « Utrum … »)."""
    if not flow:
        return []
    src = [words(line) for line in flow]
    index: dict[tuple[str, ...], list[int]] = defaultdict(list)
    for j, w in enumerate(src):
        index[tuple(w[:SOURCE_KEY_WORDS])].append(j)
    texts = [(k, c) for k, lang, c in ledger.manifest_texts(manifest) if lang == language]
    titles = [str(t) for t in _titles(manifest)]
    whole = " " + " ".join(" ".join(words(x)) for x in titles + [c for _, c in texts]
                           + re.findall(r"\^\[([^\]]*)\]", " ".join(c for _, c in texts))) + " "

    def covered(w: list[str]) -> bool:
        return len(w) < 4 or f" {' '.join(w)} " in whole or f" {' '.join(w[2:])} " in whole

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
                            for k in range(cursor + 1, j) if not covered(src[k])]
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


PAGE_LABEL = re.compile(r"^p\.\s*(\d+)$")


def gate_facsimile(manifest) -> list[str]:
    """Pages in reading order: no step back, no gap, offsets rising per section.

    A page may be listed twice in a row (it ends one section and opens the
    next); a page listed earlier than its predecessor, or a page number
    skipped, is what a facsimile aligned against the wrong text looks like."""
    out = []
    for w in manifest.get("works") or []:
        rows = w.get("facsimile") or []
        order = {}
        for r in rows:
            order.setdefault(r.get("section_path"), len(order))
        rows = sorted(rows, key=lambda r: (order[r.get("section_path")], r.get("sequence") or 0))
        prev = None
        last_offset: dict = {}
        for r in rows:
            where = f"{r.get('section_path')} {r.get('page_label')}"
            off, path = r.get("text_offset"), r.get("section_path")
            if off is not None and last_offset.get(path) is not None and off < last_offset[path]:
                out.append(f"{where}: offset {off} before the previous page's {last_offset[path]}")
            if off is not None:
                last_offset[path] = off
            m = PAGE_LABEL.match(str(r.get("page_label") or "").strip())
            if not m:
                continue
            n = int(m.group(1))
            if prev is not None and n < prev:
                out.append(f"{where}: page {n} after page {prev} in reading order")
            elif prev is not None and n > prev + 1:
                gap = f"{prev + 1}" if n == prev + 2 else f"{prev + 1}-{n - 1}"
                out.append(f"{where}: no row for p. {gap}")
            prev = n if prev is None else max(prev, n)
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


def gate_ledger(manifest, paths: list[Path]) -> list[str]:
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
    out += ledger.check(in_scope, dict(layers))
    return [p for p in out if "unit not found" not in p]


def run(manifest_path: Path, *, work_dir: Path, alignment_report=None,
        sources: list[Path] = (), ledgers: list[Path] = (), lexicon_path: Path | None = None,
        source_flow: list[Path] = (), source_language: str = "la",
        companions: list[Path] = ()) -> dict:
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
    findings = {
        "residue": gate_residue(manifest),
        "metadata": gate_metadata(manifest),
        "orthography": gate_orthography(manifest, allow),
        "seams": gate_seams(manifest),
        "parity": gate_parity(manifest),
        "alignment": gate_alignment(manifest, alignment_report, src_docs),
        "duplicates": gate_duplicates(manifest),
        "source-order": gate_source_order(
            with_companions(manifest, others), read_source_flow(list(source_flow) or
                                       [p for p in [work_dir / "source-flow"] if p.is_dir()]),
            source_language),
        "facsimile": gate_facsimile(manifest),
        "ledger": gate_ledger(manifest, ledgers),
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
    info = {}
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
):
    """Run every pre-staging gate; write the hash-bound report."""
    wd = work_dir or default_work_dir(manifest)
    rep = run(manifest, work_dir=wd, alignment_report=alignment_report, sources=source or [],
              ledgers=ledger_path or [], lexicon_path=lexicon_path,
              source_flow=source_flow or [], source_language=source_language,
              companions=companion or [])
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
