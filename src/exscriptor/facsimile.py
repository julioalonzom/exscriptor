"""Facsimile offsets checked against the work's own page files.

A facsimile row says "this leaf begins at character ``text_offset`` of this
section's source text". An OCR aligner gets that roughly right: a line early,
or a few hundred characters late when the page opens above an inline note,
and a score window that contains the leaf passes either. The work's page
files are exact: ``<work>/edition/<leaf>.md`` starts at the leaf's first
printed character. So the leaf's opening is located in the section's text by
literal search, notes and markup aside, and must sit at the recorded offset.

A leaf that begins mid-word (the previous one ended « sapien- ») is found
inside the joined word, and the offset is the character where it begins.
A row with offset 0 holds the section's start (a heading below the previous
section's tail on the same leaf); ``facsimile-start`` checks that. Leaves
without a page file (blank, stamp, plate) are not checked.

    python3 -m exscriptor.facsimile works/x/manifests/x-v1.json          # audit
    python3 -m exscriptor.facsimile works/x/manifests/x-v1.json --fix    # rewrite <work>/facsimile-manifest.json

``--fix`` sets every offset to the located opening and drops a row whose leaf
shares no text with its section when the same leaf is filed under another
section (a misfiling). It writes ``<work>/qa-reports/facsimile-offset-audit.json``.
Then rebuild the manifest and rerun preflight.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import typer
from typing_extensions import Annotated

PROBE = 60


def _norm(text: str) -> tuple[str, list[int]]:
    """Text without inline notes, emphasis or heading marks, whitespace runs as
    one space; with each kept character's index in the original."""
    out, idx, i, depth = [], [], 0, 0
    while i < len(text):
        if text.startswith("^[", i):
            depth, i = depth + 1, i + 2
            continue
        c = text[i]
        if depth:
            depth += {"[": 1, "]": -1}.get(c, 0)
        elif c.isspace():
            if out and out[-1] != " ":
                out.append(" ")
                idx.append(i)
        elif c not in "*_#>":
            out.append(c)
            idx.append(i)
        i += 1
    return "".join(out), idx


def page_opening(page: str) -> str:
    body = re.sub(r"<!--.*?-->", "", page, flags=re.S)
    return _norm(body)[0].strip()


def locate(section: str, page: str, near: int = 0) -> int | None:
    """Index in ``section`` where the leaf whose page file is ``page`` begins."""
    s, sidx = _norm(section)
    opening = page_opening(page)
    if not opening:
        return None
    first, _, rest = opening.partition(" ")
    probe = rest[:PROBE]
    if not probe:
        hits = [m.start() for m in re.finditer(re.escape(first), s)]
        return min((sidx[h] for h in hits), key=lambda o: abs(o - near), default=None)
    cands = []
    for m in re.finditer(re.escape(" " + probe), s):
        head = s[:m.start()]
        if head.endswith(first):          # « first rest », or « …first rest » mid-word
            cands.append(m.start() - len(first))
    return min((sidx[c] for c in cands), key=lambda o: abs(o - near), default=None)


def _source_texts(work: dict, language: str) -> dict[str, str]:
    out = {}
    for s in work.get("sections") or []:
        for t in s.get("texts") or []:
            if t.get("language") == language and t.get("role") != "translation":
                out[s["slug"]] = t["content"]
    return out


def audit(manifest: dict, work_dir: Path, language: str = "la") -> list[dict]:
    """One record per checked row: the row, where its leaf opens, and a
    finding when the two differ (``found`` None: the leaf is not in the section)."""
    pages = work_dir / "edition"
    out = []
    if not pages.is_dir():
        return out
    for w in manifest.get("works") or []:
        texts = _source_texts(w, language)
        for r in w.get("facsimile") or []:
            off = r.get("text_offset")
            page = pages / (Path(r["filename"]).stem + ".md")
            slug = str(r.get("section_path") or "").split("/")[-1]
            if off is None or not page.exists() or slug not in texts:
                continue
            found = locate(texts[slug], page.read_text(encoding="utf-8"), off)
            if off == 0 and found != 0:
                continue                    # section begins lower on this leaf
            if found == off:
                continue
            where = f"{r['section_path']} {r['filename']}"
            out.append({"row": r, "found": found,
                        "finding": f"{where}: offset {off}, the leaf opens at {found}" if found is not None
                        else f"{where}: the leaf's opening is not in this section's text"})
    return out


def gate(manifest: dict, work_dir: Path, language: str = "la") -> list[str]:
    return [a["finding"] for a in audit(manifest, work_dir, language)]


def fix(manifest: dict, work_dir: Path, language: str = "la") -> dict:
    """Rewrite ``<work>/facsimile-manifest.json`` from the audit."""
    path = work_dir / "facsimile-manifest.json"
    rows = json.loads(path.read_text(encoding="utf-8"))
    found = audit(manifest, work_dir, language)
    key = lambda r: (r["filename"], r["section_path"])
    by_key = {key(a["row"]): a for a in found}
    filed = {}
    for r in rows:
        filed[r["filename"]] = filed.get(r["filename"], 0) + 1
    moved, dropped, open_ = [], [], []
    kept = []
    for r in rows:
        a = by_key.get(key(r))
        if a is None:
            kept.append(r)
        elif a["found"] is not None:
            moved.append({**key_dict(r), "from": r["text_offset"], "to": a["found"]})
            kept.append({**r, "text_offset": a["found"]})
        elif filed[r["filename"]] > 1:
            dropped.append(key_dict(r))
        else:
            open_.append(a["finding"])
            kept.append(r)
    for p in {d["section_path"] for d in dropped}:
        for i, r in enumerate(x for x in kept if x["section_path"] == p):
            r["sequence"] = i
    path.write_text(json.dumps(kept, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    report = {"moved": moved, "dropped_misfiled": dropped, "unresolved": open_}
    qa = work_dir / "qa-reports"
    qa.mkdir(exist_ok=True)
    (qa / "facsimile-offset-audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return report


def key_dict(r: dict) -> dict:
    return {"filename": r["filename"], "section_path": r["section_path"]}


def main(
    manifest: Annotated[Path, typer.Argument(help="The built manifest carrying the facsimile")],
    work_dir: Annotated[Path | None, typer.Option(help="Work dir (default: the manifests dir's parent)")] = None,
    language: Annotated[str, typer.Option(help="Source language of the offsets")] = "la",
    do_fix: Annotated[bool, typer.Option("--fix", help="Rewrite <work>/facsimile-manifest.json")] = False,
):
    """Check (or fix) every facsimile offset against the leaf's page file."""
    from exscriptor.preflight import default_work_dir
    wd = work_dir or default_work_dir(manifest)
    m = json.loads(manifest.read_text(encoding="utf-8"))
    if do_fix:
        rep = fix(m, wd, language)
        print(f"moved {len(rep['moved'])}, dropped {len(rep['dropped_misfiled'])} misfiled, "
              f"unresolved {len(rep['unresolved'])} -> {wd / 'facsimile-manifest.json'}")
        for f in rep["unresolved"]:
            print("  " + f)
        print("next: rebuild the manifest, then python3 -m exscriptor.preflight")
        raise typer.Exit(1 if rep["unresolved"] else 0)
    found = gate(m, wd, language)
    for f in found[:20]:
        print("  " + f)
    print(f"{len(found)} offset finding(s)" + (" (fix: --fix, rebuild, preflight)" if found else ""))
    raise typer.Exit(1 if found else 0)


app = typer.Typer(add_completion=False)
app.command()(main)


if __name__ == "__main__":
    app()
