#!/usr/bin/env python3
"""One defects ledger: every doubt about the text, its verdict, and proof the
fix landed.

Ledgers in a long digitization run fail in two ways, and both were measured:

* **A row is not a decision.** A translator records a doubtful reading and
  correctly does not edit it -- and then nobody takes it to the page. One run
  left 95 recorded doubts that no one adjudicated; by the time they were
  swept, 84 described text that had since changed.
* **A verdict is not a fix.** A row marked "corrected" whose correction never
  reached the page files is reverted by the next assembly; one that reached
  the pages but not the manifest never goes live. A summary saying "all
  fixed" is not evidence.

So the ledger is JSONL with a fixed vocabulary, and ``check`` proves each
verdict against the text layers instead of trusting it.

Row fields (one JSON object per line):

  id         unique string                                        required
  unit       section key or page name where the doubt sits        required
  block      paragraph number in that unit (1-based)              optional
  work       the work's slug, when one ledger serves several works  optional
  layer      language of the text in doubt: "la", "en", ...       default "la"
  category   omission | addition | transposition | misreading |
             normalization | structure | translation              required
  quoted     the text exactly as it stood when raised             required
  issue      what looks wrong                                     required
  proposed   the raiser's guess                                   optional
  verdict    open | corrected | retained | editorial-note |
             withdrawn                                            default "open"
  final      the text as it now stands (corrected / editorial-note)
  rung       the evidence that settled it: context | grammar | parallel |
             witness | ocr | scan                                 required once decided
  evidence   what the evidence showed (page, witness, reading)    required once decided
  raised_by / decided_by                                          optional
  escalate   true: a best guess worth a stronger vision model     optional

The categories are the old critical signs' defect classes (omission,
addition, transposition, misreading) plus the two a pipeline adds
(normalization, structure) and the translator's own (translation).
``retained`` means retained as printed: the print really says it.
``editorial-note`` means the best reading was taken and an inline
``^[N. Editor's note: ...]`` says what the print reads.

Legacy spellings are accepted on read: ``latin-dubious`` and
``latin-apparently-wrong`` -> misreading, ``normalization-suspect`` ->
normalization, ``translation-difficult`` -> translation,
``retained-as-printed`` -> retained, ``resolved`` -> corrected.

Usage:

    python3 -m exscriptor.ledger validate ledger.jsonl
    python3 -m exscriptor.ledger triage ledger.jsonl --text 'assembled/*.md' --text manifests/x.json
    python3 -m exscriptor.ledger check ledger.jsonl --layer pages='transcription/*.md' \\
        --layer manifest=manifests/x-v3.json
    python3 -m exscriptor.ledger summary ledger.jsonl
"""
from __future__ import annotations

import glob as globmod
import json
import re
import unicodedata
from collections import Counter
from pathlib import Path

import typer
from typing_extensions import Annotated

from exscriptor.orthography_screen import drop_editorial_notes

CATEGORIES = {"omission", "addition", "transposition", "misreading", "normalization",
              "structure", "translation"}
VERDICTS = {"open", "corrected", "retained", "editorial-note", "withdrawn"}
RUNGS = {"context", "grammar", "parallel", "witness", "ocr", "scan"}
CATEGORY_ALIASES = {
    "latin-dubious": "misreading", "latin-apparently-wrong": "misreading",
    "normalization-suspect": "normalization", "translation-difficult": "translation",
}
VERDICT_ALIASES = {"retained-as-printed": "retained", "resolved": "corrected",
                   "review": "open", "unresolved": "open"}
EDITOR_NOTE = re.compile(r"\^\[(?:\d+\.\s*)?Editor['’]s note", re.I)


def normalize(row: dict) -> dict:
    row = dict(row)
    row["category"] = CATEGORY_ALIASES.get(row.get("category"), row.get("category"))
    row["verdict"] = VERDICT_ALIASES.get(row.get("verdict", "open"), row.get("verdict", "open"))
    row.setdefault("layer", "la")
    return row


def load(path: Path) -> list[dict]:
    rows = []
    for n, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if line.strip():
            row = normalize(json.loads(line))
            row["_line"] = n
            rows.append(row)
    return rows


