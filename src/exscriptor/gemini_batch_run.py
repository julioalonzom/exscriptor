#!/usr/bin/env python3
"""Submit pages to the native Gemini Batch API in chunks (work-agnostic).

Inline requests (image per page, ~1.2MB each) chunked at 15 pages per batch
(~18MB payload, safely under the 20MB inline limit). Each page = one request
keyed "pg-NNN". Pages whose transcription already exists in the run dir are
skipped, so re-running the script submits only the missing pages.

Measured 2026-08-31 (Bontempi 1676 print, gemini-3.7-flash): the batch
endpoint REJECTS `thinkingConfig` per request ("Request contains an invalid
argument" on every inlined response) while accepting `mediaResolution`.
Pass `--thinking` only when you know the model/endpoint pair supports it in
batch mode; leave it unset for the documented default behaviour.

Usage (the transcription prompt text is supplied by the caller):
  python3 -m exscriptor.gemini_batch_run \
      --pages 12-240 --images /tmp/edition_pages \
      --out runs/edition --jobs runs/edition/gbatch_jobs.json \
      --prompt-file prompt.txt
"""
from __future__ import annotations

import base64, json, os, subprocess, sys, tempfile, time

import typer
from typing_extensions import Annotated
from pathlib import Path

from exscriptor.credentials import credential  # noqa: E402

BASE = "https://generativelanguage.googleapis.com/v1beta"
MODEL = "models/gemini-3.7-flash"


def api_key() -> str:
    return credential("GEMINI_API_KEY")


def call(path: str, payload: dict | None = None, method: str = "GET", timeout: int = 300):
    """One Gemini API call, transported through `curl`.

    urllib and the google-genai SDK hang (or fail TLS) in several of the
    environments this library runs in, while curl works everywhere; the
    key travels in a header, never in argv or the URL.
    """
    url = f"{BASE}/{path}"
    body_path = None
    cmd = ["curl", "-sS", "--max-time", str(timeout),
           "-X", method, url, "-H", "@-", "-w", "\n%{http_code}"]
    if payload is not None:
        body_path = tempfile.mktemp(suffix=".json")
        with open(body_path, "wb") as fh:
            fh.write(json.dumps(payload).encode())
        cmd += ["-d", f"@{body_path}", "-H", "Content-Type: application/json"]
    proc = subprocess.run(cmd, input=f"x-goog-api-key: {api_key()}".encode(),
                          capture_output=True)
    if body_path:
        os.unlink(body_path)
    out = proc.stdout.decode(errors="replace")
    head, _, code = out.rpartition("\n")
    if proc.returncode != 0 or code.strip() != "200":
        msg = f"HTTP {code.strip() or '?'} {head[:300]}"
        print(msg)
        raise RuntimeError(msg)
    return json.loads(head)


RESOLUTIONS = {
    "default": None,
    "low": "MEDIA_RESOLUTION_LOW",
    "medium": "MEDIA_RESOLUTION_MEDIUM",
    "high": "MEDIA_RESOLUTION_HIGH",
}


def make_config(resolution: str = "default", thinking: str | None = None) -> dict:
    """generationConfig for a page request (work-agnostic knobs).

    `mediaResolution` is the quality lever on this API; `thinkingLevel` is a
    cost trap (minimal is the measured default; full thinking buys ~0.03
    accuracy points for 11x the price). Both go in generationConfig. Passing
    "default" / None keeps today's behaviour unchanged.
    """
    config: dict = {"maxOutputTokens": 24000, "temperature": 0}
    if RESOLUTIONS[resolution]:
        config["mediaResolution"] = RESOLUTIONS[resolution]
    if thinking:
        config["thinkingConfig"] = {"thinkingLevel": thinking}
    return config


def make_request(num: int, images: Path, prompt: str,
                 resolution: str = "default", thinking: str | None = None,
                 key: bool = False) -> dict:
    jpeg = (images / f"pg-{num:03d}.jpg").read_bytes()
    req = {
        "contents": [{
            "role": "user",
            "parts": [
                {"text": prompt},
                {"inline_data": {"mime_type": "image/jpeg",
                                 "data": base64.b64encode(jpeg).decode()}},
            ],
        }],
        "generationConfig": make_config(resolution, thinking),
    }
    out = {"request": req}
    if key:
        out["key"] = f"pg-{num:03d}"
    return out


def submit(out: Path, images: Path, pages: list[int], chunk: int,
           jobs_path: Path, prompt: str, display_prefix: str = "digitize",
           resolution: str = "default", thinking: str | None = None):
    jobs = json.loads(jobs_path.read_text()) if jobs_path.is_file() else []
    done_keys = {j["first_page"] + i for j in jobs for i in range(len(j["pages"]))}
    todo = [n for n in pages if n not in done_keys]
    print(f"{len(todo)} pages to submit in {(len(todo)+chunk-1)//chunk} batches")
    for i in range(0, len(todo), chunk):
        grp = todo[i:i + chunk]
        reqs = [make_request(n, images, prompt, resolution, thinking) for n in grp]
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
    by_key = {it.get("key"): it for it in items if it.get("key")}
    got = 0
    usage_log = out / "usage.jsonl"
    for i, page in enumerate(job["pages"]):
        item = by_key.get(f"pg-{page:03d}") or (items[i] if i < len(items) else {})
        r = item.get("response") or {}
        err = item.get("error")
        if err or not r:
            print(f"  pg-{page}: ERROR {json.dumps(err or item)[:200]}")
            continue
        um = r.get("usageMetadata") or {}
        usage_log.open("a").write(json.dumps({
            "page": page,
            "prompt_tokens": um.get("promptTokenCount"),
            "candidates_tokens": um.get("candidatesTokenCount"),
            "total_tokens": um.get("totalTokenCount"),
            "thoughts_tokens": um.get("thoughtsTokenCount"),
            "model": r.get("modelVersion"),
        }) + "\n")
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
    resolution: Annotated[str, typer.Option(help="mediaResolution: default|low|medium|high")] = "default",
    thinking: Annotated[str | None, typer.Option(help="thinkingLevel: minimal|low|high (or omit)")] = None,
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
        submit(out, images, todo, chunk, jobs, prompt, display_prefix, resolution, thinking)
    if poll_wait:
        poll(jobs, out, poll_wait)


app = typer.Typer()
app.command()(main)


if __name__ == "__main__":
    app()
