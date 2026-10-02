#!/usr/bin/env python3
"""Where a work stands, computed from its files -- never written by hand.

A status line in a README is a claim, and claims go stale: a resumed session
trusts "assembled, ready to stage" and stages a range whose pages changed
afterwards. This module derives each stage from the artifacts themselves and
names the next step. It reads the work-dir contract:

    work.json                {"track": "modern"|"old-print", "pages": {"first": N, "last": M},
                              "languages": ["la", "en"], "mode": "create"|"translate-only"}
    diplomatic/pg-NNN.md     old print: the diplomatic reading (source of truth)
    edition/pg-NNN.md        old print: derived by ``expand`` (never edited by hand)
    transcription/pg-NNN.md  modern print: the reading (source of truth)
    pending.tsv              ``expand`` tokens awaiting the editor
    assembled/ASSEMBLY.json  ``assemble`` record (page hashes)
    ledger.jsonl             defects ledger
    translation-<lang>/<section>.md
    manifests/<stem>.json + <stem>.preflight.json
    staged.jsonl             one line per submitted batch (the submit wrapper writes it)

Page files are named ``pg-NNN.md`` unless work.json sets
``"page_pattern": "p{n:03d}.md"``.

A work that predates the contract may declare in work.json where a step
lives instead: ``"scouted_in": "README.md (Source, page map)"`` and
``"assembler": "assemble.py + export_contract.py"`` (then ``assembled/`` is
stale when a reading page is newer than every assembled file). Every
manifest in ``manifests/`` is checked, not only the newest.

Usage:

    python3 -m exscriptor.status works/<work>
    python3 -m exscriptor.status works/*            # one line per work
    python3 -m exscriptor.status works/<work> --json
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import typer
from typing_extensions import Annotated

from exscriptor import ledger as lg
from exscriptor import preflight


def _pages(d: Path, pattern: str, first: int, last: int) -> tuple[int, list[int]]:
    have, missing = 0, []
    for n in range(first, last + 1):
        if (d / pattern.format(n=n)).exists():
            have += 1
        else:
            missing.append(n)
    return have, missing


def _ranges(nums: list[int]) -> str:
    out, start = [], None
    for i, n in enumerate(nums):
        if start is None:
            start = n
        if i + 1 == len(nums) or nums[i + 1] != n + 1:
            out.append(f"{start}" if start == n else f"{start}-{n}")
            start = None
    return ",".join(out[:8]) + ("…" if len(out) > 8 else "")


def compute(work: Path) -> dict:
    cfg_path = work / "work.json"
    if not cfg_path.exists():
        return {"work": work.name, "legacy": True, "next": "legacy work (no work.json): read its README"}
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    st: dict = {"work": work.name, "track": cfg.get("track", "modern"), "mode": cfg.get("mode", "create")}
    langs = cfg.get("languages", ["la"])
    pattern = cfg.get("page_pattern", "pg-{n:03d}.md")
    steps: list[tuple[bool, str]] = []

    if cfg.get("scouted_in"):
        steps.append((True, f"scout: in {cfg['scouted_in']}"))
    elif not (work / "SCOUT.md").exists() or not (work / "structure.json").exists():
        steps.append((False, "scout: write SCOUT.md and structure.json (TOC first)"))
    if st["track"] == "old-print" and not (work / "abbreviations.tsv").exists():
        steps.append((False, "scout: write ABBREVIATIONS.md and abbreviations.tsv from sample pages"))

    if st["mode"] != "translate-only" and "pages" in cfg:
        first, last = cfg["pages"]["first"], cfg["pages"]["last"]
        reading = work / ("diplomatic" if st["track"] == "old-print" else "transcription")
        have, missing = _pages(reading, pattern, first, last)
        st["pages"] = {"have": have, "of": last - first + 1, "missing": _ranges(missing)}
        steps.append((not missing, f"transcribe: {len(missing)} page(s) missing in {reading.name}/ ({_ranges(missing)})"))
        if st["track"] == "old-print":
            ed_have, ed_missing = _pages(work / "edition", pattern, first, last)
            pend = work / "pending.tsv"
            n_pend = max(0, len(pend.read_text(encoding="utf-8").splitlines()) - 1) if pend.exists() else None
            stale = any((work / "edition" / pattern.format(n=n)).exists() and
                        (reading / pattern.format(n=n)).stat().st_mtime >
                        (work / "edition" / pattern.format(n=n)).stat().st_mtime
                        for n in range(first, last + 1) if (reading / pattern.format(n=n)).exists())
            st["edition"] = {"have": ed_have, "pending": n_pend, "stale": stale}
            steps.append((not ed_missing and not stale and n_pend == 0,
                          f"expand: edition layer {'stale' if stale else ''} {len(ed_missing)} missing, "
                          f"{n_pend if n_pend is not None else '?'} pending (python3 -m exscriptor.expand run)"))
        rec = work / "assembled" / "ASSEMBLY.json"
        if cfg.get("assembler"):
            built = [q.stat().st_mtime for q in (work / "assembled").glob("*.md")] \
                if (work / "assembled").exists() else []
            newest_page = max((q.stat().st_mtime for q in reading.glob("*.md")), default=0)
            stale = not built or newest_page > max(built)
            steps.append((not stale, f"assemble ({cfg['assembler']}): "
                                     f"{'stale or missing: rebuild' if stale else f'{len(built)} section(s), current'}"))
        elif rec.exists():
            data = json.loads(rec.read_text(encoding="utf-8"))
            changed = [p["name"] for p in data["pages"] if not Path(p["path"]).exists() or
                       hashlib.sha256(Path(p["path"]).read_bytes()).hexdigest() != p["sha256"]]
            st["assembly"] = {"sections": len(data["sections"]), "pages": len(data["pages"]),
                              "stale_pages": changed[:10]}
            steps.append((not changed and len(data["pages"]) == last - first + 1,
                          f"assemble: {len(changed)} page(s) changed since assembly; "
                          f"{len(data['pages'])}/{last - first + 1} pages assembled"))
        else:
            steps.append((False, "assemble: no assembled/ASSEMBLY.json (python3 -m exscriptor.assemble)"))

    led = work / "ledger.jsonl"
    if led.exists():
        rows = lg.load(led)
        n_open = sum(r["verdict"] == "open" for r in rows)
        st["ledger"] = {"rows": len(rows), "open": n_open}
        steps.append((n_open == 0, f"adjudicate: {n_open} open ledger row(s)"))

    sections = sorted(p.stem for p in (work / "assembled").glob("*.md")) if (work / "assembled").exists() else []
    for lang in langs:
        if lang == "la":
            continue
        tdir = work / f"translation-{lang}"
        done = {p.stem.split(".")[0] for p in tdir.glob("*.md")} if tdir.exists() else set()
        todo = [s for s in sections if s not in done]
        st[f"translation-{lang}"] = {"done": len(done), "todo": len(todo)}
        steps.append((bool(done) and not todo, f"translate {lang}: {len(todo)} section(s) untranslated"))

    manifests = sorted((p for p in (work / "manifests").glob("*.json") if not p.name.endswith(".preflight.json")),
                       key=lambda p: p.stat().st_mtime) if (work / "manifests").exists() else []
    staged = work / "staged.jsonl"
    entries = [json.loads(l) for l in staged.read_text(encoding="utf-8").splitlines() if l.strip()] \
        if staged.exists() else []
    st["manifests"] = []
    for m in manifests:
        why = preflight.verify(m)
        sha = hashlib.sha256(m.read_bytes()).hexdigest()
        hit = [e for e in entries if e.get("sha256") == sha]
        st["manifests"].append({"name": m.name, "preflight": why or "passed",
                                "staged": hit[-1] if hit else None})
        steps.append((why is None, f"preflight {m.name}: {why or 'passed'}"))
        steps.append((bool(hit), f"stage {m.name} (submit wrapper)"))
    if manifests:
        st["manifest"] = {"latest": manifests[-1].name, "preflight": st["manifests"][-1]["preflight"]}
        st["staged"] = st["manifests"][-1]["staged"]
    else:
        steps.append((False, "build the manifest"))

    st["steps"] = [{"done": ok, "step": s} for ok, s in steps]
    pending = [s for ok, s in steps if not ok]
    st["next"] = pending[0] if pending else "verify live, then close out (KB report)"
    return st


def main(
    works: Annotated[list[Path], typer.Argument(help="Work directories")],
    as_json: Annotated[bool, typer.Option("--json")] = False,
):
    """Compute each work's stage from its files and name the next step."""
    results = [compute(w) for w in works if w.is_dir()]
    if as_json:
        print(json.dumps(results, ensure_ascii=False, indent=1))
        return
    if len(results) == 1 and not results[0].get("legacy"):
        st = results[0]
        print(f"{st['work']}  track={st['track']}  mode={st['mode']}")
        for s in st["steps"]:
            print(f"  [{'x' if s['done'] else ' '}] {s['step']}")
        print(f"next: {st['next']}")
        return
    for st in results:
        print(f"{st['work']:45s} {st['next']}")


app = typer.Typer(add_completion=False)
app.command()(main)


if __name__ == "__main__":
    app()
