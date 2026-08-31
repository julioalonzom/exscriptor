#!/usr/bin/env python3
"""Submit pages to the native Gemini Batch API in chunks (work-agnostic).

Inline requests (image per page, ~1.2MB each) chunked at 15 pages per batch
(~18MB payload, safely under the 20MB inline limit). Each page = one request
keyed "pg-NNN". Pages whose transcription already exists in the run dir are
skipped, so re-running the script submits only the missing pages.

Usage (the transcription prompt text is supplied by the caller):
  python3 -m exscriptor.gemini_batch_run \
      --pages 12-240 --images /tmp/edition_pages \
      --out runs/edition --jobs runs/edition/gbatch_jobs.json \
      --prompt-file prompt.txt
"""
from __future__ import annotations

import base64, json, sys, time, urllib.request, urllib.error

import typer
from typing_extensions import Annotated
from pathlib import Path

from exscriptor.credentials import credential  # noqa: E402

BASE = "https://generativelanguage.googleapis.com/v1beta"
MODEL = "models/gemini-3.7-flash"


def api_key() -> str:
    return credential("GEMINI_API_KEY")


def call(path: str, payload: dict | None = None, method: str = "GET"):
    hdr = {"x-goog-api-key": api_key()}
    data = None
    if payload is not None:
        hdr["Content-Type"] = "application/json"
        data = json.dumps(payload).encode()
    req = urllib.request.Request(f"{BASE}/{path}", data=data, headers=hdr, method=method)
    try:
        return json.loads(urllib.request.urlopen(req, timeout=300).read())
    except urllib.error.HTTPError as e:
        print("HTTP", e.code, e.read()[:400])
        raise


def make_request(num: int, images: Path, prompt: str) -> dict:
    jpeg = (images / f"pg-{num:03d}.jpg").read_bytes()
    return {
        "request": {
            "contents": [{
                "role": "user",
                "parts": [
                    {"text": PAGE_PROMPT},
                    {"inline_data": {"mime_type": "image/jpeg",
                                     "data": base64.b64encode(jpeg).decode()}},
                ],
            }],
            "generationConfig": {"maxOutputTokens": 24000, "temperature": 0},
        }
    }


def submit(out: Path, images: Path, pages: list[int], chunk: int,
           jobs_path: Path, prompt: str, display_prefix: str = "digitize"):
    jobs = json.loads(jobs_path.read_text()) if jobs_path.is_file() else []
    done_keys = {j["first_page"] + i for j in jobs for i in range(len(j["pages"]))}
    todo = [n for n in pages if n not in done_keys]
    print(f"{len(todo)} pages to submit in {(len(todo)+chunk-1)//chunk} batches")
    for i in range(0, len(todo), chunk):
        grp = todo[i:i + chunk]
        reqs = [make_request(n, images, prompt) for n in grp]
        payload = {"batch": {"display_name": f"{display_prefix}-p{grp[0]}-{grp[-1]}",
                             "input_config": {"requests": {"requests": reqs}}}}
        resp = call(f"{MODEL}:batchGenerateContent", payload, method="POST")
        name = resp["name"]
        rec = {"name": name, "pages": grp, "first_page": grp[0],
               "state": resp["metadata"].get("state", "?")}
        jobs.append(rec)
        jobs_path.write_text(json.dumps(jobs, indent=1))
        print(f"submitted {grp[0]}-{grp[-1]} -> {name}")
        time.sleep(2)  # gentle on the API
    print(f"all submitted; job list at {jobs_path}")


def poll(jobs_path: Path, out: Path, wait_s: int):
    jobs = json.loads(jobs_path.read_text())
    deadline = time.time() + wait_s
    terminal = ("BATCH_STATE_SUCCEEDED", "BATCH_STATE_FAILED",
                "BATCH_STATE_CANCELLED", "BATCH_STATE_EXPIRED")
    pending = list(jobs)
    while pending and time.time() < deadline:
        still = []
        for j in pending:
            st = call(j["name"])
            state = st["metadata"].get("state", "?")
            if state != j.get("state"):
                print(f"{j['name']} ({j['pages'][0]}-{j['pages'][-1]}): {state}")
                j["state"] = state
            if state in terminal:
                harvest(j, st, out)
                jobs_path.write_text(json.dumps(jobs, indent=1))
            else:
                still.append(j)
        pending = still
        if pending and time.time() < deadline:
            time.sleep(30)
    if pending:
        print(f"{len(pending)} batches still pending after wait")


def harvest(job: dict, st: dict, out: Path):
    out.mkdir(parents=True, exist_ok=True)
    inlined = (st.get("response") or {}).get("inlinedResponses") or {}
    items = inlined.get("inlinedResponses") or []
    got = 0
    for i, item in enumerate(items):
        page = job["pages"][i] if i < len(job["pages"]) else None
        r = item.get("response") or {}
        err = item.get("error")
        if err or not r:
            print(f"  pg-{page}: ERROR {json.dumps(err or item)[:200]}")
            continue
        cand = (r.get("candidates") or [{}])[0]
        parts = ((cand.get("content") or {}).get("parts")) or []
        text = "".join(p.get("text", "") for p in parts)
        target = out / f"pg-{page:03d}.md"
        if not target.exists() and text.strip():
            target.write_text(text + "\n", encoding="utf-8")
            got += 1
    print(f"  harvested {got} pages from {job['name']}")


def main(
    images: Annotated[Path, typer.Option(help="Directory of page images (pg-NNN.jpg)")],
    out: Annotated[Path, typer.Option(help="Output dir for per-page markdown")],
    jobs: Annotated[Path, typer.Option(help="Resumable job-list JSON")],
    prompt_file: Annotated[Path, typer.Option(help="File containing the transcription prompt text")],
    pages: Annotated[str | None, typer.Option(help='Pages to submit, e.g. "1-50,77" (omit to only poll)')] = None,
    chunk: Annotated[int, typer.Option(help="Pages per batch")] = 15,
    display_prefix: Annotated[str, typer.Option] = "digitize",
    poll_wait: Annotated[int, typer.Option(help="Seconds to keep polling after submitting")] = 0,
):
    """Submit pages to the native Gemini Batch API, then optionally poll."""
    jobs.parent.mkdir(parents=True, exist_ok=True)
    prompt = prompt_file.read_text()

    if pages:
        todo = []
        for part in pages.split(","):
            if "-" in part:
                lo, hi = part.split("-")
                todo.extend(range(int(lo), int(hi) + 1))
            else:
                todo.append(int(part))
        submit(out, images, todo, chunk, jobs, prompt, display_prefix)
    if poll_wait:
        poll(jobs, out, poll_wait)


app = typer.Typer()
app.command()(main)


if __name__ == "__main__":
    app()
