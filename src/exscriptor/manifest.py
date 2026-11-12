"""Build a create / append_sections / attach_facsimile manifest from a work
dir. One builder for every new work, so no work writes its own.

Reads the work-dir contract (see ``exscriptor.status``):

    work.json        "manifest": {"work": {...work fields...}, "authors": [...],
                                  "sources": {"la": {...}, "en": {...}},
                                  "batch_slug": "<prefix>"}
    structure.json   sections: key, type, title, slug, parent, sequence,
                     show_section_label, canonical_locus, commented_locus,
                     printed_start/printed_end, title_translations {lang: title},
                     live_path (an EXISTING section's slug path, for a parent
                     already on the site: append_sections only)
    assembled/<key>.md               the Latin (source language)
    translation-<lang>/<key>.md      each translation

Two works in one batch (a volume printing a text and its commentary): give
``manifest.works`` instead of ``manifest.work``, a list of
``{"id": ..., "work": {...}, "languages": [...]}``, and tag each structure
section with ``"work": <id>``; section keys must be unique across the works
(``thomas-q50a1``, ``caietanus-q50a1``). Sources and authors are shared.

The facsimile: when ``<work>/facsimile-manifest.json`` exists,
a single-work ``create`` batch carries it as the work's ``facsimile``, so the
same approval publishes the scans. It must be aligned to the text of THIS
manifest. Any other batch
leaves it out: a facsimile replaces ALL of a work's scans, and one built before
an append would drop the pages it does not know. An ``append_sections`` batch
carries it only with ``--with-facsimile``, and only when the file covers every
appended section (aligned against the work as it will stand after the append:
live sections plus this batch); otherwise the builder refuses. A live work
can also get its facsimile from ``--mode attach_facsimile``, built against the
live text after the approval; that batch carries the slug and title and
changes nothing else.

A section may carry ``source_locator`` (overrides the printed-page locator
of its source-language text) and ``citation``.

Refuses (exit 1, nothing written) when a selected text-bearing section has no
assembled text, a translation's block count differs from the Latin's, a
translation is missing for a requested language, or a parent cannot be
resolved. The manifest then goes to `exscriptor.alignment` and
`exscriptor.preflight`.

Usage:

    python3 -m exscriptor.manifest <work> --mode create --languages la,en \\
        --out <work>/manifests/<stem>-v1.json [--sections key1,key2]
    python3 -m exscriptor.manifest <work> --mode attach_facsimile \\
        --out <work>/manifests/<slug>-facsimile.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.parse
from pathlib import Path

from exscriptor import https, licence
from exscriptor.credentials import credential

API = "https://api.scholathomistica.com"



def house_titles(work_dir: Path):
    """structure.json keeps the print's titles; a Latin title takes the house
    pass its text took in ``expand`` (the spelling map, stop spacing), with the
    allow-file the edition recorded in edition/EXPAND.json."""
    from exscriptor import house
    from exscriptor.orthography_screen import read_allow_file
    pages = sorted((work_dir / "edition").glob("*.md"))
    # the pair rows take the work's majority, as `expand` took it over these pages
    rows = house.work_rows(house.default_map(), [p.read_text(encoding="utf-8") for p in pages])[0]
    flags = work_dir / "edition" / "EXPAND.json"
    allow_file = json.loads(flags.read_text(encoding="utf-8")).get("allow_file") if flags.exists() else None
    allow = read_allow_file(work_dir / allow_file) if allow_file else set()
    return lambda t: house.fix_spacing(house.apply_spelling(t, rows, allow)[0])[0]

def blocks(text: str) -> list[str]:
    return [b.strip() for b in re.split(r"\n\s*\n+", text.strip()) if b.strip()]


def locator(sec: dict, by_key: dict) -> str | None:
    s, e = sec.get("printed_start"), sec.get("printed_end")
    if s is None or e is None:
        kids = [x for x in by_key.values() if x.get("parent") == sec["key"]]
        spans = [(locator_span(k, by_key)) for k in kids]
        spans = [x for x in spans if x[0] is not None]
        if not spans:
            return None
        s, e = min(x[0] for x in spans), max(x[1] for x in spans)
    return f"p. {s}" if s == e else f"pp. {s}-{e}"


def locator_span(sec: dict, by_key: dict):
    if sec.get("printed_start") is not None:
        return sec["printed_start"], sec.get("printed_end", sec["printed_start"])
    kids = [x for x in by_key.values() if x.get("parent") == sec["key"]]
    spans = [locator_span(k, by_key) for k in kids]
    spans = [x for x in spans if x[0] is not None]
    return (min(x[0] for x in spans), max(x[1] for x in spans)) if spans else (None, None)


# The batch shape of a facsimile page; the older Git manifests also carried
# section_slug / section_id, which the API refuses.
FACSIMILE_KEYS = ("filename", "section_path", "sequence", "page_label", "text_offset")


def facsimile(work_dir: Path) -> list[dict] | None:
    path = work_dir / "facsimile-manifest.json"
    if not path.exists():
        return None
    return [{k: e[k] for k in FACSIMILE_KEYS if k in e}
            for e in json.loads(path.read_text(encoding="utf-8"))]


APPEND_WORK_KEYS = {"slug", "title", "canonical_key", "relations"}
# CorpusCreateWork in the platform's schema (``skills/reference/manifest-schema.json``; sections
# and facsimile are the builder's own). The server refuses any other field; refuse it here first.
CREATE_WORK_KEYS = {"import_mode", "author_key", "author_slug", "title", "original_title",
                    "original_language", "slug", "canonical_key", "relations", "description",
                    "publication_year", "is_complete", "align_parallel_paragraphs"}


def attach_facsimile(work_dir: Path, m: dict, slug: str | None = None,
                     title: str | None = None) -> dict:
    pages = facsimile(work_dir)
    if not pages:
        print(f"REFUSED: no {work_dir / 'facsimile-manifest.json'}")
        sys.exit(1)
    w = m.get("work") or {}
    slug = w.get("slug") or slug
    title = w.get("title") or title or slug
    if not slug:
        print("REFUSED: no work.json manifest work slug; pass --work-slug (legacy work)")
        sys.exit(1)
    images = len({p["filename"] for p in pages})
    sections = len({p["section_path"] for p in pages})
    return {
        "schema_version": 1,
        "batch_slug": f"{slug}-facsimile",
        "title": f"{title}: facsimile",
        "summary": f"attach_facsimile: {images} page images across {sections} sections, "
                   "already in the media store, each placed at its offset in the live text.",
        "sources": [],
        "authors": [],
        "works": [{"import_mode": "attach_facsimile", "slug": slug, "title": title,
                   "facsimile": pages}],
    }


def build(work_dir: Path, mode: str, languages: list[str], keys: list[str] | None,
          with_facsimile: bool = False, work_slug: str | None = None,
          title: str | None = None) -> dict:
    cfg_path = work_dir / "work.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8")) if cfg_path.exists() else {}
    m = cfg.get("manifest") or {}
    if mode == "attach_facsimile":
        return attach_facsimile(work_dir, m, work_slug, title)
    if not isinstance(m.get("sources", {}), dict):
        print('REFUSED: work.json manifest.sources is keyed by language: {"la": {...}, "en": {...}} (--help)')
        sys.exit(1)
    structure = json.loads((work_dir / "structure.json").read_text(encoding="utf-8"))
    errors: list[str] = []
    specs = m.get("works") or [{"id": None, "work": m.get("work") or {}, "languages": languages}]
    works, used, n_text, words = [], set(), 0, 0
    for spec in specs:
        secs = [s for s in structure["sections"] if spec["id"] is None or s.get("work") == spec["id"]]
        langs = spec.get("languages") or languages
        work, nt, nw = _build_work(work_dir, mode, langs, keys, spec["work"], secs, structure, m, errors)
        works.append(work)
        n_text += nt
        words += nw
        used |= {t["source_key"] for s in work["sections"] for t in s["texts"]}
    for src in (m.get("sources") or {}).values():
        if src.get("source_key") in used:
            errors += licence.problems(src)
    if keys:
        known = {s["key"] for s in structure["sections"]}
        if set(keys) - known:
            errors.append(f"unknown section keys: {sorted(set(keys) - known)}")

    if mode == "create" and m.get("authors"):
        try:
            errors += existing_authors(m["authors"])
        except OSError as e:
            print(f"warning: could not check the authors against the library ({e}); exscriptor.submit checks again")
    if errors:
        print(f"REFUSED: {len(errors)} problem(s)")
        for e in errors:
            print("  ", e)
        sys.exit(1)

    pages = facsimile(work_dir)
    if pages and mode == "create" and len(works) == 1:  # ponytail: one facsimile file per work dir; split it per work when a two-work dir needs scans
        works[0]["facsimile"] = pages
    if with_facsimile:
        # a facsimile replaces ALL the work's scans: it must already know the appended text
        filed = {e["section_path"].split("/")[-1] for e in pages or []}
        missing = [s["slug"] for s in works[0]["sections"] if s["texts"] and s["slug"] not in filed]
        if mode != "append_sections" or len(works) != 1 or not pages or missing:
            print(f"REFUSED: --with-facsimile needs a single-work append_sections batch and a "
                  f"facsimile-manifest.json filing every appended section; missing {missing[:5]}")
            sys.exit(1)
        works[0]["facsimile"] = pages

    sources = m.get("sources") or {}
    all_langs = sorted({l for spec in specs for l in (spec.get("languages") or languages)})
    title = m.get("title") or " + ".join(w.get("title", cfg.get("slug", work_dir.name)) for w in works)
    return {
        "schema_version": 1,
        "batch_slug": m.get("batch_slug", work_dir.name),
        "title": f"{title} ({', '.join(all_langs)})",
        "summary": m.get("summary") or (
            f"{mode}: {n_text} sections, {words} words of source text"
            + (f" with paragraph-aligned {', '.join(l for l in all_langs if l != 'la')}"
               if len(all_langs) > 1 else "")
            + ". Adjudicated against the page images; preflight passed."),
        "sources": [s for s in sources.values() if s["source_key"] in used],
        "authors": m.get("authors", []) if mode == "create" else [],
        "works": works,
    }


def fetch_json(url: str):
    """Raises OSError when the library cannot be read, including a reply that is not JSON."""
    with https.urlopen(url, timeout=20) as r:
        try:
            return json.loads(r.read().decode("utf-8"))
        except ValueError as e:
            raise OSError(f"{url} did not answer JSON (is SCHOLA_API_URL the API's address?)") from e


def existing_authors(authors: list[dict], api: str | None = None) -> list[str]:
    """A declared author the library already holds, by name or alias, goes in as the work's
    author_slug, not as a new record (the server once merged one by name, with a
    warning nobody read). Raises OSError when the library cannot be reached."""
    api = (api or credential("SCHOLA_API_URL", required=False) or API).rstrip("/")
    out, slugs = [], None
    for a in authors:
        name = a.get("name", "").strip()
        hits = fetch_json(f"{api}/api/authors?q={urllib.parse.quote(name)}").get("items", []) if len(name) > 1 else []
        for h in hits:
            if name.casefold() in {n.casefold() for n in [h["name"], *h.get("aliases", [])]}:
                if slugs is None:
                    slugs = {p["id"]: p["slug"] for p in fetch_json(f"{api}/api/authors/profiles")}
                held = slugs.get(h["id"], f"id {h['id']}")
                out.append(f"author {a.get('author_key')!r} ({name}) is in the library as {held} ({h['name']}): "
                           f"drop it from manifest.authors and set work.author_slug to {held}, without author_key")
    return out


def _build_work(work_dir, mode, languages, keys, work_meta, sections, structure, m, errors):
    by_key = {s["key"]: s for s in sections}
    source_lang = work_meta.get("original_language", "la")

    wanted = (set(keys) & set(by_key)) if keys else set(by_key)
    # ancestors of every wanted section travel with it (texts: []), unless
    # they are already live (append_sections with live_path)
    include = set()
    for k in wanted:
        include.add(k)
        p = by_key[k].get("parent")
        while p and p in by_key and not (mode == "append_sections" and by_key[p].get("live_path")):
            include.add(p)
            p = by_key[p].get("parent")

    sources = m.get("sources") or {}
    edition_title = house_titles(work_dir) if source_lang == "la" else (lambda t: t)
    out_sections = []
    for sec in sections:  # document order
        if sec["key"] not in include:
            continue
        entry = {
            # `key` names the files (assembled/<key>.md); `section_key` is the
            # key the server persists, when the live work has its own scheme
            # (« q50-a1 ») that a two-work dir cannot use as file names.
            "section_key": sec.get("section_key", sec["key"]),
            "parent_key": None,
            "title": edition_title(sec["title"]),
            "slug": sec.get("slug", sec["key"]),
            "section_type": sec["type"],
            "show_section_label": sec.get("show_section_label", True),
            "canonical_locus": sec.get("canonical_locus"),
            "commented_locus": sec.get("commented_locus"),
            "texts": [],
        }
        if "sequence" in sec:  # absent: the server places it in list order
            entry["sequence"] = sec["sequence"]
        if sec.get("citation"):
            entry["citation"] = sec["citation"]
        parent = sec.get("parent")
        if parent:
            if parent in include:
                entry["parent_key"] = by_key[parent].get("section_key", parent)
            elif mode == "append_sections" and by_key[parent].get("live_path"):
                entry["parent_path"] = by_key[parent]["live_path"]
            else:
                errors.append(f"{sec['key']}: parent {parent} is neither in the batch nor live_path")
        titles = {lang: t for lang, t in (sec.get("title_translations") or {}).items() if lang in languages}
        for lang in languages:
            if lang != source_lang and not str(titles.get(lang) or "").strip():
                errors.append(f"{sec['key']}: missing nonblank title_translations[{lang!r}] for staged translation (including parent headings)")
        if titles:
            entry["title_translations"] = titles
        if sec["key"] in wanted:
            la_path = work_dir / "assembled" / f"{sec['key']}.md"
            if la_path.exists():
                la = la_path.read_text(encoding="utf-8").strip()
                la_blocks = len(blocks(la))
                for lang in languages:
                    src = sources.get(lang)
                    if not src:
                        errors.append(f"work.json manifest.sources has no {lang!r} source")
                        continue
                    if lang == source_lang:
                        content = la
                        role = "transcription"
                    else:
                        tpath = work_dir / f"translation-{lang}" / f"{sec['key']}.md"
                        if not tpath.exists():
                            errors.append(f"{sec['key']}: no {tpath.relative_to(work_dir)}")
                            continue
                        content = tpath.read_text(encoding="utf-8").strip()
                        role = "translation"
                        if len(blocks(content)) != la_blocks:
                            errors.append(f"{sec['key']}: {lang} has {len(blocks(content))} blocks, "
                                          f"{source_lang} has {la_blocks}")
                    text = {"language": lang, "content": content, "source_key": src["source_key"],
                            "role": role, "license_code": src["license_code"],
                            "rights_basis": src["rights_basis"]}
                    if src.get("license_url"):
                        text["license_url"] = src["license_url"]
                    if src.get("attribution_text"):
                        text["attribution_text"] = src["attribution_text"]
                    loc = (sec.get("source_locator") or locator(sec, by_key)) if role == "transcription" \
                        else sec.get("slug", sec["key"])
                    if loc:
                        text["source_locator"] = loc
                    entry["texts"].append(text)
            elif (sec["type"] not in (structure.get("node_types") or []) and not sec.get("node")
                  and not any(x.get("parent") == sec["key"] for x in sections)):
                errors.append(f"{sec['key']}: no assembled/{sec['key']}.md")
        out_sections.append(entry)

    work = dict(work_meta)
    if mode == "create":
        work.setdefault("align_parallel_paragraphs", len(languages) > 1)
        if set(work) - CREATE_WORK_KEYS:
            errors.append(f"work.json manifest work fields the platform refuses: "
                          f"{sorted(set(work) - CREATE_WORK_KEYS)} (remove them)")
    else:
        # The server refuses unknown fields: a live work takes only these.
        work = {k: v for k, v in work.items() if k in APPEND_WORK_KEYS}
    work["import_mode"] = mode
    work["sections"] = out_sections
    n_text = sum(1 for s in out_sections if s["texts"])
    words = sum(len(t["content"].split()) for s in out_sections for t in s["texts"] if t["language"] == source_lang)
    return work, n_text, words


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("work_dir", type=Path)
    ap.add_argument("--mode", choices=["create", "append_sections", "attach_facsimile"], required=True)
    ap.add_argument("--languages", default="la")
    ap.add_argument("--sections", help="comma-separated section keys (default: all)")
    ap.add_argument("--batch-slug", help="override work.json manifest.batch_slug")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--with-facsimile", action="store_true",
                    help="append_sections: carry facsimile-manifest.json (the whole work's scans)")
    ap.add_argument("--update-work", type=Path, metavar="JSON",
                    help="append_sections: a guarded {expected, set} on the work's own fields "
                         "(is_complete, description) for the batch that completes it; needs the Custos")
    ap.add_argument("--work-slug", help="attach_facsimile on a legacy work (no work.json): its live slug")
    ap.add_argument("--title", help="attach_facsimile on a legacy work: the live work's title")
    args = ap.parse_args()
    keys = [k.strip() for k in args.sections.split(",")] if args.sections else None
    manifest = build(args.work_dir, args.mode, [l.strip() for l in args.languages.split(",")], keys,
                     with_facsimile=args.with_facsimile, work_slug=args.work_slug, title=args.title)
    version = re.search(r"-v(\d+)$", args.out.stem)
    if args.batch_slug:
        manifest["batch_slug"] = args.batch_slug
    elif version and int(version[1]) > 1:
        # A slug is consumed by its first submission, so a revision (manifest-v2.json) needs its own:
        # the file's version replaces or extends the slug's (a v2 under the old slug was refused with HTTP 409).
        manifest["batch_slug"] = re.sub(r"(-v\d+)?$", version[0], manifest["batch_slug"], count=1)
    if args.update_work:
        if args.mode != "append_sections" or len(manifest["works"]) != 1:
            ap.error("--update-work goes on a single-work append_sections batch")
        manifest["works"][0]["update_work"] = json.loads(args.update_work.read_text(encoding="utf-8"))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    secs = manifest["works"][0].get("sections", [])
    pages = manifest["works"][0].get("facsimile") or []
    print(f"{args.out}: {len(secs)} sections, {sum(len(s['texts']) for s in secs)} texts, "
          f"{len(pages)} facsimile entries")
    print(f"next: python3 -m exscriptor.alignment screen {args.out} ... ; python3 -m exscriptor.preflight {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
