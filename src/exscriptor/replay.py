#!/usr/bin/env python3
"""Cheap verification: replay only the units a change is meant to fix.

A proposed rule (a skill edit, a brief change, a new gate) is worth promoting
only if it makes the output better where it was meant to and no worse
elsewhere. A full benchmark answers that and costs too much to run per
change, so it was never run, and the skills grew unverified. This module
answers it with what finished works already hold:

* **The ground truth is a byproduct.** An adjudicated page file is the right
  answer for that page; an incident (``exscriptor.incidents``) points at the
  page and the span it went wrong on.
* **A fixture is a pointer, not a copy**: work, page, the expected file and
  optionally a span (``start``/``end`` anchor strings). A reading is scored
  only on the span's aligned window, so a whole page re-read is judged at the
  site that motivated the change.
* **Scoring is deterministic**: character and word error rates against the
  adjudicated text. No model judges a model.
* **Two sets**: *targets* (the incident's units: the change must improve
  them) and *sentinels* (a fixed spread of pages across works: the change
  must not regress them beyond a tolerance).

Fixtures (JSONL):

  id        unique                                                 required
  kind      reading | gate                                         default reading
  role      target | sentinel                                      default target
  work      work dir (relative to --root)                          reading
  page      page number (the image comes from ``exscriptor.render``)  reading
  expected  {"path": ..., "start": "anchor", "end": "anchor"}      reading
  bad       path of a text the gate must flag                      gate
  incident  the incident id it came from                           optional

Commands:

    replay sentinel works/a works/b --n 10 --out sentinels.jsonl
    replay from-incidents works/*/papercuts.jsonl --out targets.jsonl
    replay from-ledger works/a --limit 40 --out sites.jsonl   # adjudicated hard sites
    replay run fixtures.jsonl --label old --cmd 'reader {image} {brief_old} > {out}' --samples 2 --results r.jsonl
    replay run fixtures.jsonl --label new --cmd 'reader {image} {brief_new} > {out}' --samples 2 --results r.jsonl
    replay compare r.jsonl --base old --cand new          # exit 1 unless verified
    replay gate fixtures.jsonl --cmd 'python3 -m exscriptor.check_markers {file}' --clean 'works/*/transcription/*.md'

``--cmd`` is the harness's reader: any shell command, with ``{image}``,
``{page}``, ``{work}``, ``{id}``, ``{sample}`` and ``{out}`` substituted
(shell-quoted). The reading is read from ``{out}`` if the command wrote it,
else from stdout. Free tests use a fake command; a real run uses whatever
model route the job is authorized for.
"""
from __future__ import annotations

import difflib
import hashlib
import json
import random
import re
import shlex
import statistics
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from glob import glob
from pathlib import Path

import typer
from typing_extensions import Annotated

from exscriptor import incidents as inc
from exscriptor import render


# ---------------------------------------------------------------- scoring

def normalize(text: str, mode: str = "ws") -> str:
    """ws: collapse whitespace. letters: also drop punctuation/markup and casefold."""
    if mode == "letters":
        text = re.sub(r"[^\w\s]", " ", text.casefold())
    return re.sub(r"\s+", " ", text).strip()


def _lev(a, b) -> int:
    if len(a) < len(b):
        a, b = b, a
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i]
        for j, y in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x != y)))
        prev = cur
    return prev[-1]


def distance(expected: str, candidate: str) -> dict:
    """Edit distances, exact within each differing hunk of a word alignment."""
    ew, cw = expected.split(), candidate.split()
    char_edits = word_edits = 0
    sm = difflib.SequenceMatcher(None, ew, cw, autojunk=False)
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            continue
        word_edits += _lev(ew[i1:i2], cw[j1:j2])
        char_edits += _lev(" ".join(ew[i1:i2]), " ".join(cw[j1:j2])) + (1 if (i1 == i2) != (j1 == j2) else 0)
    n_chars, n_words = max(len(expected), 1), max(len(ew), 1)
    return {"cer": round(char_edits / n_chars, 5), "wer": round(word_edits / n_words, 5),
            "char_edits": char_edits, "word_edits": word_edits, "chars": len(expected)}


