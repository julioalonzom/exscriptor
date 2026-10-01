#!/usr/bin/env python3
"""Paragraph alignment of a source text and its translation, made checkable.

Equal paragraph counts are necessary and prove nothing: an omitted block and
a duplicated one cancel, and a sustained one-block offset keeps every count
equal while every pair after it is wrong. Only reading the pairs settles it.
This module decides WHICH pairs must be read, records that they were, and
refuses a manifest whose text changed after the reading.

``screen`` flags, per section with both languages:

* ``ratio``  -- target/source length outside 0.5-2.0 (omission, merge, split);
* ``final``  -- the last pair of every section (an offset shows at the end);
* ``sample`` -- a seeded random sample of internal pairs (``--rate``, at
  least one per section), so a sustained offset with ordinary ratios is
  still caught;

and writes a report with each section's source and target sha256. A section
whose block counts differ is an error that no disposition can clear.

The reader (agent) gives every flag a disposition in the report:
``{"verdict": "aligned" | "outlier-ok", "note": "<what was compared>"}``.
When a flag shows a real defect, fix the text, re-run ``screen``: the
section's hash changes, its old dispositions are dropped, and it is read
again. ``check`` passes only when every section is present with matching
hashes, counts agree, and every flag has a disposition.

For a translate-only job (the source is live, the manifest carries only the
translation) pass the live snapshot with ``--source``.

Usage:

    python3 -m exscriptor.alignment screen manifest.json --target en --report align.json
    python3 -m exscriptor.alignment show align.json manifest.json      # flagged pairs, to read
    python3 -m exscriptor.alignment check manifest.json --report align.json
"""
from __future__ import annotations

import hashlib
import json
import random
import re
from pathlib import Path

import typer
from typing_extensions import Annotated

from exscriptor.ledger import manifest_texts

LOW, HIGH = 0.5, 2.0
VERDICTS = {"aligned", "outlier-ok"}


def blocks(content: str) -> list[str]:
    return [b.strip() for b in re.split(r"\n\s*\n+", content.strip()) if b.strip()]


def sha(text: str) -> str:
    return hashlib.sha256("\n\n".join(blocks(text)).encode("utf-8")).hexdigest()


def pairs_by_section(manifest: dict, source: str, target: str,
                     sources: list[dict] = ()) -> dict[str, tuple[str, str]]:
    """{section key: (source text, target text)} for sections with a target
    text; the source comes from the manifest, else from the snapshots."""
    src, tgt = {}, {}
    for doc in [manifest, *sources]:
        for key, lang, content in manifest_texts(doc):
            if lang == source and key not in src:
                src[key] = content
    for key, lang, content in manifest_texts(manifest):
        if lang == target:
            tgt[key] = content
    return {k: (src.get(k), v) for k, v in tgt.items()}


def screen(pairs: dict[str, tuple[str | None, str]], *, seed: int = 0, rate: float = 0.05,
           previous: dict | None = None) -> dict:
    previous = previous or {}
    out = {}
    for key in sorted(pairs):
        s, t = pairs[key]
        if s is None:
            out[key] = {"error": "no source text for this section (pass --source)"}
            continue
        sb, tb = blocks(s), blocks(t)
        entry = {"source_sha": sha(s), "target_sha": sha(t), "counts": [len(sb), len(tb)], "flags": []}
        if len(sb) != len(tb):
            entry["error"] = f"block count mismatch: source {len(sb)}, target {len(tb)}"
            out[key] = entry
            continue
        kinds: dict[int, set] = {}
        for i, (a, b) in enumerate(zip(sb, tb), 1):
            r = len(b) / max(len(a), 1)
            if r < LOW or r > HIGH:
                kinds.setdefault(i, set()).add("ratio")
        if sb:
            kinds.setdefault(len(sb), set()).add("final")
            internal = list(range(1, len(sb)))
            rng = random.Random(f"{seed}:{key}")
            for i in rng.sample(internal, min(len(internal), max(1, round(rate * len(sb))))):
                kinds.setdefault(i, set()).add("sample")
        prev = previous.get(key, {})
        same = prev.get("source_sha") == entry["source_sha"] and prev.get("target_sha") == entry["target_sha"]
        old = {f["index"]: f.get("disposition") for f in prev.get("flags", [])} if same else {}
        for i in sorted(kinds):
            a, b = sb[i - 1], tb[i - 1]
            entry["flags"].append({
                "index": i, "kinds": sorted(kinds[i]), "ratio": round(len(b) / max(len(a), 1), 2),
                "source": a[:80], "target": b[:80], "disposition": old.get(i)})
        out[key] = entry
    return out


