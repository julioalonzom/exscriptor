#!/usr/bin/env python3
"""Papercuts as data: every friction a run hits, with a way to reproduce it.

A papercut log in prose did its first job -- nothing was forgotten -- and
failed its second: a lesson promoted from it into a skill was never checked.
Was the new rule better, or only newer? Checking costs a benchmark, so nobody
checked, and a skill grows by accretion until its rules contradict.

The fix is to make verification cheap, and that starts at capture. An
incident records not only what went wrong but **where the right answer
already lives**: the adjudicated page file, the ledger verdict, the gate that
should have fired. Finished works are a labeled corpus; an incident is a
pointer into it. ``exscriptor.replay`` turns those pointers into fixtures and
re-runs only them.

Row fields (``papercuts.jsonl``, one JSON object per line):

  id        unique string ("pc-<date>-<n>")                         required
  ts        ISO timestamp                                           required
  work      work slug, when the incident belongs to one work        optional
  kind      gate-failure | blocked-call | overturn | alignment-flag |
            retry | tool-error | human                              required
  stage     scout | read | adjudicate | expand | assemble | translate |
            align | preflight | stage | other                        default "other"
  what      the observable, with command or page                     required
  why       the cause; empty means "cause not established"           optional
  fix       where the fix belongs: work-readme | house-style |
            skill:<name> | exscriptor:<module> | agents-md | harness  optional
  status    open | fixed-here | promoted | wontfix                   default "open"
  repro     {unit, page, block, input: [paths], expected: {path, start, end} |
             {ledger: id}, brief: path}                              optional
  signature normalized key for clustering (computed if absent)
  source    auto | human                                             default "human"
  count     times seen (auto incidents merge on signature)           default 1

An entry without ``why`` stays open: a symptom recorded as a cause is how a
hack gets promoted into a skill.

Usage:

    python3 -m exscriptor.incidents add works/w/papercuts.jsonl --kind gate-failure \
        --stage preflight --what "preflight: 3 stray asterisks in q12" --source auto
    python3 -m exscriptor.incidents list works/*/papercuts.jsonl --status open
    python3 -m exscriptor.incidents cluster works/*/papercuts.jsonl
    python3 -m exscriptor.incidents close works/w/papercuts.jsonl pc-... --status promoted --fix skill:schola-translate
    python3 -m exscriptor.incidents validate works/*/papercuts.jsonl
"""
from __future__ import annotations

import datetime as dt
import json
import re
from collections import defaultdict
from pathlib import Path

import typer
from typing_extensions import Annotated

KINDS = {"gate-failure", "blocked-call", "overturn", "alignment-flag", "retry", "tool-error", "human"}
STAGES = {"scout", "read", "adjudicate", "expand", "assemble", "translate", "align", "preflight", "stage", "other"}
STATUSES = {"open", "fixed-here", "promoted", "wontfix"}
FIX_RE = re.compile(r"^(work-readme|house-style|agents-md|harness|skill:[\w.-]+|exscriptor:[\w.]+)$")


def signature(row: dict) -> str:
    """A clustering key: kind, stage, and the `what` with numbers, paths and quotes blanked."""
    what = row.get("what", "").lower()
    what = re.sub(r"[\"'«»“”].*?[\"'«»“”]", "‹q›", what)
    what = re.sub(r"\S*/\S*", "‹path›", what)
    what = re.sub(r"\d+", "N", what)
    what = re.sub(r"\s+", " ", what).strip()[:120]
    return f"{row.get('kind')}|{row.get('stage', 'other')}|{what}"


def read(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for n, line in enumerate(path.read_text().splitlines(), 1):
        if line.strip():
            row = json.loads(line)
            row.setdefault("_file", str(path))
            row.setdefault("_line", n)
            rows.append(row)
    return rows


def _write(path: Path, rows: list[dict]) -> None:
    clean = [{k: v for k, v in r.items() if not k.startswith("_")} for r in rows]
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in clean))


def problems(row: dict) -> list[str]:
    out = []
    for f in ("id", "ts", "kind", "what"):
        if not row.get(f):
            out.append(f"missing {f}")
    if row.get("kind") and row["kind"] not in KINDS:
        out.append(f"kind {row['kind']!r} not in {sorted(KINDS)}")
    if row.get("stage", "other") not in STAGES:
        out.append(f"stage {row['stage']!r} not in {sorted(STAGES)}")
    status = row.get("status", "open")
    if status not in STATUSES:
        out.append(f"status {status!r} not in {sorted(STATUSES)}")
    if row.get("fix") and not FIX_RE.match(row["fix"]):
        out.append(f"fix {row['fix']!r} is not a routing target")
    if status in ("fixed-here", "promoted") and not row.get("why"):
        out.append("closed without a cause (why)")
    if status == "promoted" and not row.get("fix"):
        out.append("promoted without a fix target")
    return out