def _span(words: list[str], start: str | None, end: str | None) -> tuple[int, int]:
    """Word indices [i, j) of the span from the anchor ``start`` to the end of anchor ``end``."""
    text = " ".join(words)
    i0, j0 = 0, len(text)
    if start:
        k = text.find(normalize(start))
        if k < 0:
            raise ValueError(f"start anchor not found: {start!r}")
        i0 = k
    if end:
        k = text.find(normalize(end), i0)
        if k < 0:
            raise ValueError(f"end anchor not found: {end!r}")
        j0 = k + len(normalize(end))
    return len(text[:i0].split()), len(text[:j0].split())


def score_span(expected_full: str, candidate: str, start: str | None = None, end: str | None = None,
               mode: str = "ws") -> dict:
    """Score ``candidate`` only on the window aligned to the expected span."""
    ef, cf = normalize(expected_full, mode), normalize(candidate, mode)
    ew, cw = ef.split(), cf.split()
    if mode != "ws":
        start, end = (normalize(a, mode) if a else a for a in (start, end))
    i, j = _span(ew, start, end) if (start or end) else (0, len(ew))
    if (i, j) == (0, len(ew)):
        return distance(ef, cf)
    sm = difflib.SequenceMatcher(None, ew, cw, autojunk=False)
    emap: dict[int, int] = {}
    for a, b, size in sm.get_matching_blocks():
        for k in range(size):
            emap[a + k] = b + k
    scale = len(cw) / max(len(ew), 1)
    # The window starts at the candidate word aligned to the nearest matched
    # expected word at or before i, shifted by the gap; it ends likewise from
    # the nearest matched word at or after j-1. Without any match: proportional.
    k = next((k for k in range(i, -1, -1) if k in emap), None)
    ci = emap[k] + (i - k) if k is not None else round(i * scale)
    k = next((k for k in range(j - 1, len(ew)) if k in emap), None)
    cj = emap[k] - (k - (j - 1)) + 1 if k is not None else round(j * scale)
    ci = min(max(ci, 0), len(cw))
    cj = min(max(cj, ci), len(cw))
    return distance(" ".join(ew[i:j]), " ".join(cw[ci:cj]))


# ---------------------------------------------------------------- fixtures

def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(l) for l in Path(path).read_text().splitlines() if l.strip()] if Path(path).exists() else []


def expected_text(fx: dict, root: Path) -> str:
    exp = fx["expected"]
    return exp["text"] if "text" in exp else (root / exp["path"]).read_text()


def _source_dir(work: Path) -> str:
    meta = render._meta(work)
    return "diplomatic" if meta.get("track") == "old-print" else "transcription"


def sentinels(works: list[Path], n: int, root: Path, seed: int = 0) -> list[dict]:
    """``n`` pages spread evenly over ``works`` (round-robin), deterministic for ``seed``."""
    rng = random.Random(seed)
    pools = []
    for w in works:
        d = w / _source_dir(w)
        pages = sorted(d.glob("pg-*.md")) if d.is_dir() else []
        rng.shuffle(pages)
        if pages:
            pools.append((w, pages))
    out, k = [], 0
    while len(out) < n and any(p for _, p in pools):
        w, pages = pools[k % len(pools)]
        k += 1
        if not pages:
            continue
        pg = pages.pop()
        num = int(re.search(r"(\d+)", pg.stem).group(1))
        out.append({"id": f"sentinel:{w.name}:{num}", "kind": "reading", "role": "sentinel",
                    "work": str(w.relative_to(root) if w.is_relative_to(root) else w), "page": num,
                    "expected": {"path": str(pg.relative_to(root) if pg.is_relative_to(root) else pg)}})
    return out


def from_incidents(rows: list[dict]) -> list[dict]:
    """Fixtures from incidents whose ``repro`` names an expected text or a bad input."""
    out = []
    for r in rows:
        rp = r.get("repro") or {}
        base = {"incident": r["id"], "role": "target"}
        if rp.get("expected") and rp.get("page") is not None:
            out.append({**base, "id": f"{r['id']}", "kind": "reading", "work": rp.get("work") or r.get("work"),
                        "page": rp["page"], "expected": rp["expected"]})
        elif rp.get("bad"):
            out.append({**base, "id": f"{r['id']}", "kind": "gate", "bad": rp["bad"]})
    return out


LATE = ("preflight", "translator", "reviser", "alignment", "audit", "live")


