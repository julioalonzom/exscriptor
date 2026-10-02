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
               current text (``alignment check``; default
               ``<work>/alignment/<stem>.json``).
  ledger       ``<work>/ledger.jsonl`` (or ``--ledger``): valid, no open row,
               and every correction present in this manifest's text.
  oov          informational only (``--lexicon``): unknown Latin forms.

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
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

import typer
from typing_extensions import Annotated

from exscriptor import alignment, ledger, lexicon, seams
from exscriptor.orthography_screen import failing, manifest_units, read_allow_file, screen_text

RESIDUE = {
    "sentinel": re.compile(r"[⟦⟪][^⟧⟫]*[⟧⟫]"),
    "html comment": re.compile(r"<!--"),
    "zone marker": re.compile(r"<<<|>>>"),
    "wrapper tag": re.compile(r"</?content>"),
    "soft hyphen": re.compile("­"),
    "uncertainty mark": re.compile(r"\[illegible|\[\?\]|\(\?\)", re.I),
    # XXX is also the numeral 30: « XXX. Ad hoc dicitur », « qu. XXX, art. 3 ».
    # A placeholder XXX stands alone, never after « qu. » or before a stop.
    "todo": re.compile(r"\b(?:TODO|TBD|FIXME)\b|(?<!\. )\bXXX\b(?![.,;:)\]])"),
    "placeholder": re.compile(r"\[(?:Block|Translation|Paragraph) \d+[^\]]*\]"),
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
    return out


def gate_parity(manifest) -> list[str]:
    out = []
    for key, langs in sections_by_key(manifest).items():
        if len(langs) < 2:
            continue
        for label, measure in (("blocks", lambda c: len(alignment.blocks(c))),
                               ("footnotes", lambda c: len(FOOTNOTE.findall(c))),
                               ("links", lambda c: len(LINK.findall(c)))):
            counts = {lang: measure(c) for lang, c in langs.items()}
            if len(set(counts.values())) > 1:
                out.append(f"{key}: {label} differ: " + ", ".join(f"{l}={n}" for l, n in sorted(counts.items())))
    return out


def gate_alignment(manifest, report: Path | None, sources: list[dict]) -> list[str]:
    # Only a TRANSLATION is aligned to a source; an original text in another
    # language (a modern introduction) has nothing to pair with.
    targets = sorted({t.get("language") for _, t in text_records(manifest)
                      if t.get("role") == "translation" and t.get("language")})
    if not targets:
        return []
    if report is None or not report.exists():
        return [f"multi-language batch and no alignment report at {report} "
                f"(python3 -m exscriptor.alignment screen ...)"]
    rep = json.loads(report.read_text(encoding="utf-8"))
    out = []
    for target in targets:
        if rep.get("target") != target:
            out.append(f"alignment report is for {rep.get('target')!r}, batch carries {target!r}")
            continue
        pairs = alignment.pairs_by_section(manifest, rep.get("source_language", "la"), target, sources)
        out += alignment.check(pairs, rep)
    return out


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
    in_scope = [r for r in rows if r["verdict"] == "open" or
                any(r["unit"] == k or r["unit"] in k or k in r["unit"] for k in sections)]
    out += ledger.check(in_scope, dict(layers))
    return [p for p in out if "unit not found" not in p]


def run(manifest_path: Path, *, work_dir: Path, alignment_report: Path | None = None,
        sources: list[Path] = (), ledgers: list[Path] = (), lexicon_path: Path | None = None) -> dict:
    raw = manifest_path.read_bytes()
    manifest = json.loads(raw.decode("utf-8"))
    allow_path = work_dir / "orthography-allow.txt"
    allow = read_allow_file(allow_path) if allow_path.exists() else set()
    src_docs = [json.loads(Path(p).read_text(encoding="utf-8")) for p in sources]
    if alignment_report is None:
        alignment_report = work_dir / "alignment" / f"{manifest_path.stem}.json"
    ledgers = list(ledgers) or [work_dir / "ledger.jsonl"]
    findings = {
        "residue": gate_residue(manifest),
        "metadata": gate_metadata(manifest),
        "orthography": gate_orthography(manifest, allow),
        "seams": gate_seams(manifest),
        "parity": gate_parity(manifest),
        "alignment": gate_alignment(manifest, alignment_report, src_docs),
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
    if lexicon_path:
        lex = lexicon.load(lexicon_path)
        texts = [t for label, t in manifest_units(manifest, "la") if label.startswith("text:")]
        found = lexicon.oov(texts, lex)
        info["oov"] = {"forms": len(found), "tokens": sum(found.values()),
                       "top": found.most_common(40)}
    return {
        "manifest": manifest_path.name,
        "sha256": hashlib.sha256(raw).hexdigest(),
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
    alignment_report: Annotated[Path | None, typer.Option("--alignment", help="Alignment report JSON")] = None,
    source: Annotated[list[Path], typer.Option(help="Live snapshot with the source text (translate-only)")] = None,
    ledger_path: Annotated[list[Path], typer.Option("--ledger", help="Ledger JSONL (repeatable)")] = None,
    lexicon_path: Annotated[Path | None, typer.Option("--lexicon", help="Corpus lexicon (OOV info)")] = None,
):
    """Run every pre-staging gate; write the hash-bound report."""
    wd = work_dir or default_work_dir(manifest)
    rep = run(manifest, work_dir=wd, alignment_report=alignment_report, sources=source or [],
              ledgers=ledger_path or [], lexicon_path=lexicon_path)
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
        print(f"  info oov          {o['forms']} forms / {o['tokens']} tokens unknown to the lexicon")
    print(("PASSED" if rep["passed"] else "FAILED") + f" -> {out}")
    if not rep["passed"]:
        raise typer.Exit(1)


app = typer.Typer(add_completion=False)
app.command()(main)


if __name__ == "__main__":
    app()