def check(pairs: dict[str, tuple[str | None, str]], report: dict) -> list[str]:
    problems = []
    sections = report.get("sections", {})
    for key, (s, t) in sorted(pairs.items()):
        entry = sections.get(key)
        if entry is None:
            problems.append(f"{key}: not in the alignment report (run screen)")
            continue
        if entry.get("error"):
            problems.append(f"{key}: {entry['error']}")
            continue
        if s is None:
            problems.append(f"{key}: no source text to check against")
            continue
        if entry["source_sha"] != sha(s) or entry["target_sha"] != sha(t):
            problems.append(f"{key}: text changed since the screen (re-run screen and re-read)")
            continue
        for f in entry["flags"]:
            d = f.get("disposition") or {}
            if d.get("verdict") not in VERDICTS or not str(d.get("note") or "").strip():
                problems.append(f"{key} block {f['index']} ({','.join(f['kinds'])}): no disposition")
    return problems


app = typer.Typer(add_completion=False, help="Paragraph alignment: screen, show, check.")


def _load(manifest: Path, source_files: list[Path] | None):
    return (json.loads(manifest.read_text(encoding="utf-8")),
            [json.loads(p.read_text(encoding="utf-8")) for p in source_files or []])


@app.command("screen")
def screen_cmd(
    manifest: Annotated[Path, typer.Argument()],
    report: Annotated[Path, typer.Option(help="Alignment report JSON (updated in place)")],
    target: Annotated[str, typer.Option(help="Target language")] = "en",
    source_language: Annotated[str, typer.Option("--source-language")] = "la",
    source: Annotated[list[Path], typer.Option(help="Live snapshot(s) holding the source text")] = None,
    seed: Annotated[int, typer.Option()] = 0,
    rate: Annotated[float, typer.Option(help="Share of internal pairs sampled per section")] = 0.05,
):
    """Flag the pairs that must be read; keep dispositions of unchanged sections."""
    m, srcs = _load(manifest, source)
    pairs = pairs_by_section(m, source_language, target, srcs)
    prev = json.loads(report.read_text(encoding="utf-8")) if report.exists() else {}
    seed = prev.get("seed", seed)
    sections = screen(pairs, seed=seed, rate=rate, previous=prev.get("sections"))
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps({"source_language": source_language, "target": target, "seed": seed,
                                  "sections": sections}, ensure_ascii=False, indent=1) + "\n",
                      encoding="utf-8")
    flags = sum(len(e.get("flags", [])) for e in sections.values())
    todo = sum(1 for e in sections.values() for f in e.get("flags", []) if not f.get("disposition"))
    errors = [k for k, e in sections.items() if e.get("error")]
    print(f"{len(sections)} sections, {flags} flagged pairs, {todo} to read, {len(errors)} with errors -> {report}")
    for k in errors:
        print(f"  ERROR {k}: {sections[k]['error']}")


@app.command("show")
def show_cmd(
    report: Annotated[Path, typer.Argument()],
    manifest: Annotated[Path, typer.Argument()],
    source: Annotated[list[Path], typer.Option(help="Live snapshot(s) holding the source text")] = None,
    all_flags: Annotated[bool, typer.Option("--all", help="Include flags already dispositioned")] = False,
):
    """Print each flagged pair in full, with its neighbours' edges."""
    rep = json.loads(report.read_text(encoding="utf-8"))
    m, srcs = _load(manifest, source)
    pairs = pairs_by_section(m, rep.get("source_language", "la"), rep["target"], srcs)
    for key, entry in rep["sections"].items():
        if key not in pairs or entry.get("error") or pairs[key][0] is None:
            continue
        sb, tb = blocks(pairs[key][0]), blocks(pairs[key][1])
        for f in entry["flags"]:
            if f.get("disposition") and not all_flags:
                continue
            i = f["index"]
            print(f"=== {key} block {i}/{len(sb)} {','.join(f['kinds'])} ratio={f['ratio']}")
            if i > 1:
                print(f"  prev SRC …{sb[i - 2][-120:]}\n  prev TGT …{tb[i - 2][-120:]}")
            print(f"  SRC {sb[i - 1]}\n  TGT {tb[i - 1]}")
            if i < len(sb):
                print(f"  next SRC {sb[i][:120]}…\n  next TGT {tb[i][:120]}…")


@app.command("check")
def check_cmd(
    manifest: Annotated[Path, typer.Argument()],
    report: Annotated[Path, typer.Option()],
    source: Annotated[list[Path], typer.Option(help="Live snapshot(s) holding the source text")] = None,
):
    """Pass only if every flagged pair of the CURRENT text has a disposition."""
    rep = json.loads(report.read_text(encoding="utf-8"))
    m, srcs = _load(manifest, source)
    pairs = pairs_by_section(m, rep.get("source_language", "la"), rep["target"], srcs)
    problems = check(pairs, rep)
    print(f"{len(pairs)} sections, {len(problems)} problem(s)")
    for p in problems[:200]:
        print("  ", p)
    if problems:
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