def page_of(work: Path, unit: str) -> tuple[int, Path] | None:
    """(page number, page file) for a ledger unit naming a page (``pg-014``), else None."""
    m = re.fullmatch(r"(?:pg|p)-?(\d+)", unit or "")
    if not m or not (work / "work.json").exists():
        return None
    n = int(m.group(1))
    files = sorted((work / _source_dir(work)).glob(f"*{n:03d}.md")) or sorted((work / _source_dir(work)).glob(f"*{n}.md"))
    return (n, files[0]) if files else None


def site_anchors(page_text: str, phrase: str, context: int = 3) -> dict | None:
    """Start/end anchors spanning ``phrase`` plus ``context`` words each side, if it occurs once."""
    words = normalize(page_text).split()
    key = lambda w: re.sub(r"[^\w]", "", w.casefold())
    keys, target = [key(w) for w in words], [k for k in (key(w) for w in normalize(phrase).split()) if k]
    if not target:
        return None
    hits = [i for i in range(len(keys) - len(target) + 1) if keys[i:i + len(target)] == target]
    if len(hits) != 1:
        return None
    i = hits[0]
    a, b = max(0, i - context), min(len(words), i + len(target) + context)
    return {"start": " ".join(words[a:min(a + 2, b)]), "end": " ".join(words[max(b - 2, a):b])}


def correct_text(row: dict) -> str | None:
    """What the print says at a decided ledger site: ``final`` if changed, ``quoted`` if retained."""
    v = row.get("verdict")
    if v in ("corrected", "editorial-note"):
        return row.get("final")
    if v == "retained":
        return row.get("quoted")
    return None


def from_ledger(work: Path, root: Path, categories=("misreading", "omission", "addition", "transposition")) -> list[dict]:
    """Reading fixtures from a work's decided ledger sites: each a hard spot with its adjudicated answer."""
    out = []
    lp = work / "ledger.jsonl"
    rows = [json.loads(l) for l in lp.read_text().splitlines() if l.strip()] if lp.exists() else []
    texts: dict[Path, str] = {}
    for r in rows:
        if r.get("category") not in categories or r.get("layer", "la") != "la":
            continue
        good, loc = correct_text(r), page_of(work, r.get("unit", ""))
        if not good or not loc:
            continue
        n, f = loc
        texts.setdefault(f, f.read_text())
        anchors = site_anchors(texts[f], good)
        if not anchors:
            continue
        rel = lambda p: str(p.relative_to(root)) if p.is_relative_to(root) else str(p)
        out.append({"id": f"site:{work.name}:{r['id']}", "kind": "reading", "role": "target",
                    "work": rel(work), "page": n, "expected": {"path": rel(f), **anchors}})
    return out


# ---------------------------------------------------------------- runs

def _sha(path: str | None) -> str | None:
    if path and Path(path).exists():
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:12]
    return None


def run_one(fx: dict, cmd: str, label: str, sample: int, root: Path, mode: str, timeout: int) -> dict:
    row = {"fixture": fx["id"], "role": fx.get("role", "target"), "label": label, "sample": sample}
    try:
        work = root / fx["work"]
        image = render.page_image(work, int(fx["page"]))
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "out.md"
            subs = {"image": image, "page": fx["page"], "work": work, "id": fx["id"], "sample": sample, "out": out}
            line = cmd.format(**{k: shlex.quote(str(v)) for k, v in subs.items()})
            proc = subprocess.run(line, shell=True, capture_output=True, text=True, timeout=timeout, cwd=root)
            if proc.returncode != 0:
                raise RuntimeError(f"exit {proc.returncode}: {proc.stderr.strip()[-300:]}")
            cand = out.read_text() if out.exists() else proc.stdout
        exp = fx["expected"]
        row.update(score_span(expected_text(fx, root), cand, exp.get("start"), exp.get("end"), mode))
    except Exception as e:  # a failed sample is a result, not a crash
        row["error"] = str(e)
    return row


