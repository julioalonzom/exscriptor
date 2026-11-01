#!/usr/bin/env python3
"""Blind-read flagged sites through the Gemini Batch API (work-agnostic).

Input: a sites.jsonl as `shared misreading-sites` + `shared crop` write it
(each row: id, unit, context with the site as `[…]`, crop, optional zoom).
One request per site: the crop, its zoom, and a prompt that names neither
form, only the neighbouring words. Readings land in <out>/readings.jsonl,
one row per site id; a re-run skips ids already read.

Usage (paid route: only on a job the owner authorized):
  python3 -m exscriptor.gemini_sites --sites sites.jsonl --out runs/sites \
      --model models/<name> --poll-wait 3600
"""
from __future__ import annotations

import base64, json, time
from pathlib import Path

import typer
from typing_extensions import Annotated

from exscriptor.gemini_batch_run import call, make_config

PROMPT = """These images are from one page of a Latin book printed in the 17th century: a strip of the page, then an enlargement of the same place.

Find the passage that reads, in modernized spelling:
  {context}
The gap […] is ONE printed word (it may be split by a line-end hyphen; then give both parts joined, with the hyphen).

Transcribe that word exactly as printed, letter by letter: long s as ſ, æ and œ as printed, accents and abbreviation marks as printed (a nasal bar as a tilde over the vowel, q; for -que), u and v as printed. Do not correct the printer, do not modernize, do not guess from the sense: if a letter is unclear, give the letter you see and say so in note.

If the passage is not in the images, set word to "" and found to false."""

# Thinking counts against the output limit: at 2000, 4 of 24 answers were cut mid-JSON (Hurtado pilot 3).
MAX_OUTPUT = 8192

SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "found": {"type": "BOOLEAN"},
        "word": {"type": "STRING"},
        "printed_line": {"type": "STRING", "description": "the whole printed line holding the word, as printed"},
        "confidence": {"type": "STRING", "enum": ["high", "medium", "low"]},
        "note": {"type": "STRING"},
    },
    "required": ["found", "word", "printed_line", "confidence", "note"],
}


def image_part(path: Path) -> dict:
    mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    return {"inline_data": {"mime_type": mime, "data": base64.b64encode(path.read_bytes()).decode()}}


def make_site_request(site: dict, prompt: str = PROMPT) -> dict:
    parts = [{"text": prompt.format(context=site["context"])}, image_part(Path(site["crop"]))]
    if site.get("zoom"):
        parts.append(image_part(Path(site["zoom"])))
    config = make_config() | {"responseMimeType": "application/json", "responseSchema": SCHEMA,
                              "maxOutputTokens": MAX_OUTPUT}
    return {"metadata": {"key": site["id"]},
            "request": {"contents": [{"role": "user", "parts": parts}], "generationConfig": config}}


def read_rows(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()] if path.is_file() else []


def submit(sites: list[dict], out: Path, model: str, chunk: int):
    jobs_path = out / "jobs.json"
    jobs = json.loads(jobs_path.read_text()) if jobs_path.is_file() else []
    # A reading that failed (cut or unparsed) is sent again; so is a site of a failed batch.
    sent = {k for j in jobs if not j.get("harvested") for k in j["ids"]} | {
        r["id"] for r in read_rows(out / "readings.jsonl") if "error" not in r}
    todo = [s for s in sites if s["id"] not in sent]
    for i in range(0, len(todo), chunk):
        grp = todo[i:i + chunk]
        payload = {"batch": {"display_name": f"sites-{grp[0]['id']}-{grp[-1]['id']}",
                             "input_config": {"requests": {"requests": [make_site_request(s) for s in grp]}}}}
        resp = call(f"{model}:batchGenerateContent", payload, method="POST")
        jobs.append({"name": resp["name"], "model": model, "ids": [s["id"] for s in grp], "state": "?"})
        jobs_path.write_text(json.dumps(jobs, indent=1))
        print(f"submitted {grp[0]['id']}-{grp[-1]['id']} -> {resp['name']}")


def harvest(st: dict, sites: dict, out: Path, ids: list[str] = ()) -> int:
    items = ((st.get("response") or {}).get("inlinedResponses") or {}).get("inlinedResponses") or []
    got = 0
    with (out / "readings.jsonl").open("a") as fh:
        for n, it in enumerate(items):
            r = it.get("response") or {}
            key = (it.get("metadata") or {}).get("key") or it.get("key") or (ids[n] if n < len(ids) else None)
            parts = (((r.get("candidates") or [{}])[0].get("content") or {}).get("parts")) or []
            text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
            try:
                reading = json.loads(text)
            except ValueError:
                reading = {"error": it.get("error") or text[:300]}
            site = sites.get(key, {})
            fh.write(json.dumps({"id": key, "unit": site.get("unit"), "edition": site.get("a"),
                                 "near": site.get("b"), **reading,
                                 "usage": r.get("usageMetadata"), "model": r.get("modelVersion")},
                                ensure_ascii=False) + "\n")
            got += 1
    return got


def poll(sites: list[dict], out: Path, wait_s: int):
    jobs_path = out / "jobs.json"
    jobs = json.loads(jobs_path.read_text())
    by_id = {s["id"]: s for s in sites}
    deadline = time.time() + wait_s
    while True:
        pending = [j for j in jobs if not j.get("harvested")]
        for j in pending:
            st = call(j["name"])
            j["state"] = st["metadata"].get("state", "?")
            if j["state"] == "BATCH_STATE_SUCCEEDED":
                print(f"{j['name']}: {harvest(st, by_id, out, j['ids'])} readings")
                j["harvested"] = True
            elif j["state"] in ("BATCH_STATE_FAILED", "BATCH_STATE_CANCELLED", "BATCH_STATE_EXPIRED"):
                print(f"{j['name']}: {j['state']}")
                j["harvested"] = True
        jobs_path.write_text(json.dumps(jobs, indent=1))
        if not [j for j in jobs if not j.get("harvested")] or time.time() >= deadline:
            break
        time.sleep(30)
    left = [j["name"] for j in jobs if not j.get("harvested")]
    print(f"{len(left)} batches still pending" if left else "all harvested")


def main(
    sites: Annotated[Path, typer.Option(help="sites.jsonl with context, crop and zoom per site")],
    out: Annotated[Path, typer.Option(help="Run dir: jobs.json and readings.jsonl")],
    model: Annotated[str | None, typer.Option(help='"models/<name>"; required to submit, no default')] = None,
    chunk: Annotated[int, typer.Option(help="Sites per batch (inline payload stays under 20MB)")] = 12,
    poll_wait: Annotated[int, typer.Option(help="Seconds to keep polling")] = 0,
):
    """Submit the sites not yet read, then optionally poll and harvest."""
    rows = read_rows(sites)
    out.mkdir(parents=True, exist_ok=True)
    if model:
        submit(rows, out, model, chunk)
    if poll_wait:
        poll(rows, out, poll_wait)


app = typer.Typer()
app.command()(main)

if __name__ == "__main__":
    app()