def add(path: Path, row: dict) -> dict:
    """Append ``row``; an auto incident whose signature is already open bumps its count."""
    rows = read(path)
    row = {k: v for k, v in row.items() if v not in (None, "", [], {})}
    row.setdefault("ts", dt.datetime.now().isoformat(timespec="seconds"))
    row.setdefault("status", "open")
    row.setdefault("source", "human")
    row["signature"] = row.get("signature") or signature(row)
    if row["source"] == "auto":
        for r in rows:
            if r.get("signature") == row["signature"] and r.get("status", "open") == "open":
                r["count"] = r.get("count", 1) + 1
                r["last_ts"] = row["ts"]
                _write(path, rows)
                return r
    if "id" not in row:
        day = row["ts"][:10]
        n = sum(1 for r in rows if r.get("id", "").startswith(f"pc-{day}-")) + 1
        row["id"] = f"pc-{day}-{n}"
    bad = problems(row)
    if bad:
        raise ValueError("; ".join(bad))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


def cluster(rows: list[dict], status: str | None = "open") -> list[dict]:
    """Group incidents by signature across files; the biggest clusters first."""
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        if status and r.get("status", "open") != status:
            continue
        groups[r.get("signature") or signature(r)].append(r)
    out = []
    for sig, rs in groups.items():
        works = sorted({r.get("work") or Path(r["_file"]).parent.name for r in rs if r.get("work") or r.get("_file")})
        out.append({
            "signature": sig,
            "count": sum(r.get("count", 1) for r in rs),
            "works": works,
            "ids": [r["id"] for r in rs],
            "fix": sorted({r["fix"] for r in rs if r.get("fix")}),
            "with_cause": sum(1 for r in rs if r.get("why")),
            "with_repro": sum(1 for r in rs if r.get("repro")),
            "example": rs[0].get("what"),
        })
    out.sort(key=lambda c: (-len(c["works"]), -c["count"]))
    return out


app = typer.Typer(add_completion=False, help="Papercuts as data: capture, cluster, close.")


@app.command("add")
def add_cmd(
    path: Annotated[Path, typer.Argument(help="papercuts.jsonl")],
    kind: Annotated[str, typer.Option()],
    what: Annotated[str, typer.Option()],
    stage: Annotated[str, typer.Option()] = "other",
    why: Annotated[str, typer.Option()] = None,
    fix: Annotated[str, typer.Option()] = None,
    work: Annotated[str, typer.Option()] = None,
    source: Annotated[str, typer.Option()] = "human",
    repro: Annotated[str, typer.Option(help="JSON object")] = None,
):
    """Append an incident (auto incidents merge with an open one of the same signature)."""
    row = {"kind": kind, "what": what, "stage": stage, "why": why, "fix": fix, "work": work,
           "source": source, "repro": json.loads(repro) if repro else None}
    try:
        out = add(path, row)
    except ValueError as e:
        raise typer.BadParameter(str(e))
    print(json.dumps({k: v for k, v in out.items() if not k.startswith("_")}, ensure_ascii=False))


@app.command("list")
def list_cmd(
    paths: Annotated[list[Path], typer.Argument()],
    status: Annotated[str, typer.Option()] = None,
    as_json: Annotated[bool, typer.Option("--json")] = False,
):
    rows = [r for p in paths for r in read(p) if not status or r.get("status", "open") == status]
    if as_json:
        print(json.dumps([{k: v for k, v in r.items() if not k.startswith("_")} for r in rows], ensure_ascii=False, indent=1))
        return
    for r in rows:
        cause = "" if r.get("why") else "  [cause not established]"
        print(f"{r['id']:16s} {r.get('status', 'open'):10s} {r['kind']:14s} x{r.get('count', 1):<3d} {r['what'][:90]}{cause}")


@app.command("cluster")
def cluster_cmd(
    paths: Annotated[list[Path], typer.Argument()],
    status: Annotated[str, typer.Option()] = "open",
    as_json: Annotated[bool, typer.Option("--json")] = False,
):
    """Group incidents across works: a cluster seen in several works is a candidate rule."""
    cl = cluster([r for p in paths for r in read(p)], status)
    if as_json:
        print(json.dumps(cl, ensure_ascii=False, indent=1))
        return
    for c in cl:
        print(f"x{c['count']:<3d} works={len(c['works'])} cause={c['with_cause']}/{len(c['ids'])} "
              f"repro={c['with_repro']}/{len(c['ids'])}  {c['example'][:80]}")


@app.command("close")
def close_cmd(
    path: Annotated[Path, typer.Argument()],
    incident_id: Annotated[str, typer.Argument()],
    status: Annotated[str, typer.Option()],
    why: Annotated[str, typer.Option()] = None,
    fix: Annotated[str, typer.Option()] = None,
    evidence: Annotated[str, typer.Option(help="e.g. the replay comparison that verified the fix")] = None,
):
    rows = read(path)
    hit = [r for r in rows if r.get("id") == incident_id]
    if not hit:
        raise typer.BadParameter(f"no incident {incident_id} in {path}")
    r = hit[0]
    r["status"] = status
    for k, v in (("why", why), ("fix", fix), ("evidence", evidence)):
        if v:
            r[k] = v
    bad = problems(r)
    if bad:
        raise typer.BadParameter("; ".join(bad))
    _write(path, rows)


@app.command("validate")
def validate_cmd(paths: Annotated[list[Path], typer.Argument()]):
    n = 0
    for p in paths:
        for r in read(p):
            for msg in problems(r):
                n += 1
                print(f"{p}:{r['_line']}: {r.get('id', '?')}: {msg}")
    raise typer.Exit(1 if n else 0)


if __name__ == "__main__":
    app()