def run(fixtures: list[dict], cmd: str, label: str, samples: int, results: Path, root: Path,
        mode: str = "ws", jobs: int = 1, timeout: int = 600, brief: str | None = None) -> list[dict]:
    done = {(r["fixture"], r["label"], r["sample"]) for r in read_jsonl(results) if "error" not in r}
    todo = [(fx, s) for fx in fixtures if fx.get("kind", "reading") == "reading"
            for s in range(samples) if (fx["id"], label, s) not in done]
    brief_sha = _sha(brief)
    rows = []
    with ThreadPoolExecutor(max_workers=max(jobs, 1)) as pool:
        for row in pool.map(lambda t: run_one(t[0], cmd, label, t[1], root, mode, timeout), todo):
            if brief_sha:
                row["brief_sha"] = brief_sha
            rows.append(row)
            with results.open("a") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return rows


def compare(rows: list[dict], base: str, cand: str, metric: str = "cer",
            tolerance: float = 0.005, min_gain: float = 0.0) -> dict:
    """Verdict on a candidate: targets must improve, sentinels must not regress."""
    by: dict[tuple[str, str], list[float]] = {}
    role: dict[str, str] = {}
    errors = sum(1 for r in rows if "error" in r and r["label"] in (base, cand))
    for r in rows:
        if "error" in r or r["label"] not in (base, cand):
            continue
        by.setdefault((r["fixture"], r["label"]), []).append(r[metric])
        role[r["fixture"]] = r.get("role", "target")
    fixtures = sorted({f for f, _ in by if (f, base) in by and (f, cand) in by})
    per = []
    for f in fixtures:
        b, c = by[(f, base)], by[(f, cand)]
        spread = max(max(b) - min(b), max(c) - min(c))
        delta = statistics.mean(c) - statistics.mean(b)
        per.append({"fixture": f, "role": role[f], "base": round(statistics.mean(b), 5),
                    "cand": round(statistics.mean(c), 5), "delta": round(delta, 5),
                    "within_noise": abs(delta) <= spread})
    tg = [p for p in per if p["role"] == "target"]
    sn = [p for p in per if p["role"] == "sentinel"]
    tg_delta = statistics.mean(p["delta"] for p in tg) if tg else 0.0
    sn_delta = statistics.mean(p["delta"] for p in sn) if sn else 0.0
    regressions = [p["fixture"] for p in sn if p["delta"] > tolerance and not p["within_noise"]]
    reasons = []
    if not tg:
        reasons.append("no target fixture scored under both labels")
    elif not tg_delta < -min_gain:
        reasons.append(f"targets did not improve (mean Δ{metric} {tg_delta:+.4f})")
    elif all(p["within_noise"] for p in tg):
        reasons.append("target gains are within sample noise: add samples")
    if sn_delta > tolerance:
        reasons.append(f"sentinels regressed (mean Δ{metric} {sn_delta:+.4f})")
    if regressions:
        reasons.append(f"sentinel regressions: {', '.join(regressions)}")
    if errors:
        reasons.append(f"{errors} failed samples")
    return {"verified": not reasons, "reasons": reasons, "metric": metric,
            "targets": {"n": len(tg), "mean_delta": round(tg_delta, 5)},
            "sentinels": {"n": len(sn), "mean_delta": round(sn_delta, 5)},
            "fixtures": per}


def gate(fixtures: list[dict], cmd: str, clean: list[str], root: Path, max_fp: int = 0,
         timeout: int = 120) -> dict:
    """A check must flag every bad input (exit != 0) and stay quiet on clean, adjudicated text."""
    def flags(path: Path) -> bool:
        line = cmd.format(file=shlex.quote(str(path)))
        return subprocess.run(line, shell=True, capture_output=True, cwd=root, timeout=timeout).returncode != 0
    bad = [fx for fx in fixtures if fx.get("kind") == "gate"]
    missed = [fx["id"] for fx in bad if not flags(root / fx["bad"])]
    files = sorted({Path(p) for g in clean for p in glob(str(root / g))})
    fps = [str(p) for p in files if flags(p)]
    reasons = []
    if not bad:
        reasons.append("no gate fixture")
    if missed:
        reasons.append(f"missed: {', '.join(missed)}")
    if len(fps) > max_fp:
        reasons.append(f"{len(fps)} false positives on clean text (max {max_fp})")
    return {"verified": not reasons, "reasons": reasons, "caught": len(bad) - len(missed), "bad": len(bad),
            "clean_files": len(files), "false_positives": fps[:50]}


# ---------------------------------------------------------------- CLI

