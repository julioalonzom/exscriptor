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
For gemini-3.8-flash, explicitly use a supported thinking level: `low` is
the lowest. A legacy zero budget can be accepted while still generating
thinking tokens; do not treat it as disabled thinking for this model.

A page is written only when the model finished it (finishReason STOP). A page
cut by the token cap or withheld (RECITATION, SAFETY) goes to `<out>/rejected/`
with its reason, and the next run submits it again: resubmission follows the
page files, not the job list.

Usage (the transcription prompt text is supplied by the caller):
  python3 -m exscriptor.gemini_batch_run \
      --pages 12-240 --images /tmp/edition_pages \
      --out runs/edition --jobs runs/edition/gbatch_jobs.json \
      --prompt-file prompt.txt --model models/<name>
"""
from __future__ import annotations

import base64, json, os, subprocess, sys, tempfile, time

import typer
from typing_extensions import Annotated
from pathlib import Path

from exscriptor.credentials import credential  # noqa: E402

# GEMINI_BASE points a worker at a protected local proxy that holds the key and the cap.
BASE = os.environ.get("GEMINI_BASE", "https://generativelanguage.googleapis.com/v1beta")
# No default model: a paid route runs only on a model named explicitly on the
# command line of a job the owner authorized.


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


def make_config(resolution: str = "default", thinking: str | None = None, *, model: str | None = None) -> dict:
    """generationConfig for a page request (work-agnostic knobs).

    Models support different thinking levels, and thinking tokens cost money.
    For models without a specific guard, None keeps the provider default.
    """
    if model and model.removeprefix("models/") == "gemini-3.8-flash" and thinking not in ("low", "medium", "high"):
        raise ValueError("Gemini 3.8 Flash requires explicit thinking low, medium, or high; off/minimal are unsupported")
    config: dict = {"maxOutputTokens": 24000, "temperature": 0}
    if RESOLUTIONS[resolution]:
        config["mediaResolution"] = RESOLUTIONS[resolution]
    if thinking == "off":  # legacy models that actually support a zero budget
        config["thinkingConfig"] = {"thinkingBudget": 0}
    elif thinking:
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
        out["metadata"] = {"key": f"pg-{num:03d}"}
    return out


def submit(out: Path, images: Path, pages: list[int], chunk: int,
           jobs_path: Path, prompt: str, display_prefix: str = "digitize",
           resolution: str = "default", thinking: str | None = None,
           *, model: str):
    make_config(resolution, thinking, model=model)  # refuse unsupported settings before a paid request
    jobs = json.loads(jobs_path.read_text()) if jobs_path.is_file() else []
    # A page goes out unless its page file exists or a batch holding it is still running:
    # a page rejected at harvest (cut, blocked) has no file, so a re-run resubmits it.
    in_flight = {n for j in jobs if j.get("state") not in TERMINAL for n in j["pages"]}
    todo = [n for n in pages if n not in in_flight and not (out / f"pg-{n:03d}.md").exists()]
    print(f"{len(todo)} pages to submit in {(len(todo)+chunk-1)//chunk} batches")
    for i in range(0, len(todo), chunk):
        grp = todo[i:i + chunk]
        reqs = [make_request(n, images, prompt, resolution, thinking, key=True) for n in grp]
        payload = {"batch": {"display_name": f"{display_prefix}-p{grp[0]}-{grp[-1]}",
                             "input_config": {"requests": {"requests": reqs}}}}
        resp = call(f"{model}:batchGenerateContent", payload, method="POST")
        name = resp["name"]
        rec = {"name": name, "model": model, "pages": grp, "first_page": grp[0],
               "state": resp["metadata"].get("state", "?")}
        jobs.append(rec)
        jobs_path.write_text(json.dumps(jobs, indent=1))
        print(f"submitted {grp[0]}-{grp[-1]} -> {name}")
        time.sleep(2)  # gentle on the API
    print(f"all submitted; job list at {jobs_path}")


TERMINAL = ("BATCH_STATE_SUCCEEDED", "BATCH_STATE_FAILED",
            "BATCH_STATE_CANCELLED", "BATCH_STATE_EXPIRED")


def poll(jobs_path: Path, out: Path, wait_s: int):
    jobs = json.loads(jobs_path.read_text())
    deadline = time.time() + wait_s
    terminal = TERMINAL
    pending = [j for j in jobs if j.get("state") not in TERMINAL]
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
    def key_of(it):
        return (it.get("metadata") or {}).get("key") or it.get("key")
    by_key = {key_of(it): it for it in items if key_of(it)}
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
        cand = (r.get("candidates") or [{}])[0]
        finish = cand.get("finishReason")
        usage_log.open("a").write(json.dumps({
            "page": page, "finish": finish,
            "prompt_tokens": um.get("promptTokenCount"),
            "candidates_tokens": um.get("candidatesTokenCount"),
            "total_tokens": um.get("totalTokenCount"),
            "thoughts_tokens": um.get("thoughtsTokenCount"),
            "model": r.get("modelVersion"),
        }) + "\n")
        parts = ((cand.get("content") or {}).get("parts")) or []
        text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        if finish != "STOP":
            # MAX_TOKENS is a page cut short, RECITATION / SAFETY a page withheld: never a page file.
            print(f"  pg-{page}: REJECTED, finishReason {finish}")
            (out / "rejected").mkdir(exist_ok=True)
            (out / "rejected" / f"pg-{page:03d}.md").write_text(
                f"<!-- rejected: finishReason {finish} -->\n{text}\n", encoding="utf-8")
            continue
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
    thinking: Annotated[str | None, typer.Option(help="Model-supported thinking level; required for Gemini 3.8 Flash")] = None,
    poll_wait: Annotated[int, typer.Option(help="Seconds to keep polling after submitting")] = 0,
    model: Annotated[str | None, typer.Option(help='Model resource name, e.g. "models/<name>". Required with --pages; there is no default')] = None,
):
    """Submit pages to the native Gemini Batch API, then optionally poll."""
    if pages and not model:
        raise typer.BadParameter("--model is required when submitting pages (no default model)",
                                 param_hint="--model")
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
        submit(out, images, todo, chunk, jobs, prompt, display_prefix, resolution, thinking,
               model=model)
    if poll_wait:
        poll(jobs, out, poll_wait)


app = typer.Typer()
app.command()(main)


if __name__ == "__main__":
    app()