def save(rows: list[dict], path: Path) -> None:
    Path(path).write_text("".join(json.dumps({k: v for k, v in r.items() if not k.startswith("_")},
                                             ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


def validate(rows: list[dict]) -> list[str]:
    errs = []
    seen: Counter = Counter(r.get("id") for r in rows)
    for r in rows:
        where = f"line {r.get('_line', '?')} ({r.get('id')})"
        for f in ("id", "unit", "quoted", "issue"):
            if not str(r.get(f) or "").strip():
                errs.append(f"{where}: missing {f}")
        if r.get("id") and seen[r["id"]] > 1:
            errs.append(f"{where}: duplicate id")
        if r.get("category") not in CATEGORIES:
            errs.append(f"{where}: category {r.get('category')!r} not in {sorted(CATEGORIES)}")
        if r["verdict"] not in VERDICTS:
            errs.append(f"{where}: verdict {r['verdict']!r} not in {sorted(VERDICTS)}")
        if r["verdict"] != "open":
            if r.get("rung") not in RUNGS:
                errs.append(f"{where}: decided row needs rung in {sorted(RUNGS)}")
            if not str(r.get("evidence") or "").strip():
                errs.append(f"{where}: decided row needs evidence")
        if r["verdict"] in ("corrected", "editorial-note") and not str(r.get("final") or "").strip():
            errs.append(f"{where}: {r['verdict']} row needs final")
    return errs


def _nfc(s: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", s))


def read_layer(spec: str, language: str | None = None) -> dict[str, str]:
    """{unit: text} from files and/or manifests. File units are the file stem;
    manifest units are section keys (texts in ``language`` only, if given)."""
    out: dict[str, str] = {}
    for item in sorted(globmod.glob(spec, recursive=True)) or [spec]:
        p = Path(item)
        if not p.is_file():
            continue
        if p.suffix == ".json":
            data = json.loads(p.read_text(encoding="utf-8"))
            for key, lang, text in manifest_texts(data):
                if language is None or lang == language:
                    out[key] = out.get(key, "") + "\n\n" + text
        else:
            out[p.stem] = p.read_text(encoding="utf-8")
    return out


def per_work(manifest, walk):
    """Run `walk` over a manifest, one work at a time when it has several.

    Two works in one batch (a text and its commentary) share section keys
    (« q50-a1 » in both), so their keys are qualified as « <work slug>/<key> »;
    a single-work manifest keeps its bare keys.
    """
    works = manifest.get("works") if isinstance(manifest, dict) else None
    if isinstance(works, list) and len(works) > 1:
        for w in works:
            slug = w.get("slug") if isinstance(w, dict) else None
            for key, *rest in walk(w):
                yield (f"{slug}/{key}", *rest)
    else:
        yield from walk(manifest)


def manifest_texts(manifest):
    """(section key, language, content) for every text in a manifest."""
    return per_work(manifest, _texts)


def _texts(manifest):
    def walk(node, key=""):
        if isinstance(node, dict):
            key = node.get("section_key") or node.get("slug") or str(node.get("id") or "") or key
            texts = node.get("texts")
            if isinstance(texts, list):
                for t in texts:
                    if isinstance(t, dict) and isinstance(t.get("content"), str):
                        yield key, t.get("language"), t["content"]
            elif isinstance(texts, dict):
                for lang, t in texts.items():
                    content = t.get("content") if isinstance(t, dict) else t
                    if isinstance(content, str):
                        yield key, lang, content
            for k, v in node.items():
                if k != "texts":
                    yield from walk(v, key)
        elif isinstance(node, list):
            for v in node:
                yield from walk(v, key)
    yield from walk(manifest)


def unit_matches(unit: str, key: str) -> bool:
    """« q12-a3 » names « q12-a3 » and « summa/q12-a3 », never « q12-a30 »;
    « pg-050..056 » names « pg-050 »."""
    def within(a: str, b: str) -> bool:
        return re.search(rf"(?<![\w-]){re.escape(a)}(?![\w-])", b) is not None
    return unit == key or within(unit, key) or within(key, unit)


def _scope(row: dict, layer: dict[str, str]) -> str | None:
    """The text a row is about: its unit's text, else None (unit not in layer)."""
    unit = row["unit"]
    if unit in layer:
        return layer[unit]
    hits = [k for k in layer if unit_matches(unit, k)]
    return "\n\n".join(layer[k] for k in hits) if hits else None


def triage(rows: list[dict], texts: dict[str, str]) -> list[dict]:
    """Open rows whose quoted text no longer occurs where it was raised (or
    anywhere, when the unit is unknown): candidates already fixed. A lead,
    not a verdict -- confirm, then close with evidence."""
    stale = []
    everything = _nfc("\n".join(texts.values()))
    for r in rows:
        if r["verdict"] != "open":
            continue
        scope = _scope(r, texts)
        hay = _nfc(scope) if scope is not None else everything
        if _nfc(r["quoted"]) not in hay:
            stale.append(r)
    return stale


def check(rows: list[dict], layers: dict[str, dict[str, str]]) -> list[str]:
    """Every row decided, and every decision visible in every layer."""
    problems = []
    for r in rows:
        tag = f"{r.get('id')} [{r['unit']}]"
        if r["verdict"] == "open":
            problems.append(f"{tag}: still open ({r['category']}): {r['quoted'][:60]!r}")
            continue
        if r["verdict"] not in ("corrected", "editorial-note"):
            continue
        final, quoted = _nfc(r["final"]), _nfc(r["quoted"])
        for name, layer in layers.items():
            lang = name.split("@", 1)[1] if "@" in name else None
            if lang and lang != r.get("layer", "la"):
                continue
            if r.get("layer", "la") != "la" and name.startswith("pages"):
                continue  # page files carry the source language only
            text = _scope(r, layer)
            if text is None:
                problems.append(f"{tag}: unit not found in layer {name}")
                continue
            raw, text = text, _nfc(text)
            if final not in text:
                problems.append(f"{tag}: final reading not in {name}: {r['final'][:60]!r}")
            elif quoted not in final and quoted in _nfc(drop_editorial_notes(raw)):
                problems.append(f"{tag}: old reading still in {name}: {r['quoted'][:60]!r}")
            if r["verdict"] == "editorial-note" and not EDITOR_NOTE.search(text):
                problems.append(f"{tag}: editorial-note verdict but no Editor's note in {name}")
    return problems


def summary(rows: list[dict]) -> dict:
    return {
        "rows": len(rows),
        "by_verdict": dict(Counter(r["verdict"] for r in rows)),
        "by_category": dict(Counter(r.get("category") for r in rows)),
        "by_rung": dict(Counter(r.get("rung") for r in rows if r["verdict"] != "open")),
        "best_guesses": [{"id": r["id"], "unit": r["unit"], "final": r.get("final"),
                          "evidence": r.get("evidence")}
                         for r in rows if r["verdict"] == "editorial-note" or r.get("escalate")],
    }


app = typer.Typer(add_completion=False, help="Defects ledger: validate, triage, prove, summarize.")


def _layers(specs: list[str]) -> dict[str, dict[str, str]]:
    out = {}
    for spec in specs or []:
        name, _, rest = spec.partition("=")
        if not rest:
            raise typer.BadParameter(f"--layer wants name=glob, got {spec!r}")
        lang = name.split("@", 1)[1] if "@" in name else None
        out[name] = read_layer(rest, lang)
    return out


@app.command("validate")
def validate_cmd(ledger: Annotated[list[Path], typer.Argument(help="Ledger JSONL files")]):
    """Schema check: fields, vocabulary, decided rows carry rung and evidence."""
    bad = 0
    for path in ledger:
        errs = validate(load(path))
        bad += len(errs)
        print(f"{path}: {len(errs)} problem(s)")
        for e in errs:
            print("  ", e)
    if bad:
        raise typer.Exit(1)


@app.command("triage")
def triage_cmd(
    ledger: Annotated[Path, typer.Argument()],
    text: Annotated[list[str], typer.Option(help="Current text: files/globs or manifests (repeatable)")],
):
    """List open rows whose quoted text is gone: probably already fixed."""
    rows = load(ledger)
    texts: dict[str, str] = {}
    for spec in text:
        texts.update(read_layer(spec))
    stale = triage(rows, texts)
    open_rows = [r for r in rows if r["verdict"] == "open"]
    print(f"{len(open_rows)} open, {len(stale)} whose quoted text no longer occurs, "
          f"{len(open_rows) - len(stale)} to take to the page")
    for r in stale:
        print(f"  gone  {r['id']} [{r['unit']}] {r['quoted'][:70]!r}")


@app.command("check")
def check_cmd(
    ledger: Annotated[list[Path], typer.Argument()],
    layer: Annotated[list[str], typer.Option(help="name[@lang]=glob of a text layer (repeatable)")] = None,
):
    """Close-check: no open rows; every correction present in every layer."""
    rows = [r for path in ledger for r in load(path)]
    errs = validate(rows)
    problems = errs + check(rows, _layers(layer))
    print(f"{len(rows)} rows, {len(problems)} problem(s)")
    for p in problems:
        print("  ", p)
    if problems:
        raise typer.Exit(1)


@app.command("summary")
def summary_cmd(ledger: Annotated[list[Path], typer.Argument()]):
    """Counts, and the best-guess sites for the closing report."""
    rows = [r for path in ledger for r in load(path)]
    print(json.dumps(summary(rows), ensure_ascii=False, indent=1))


if __name__ == "__main__":
    app()