app = typer.Typer(add_completion=False, help="Verify a proposed change on the units it is meant to fix.")
RootOpt = Annotated[Path, typer.Option(help="Paths in fixtures are relative to this")]


def _dump(rows: list[dict], out: Path | None):
    text = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
    if out:
        out.write_text(text)
        print(f"{len(rows)} fixtures -> {out}")
    else:
        print(text, end="")


@app.command("sentinel")
def sentinel_cmd(works: Annotated[list[Path], typer.Argument()], n: int = 10, seed: int = 0,
                 out: Path = None, root: RootOpt = Path(".")):
    """Pick n sentinel pages spread across finished works."""
    _dump(sentinels([w.absolute() for w in works], n, root.absolute(), seed), out)


@app.command("from-incidents")
def from_incidents_cmd(paths: Annotated[list[Path], typer.Argument()], out: Path = None,
                       status: str = "open"):
    """Target fixtures from incidents that carry a repro."""
    rows = [r for p in paths for r in inc.read(p) if not status or r.get("status", "open") == status]
    _dump(from_incidents(rows), out)


@app.command("from-ledger")
def from_ledger_cmd(works: Annotated[list[Path], typer.Argument()], out: Path = None,
                    limit: int = 0, seed: int = 0, root: RootOpt = Path(".")):
    """Hard-site fixtures from works' decided ledger rows (optionally a seeded sample of `limit`)."""
    fx = [f for w in works for f in from_ledger(w.absolute(), root.absolute())]
    if limit and len(fx) > limit:
        fx = random.Random(seed).sample(fx, limit)
    _dump(fx, out)


@app.command("run")
def run_cmd(fixtures: Annotated[list[Path], typer.Argument()],
            label: Annotated[str, typer.Option(help="e.g. old / new")],
            cmd: Annotated[str, typer.Option(help="Reader command template")],
            results: Annotated[Path, typer.Option()],
            samples: int = 2, jobs: int = 1, timeout: int = 600,
            mode: Annotated[str, typer.Option(help="ws | letters")] = "ws",
            brief: Annotated[str, typer.Option(help="Brief file, hashed into each row")] = None,
            root: RootOpt = Path(".")):
    """Run the reader on each reading fixture; resumable (done samples are skipped)."""
    fx = [f for p in fixtures for f in read_jsonl(p)]
    rows = run(fx, cmd, label, samples, results, root.absolute(), mode, jobs, timeout, brief)
    errs = sum(1 for r in rows if "error" in r)
    print(f"{len(rows)} samples ({errs} failed) -> {results}")


@app.command("compare")
def compare_cmd(results: Annotated[Path, typer.Argument()], base: str = "old", cand: str = "new",
                metric: str = "cer", tolerance: float = 0.005, min_gain: float = 0.0,
                as_json: Annotated[bool, typer.Option("--json")] = False):
    """Exit 0 only if the candidate improves its targets without regressing sentinels."""
    v = compare(read_jsonl(results), base, cand, metric, tolerance, min_gain)
    if as_json:
        print(json.dumps(v, ensure_ascii=False, indent=1))
    else:
        for p in v["fixtures"]:
            noise = "  (noise)" if p["within_noise"] else ""
            print(f"{p['role']:8s} {p['fixture']:40s} {p['base']:.4f} -> {p['cand']:.4f}  {p['delta']:+.4f}{noise}")
        print(("VERIFIED" if v["verified"] else "NOT VERIFIED") + "".join(f"\n  - {r}" for r in v["reasons"]))
    raise typer.Exit(0 if v["verified"] else 1)


@app.command("gate")
def gate_cmd(fixtures: Annotated[list[Path], typer.Argument()],
             cmd: Annotated[str, typer.Option(help="Check command with {file}; nonzero exit = flagged")],
             clean: Annotated[list[str], typer.Option(help="Glob of adjudicated text (repeatable)")],
             max_fp: int = 0, root: RootOpt = Path(".")):
    """Verify a new or changed gate: catches the bad inputs, quiet on the finished corpus."""
    v = gate([f for p in fixtures for f in read_jsonl(p)], cmd, clean, root.absolute(), max_fp)
    print(json.dumps(v, ensure_ascii=False, indent=1))
    raise typer.Exit(0 if v["verified"] else 1)


if __name__ == "__main__":
    app()
