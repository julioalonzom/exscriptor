"""Stage a manifest as a pending batch, with your corpus-import key.

    python3 -m exscriptor.submit <work>/manifests/<stem>.json [--supersedes-batch-id N]

Refuses, before anything is sent, a manifest without a passing preflight
report bound to its exact bytes (``exscriptor.preflight``), a source of ours
under the wrong licence (``exscriptor.licence``), and a declared author the
library already holds (when the library can be read; otherwise it warns
and goes on). The server then applies the batch inside a rolled-back
transaction, so every error approval would raise comes back now.

Prints the batch (id, status, validation report) as JSON and appends it to
``<work>/staged.jsonl``, which ``exscriptor.status`` and
``exscriptor.batch_status`` read. Exit 2 when the batch was staged with a
warning: a warning is a defect, so stage a revision before reporting it done.

``SCHOLA_IMPORT_TOKEN`` and ``SCHOLA_API_URL`` come from the environment or
the ``.env`` file ``exscriptor.credentials`` reads. The key is never printed.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

import typer
from typing_extensions import Annotated

from exscriptor import https, licence, preflight
from exscriptor.credentials import credential
from exscriptor.manifest import API, existing_authors

app = typer.Typer(add_completion=False)


def summarize(manifest: dict) -> dict:
    works = manifest.get("works") or []
    sections = [s for w in works for s in w.get("sections") or []]
    texts = [t for s in sections for t in s.get("texts") or []]
    return {"batch_slug": manifest.get("batch_slug"), "title": manifest.get("title"),
            "source_count": len(manifest.get("sources") or []), "work_count": len(works),
            "section_count": len(sections), "text_count": len(texts),
            "languages": sorted({t["language"] for t in texts if isinstance(t.get("language"), str)})}


def post(api: str, token: str, manifest: dict, timeout: float,
         supersedes_batch_id: int | None = None) -> dict:
    body = {"manifest": manifest}
    if supersedes_batch_id is not None:
        # workflow metadata: never part of the manifest or its content hash
        body["supersedes_batch_id"] = supersedes_batch_id
    req = urllib.request.Request(
        f"{api.rstrip('/')}/api/corpus-imports", data=json.dumps(body).encode("utf-8"), method="POST",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json",
                 "Accept": "application/json"})
    try:
        with https.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        sys.exit(f"Submission failed with HTTP {e.code}: {e.read().decode('utf-8', 'replace')}")
    except OSError as e:  # URLError, a timeout, a reset: the server may still have staged it
        sys.exit(f"Submission of {manifest.get('batch_slug')} got no answer ({e}). It may be staged: "
                 f"send the same file again, which the platform treats as a retry, not a second batch.")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        sys.exit(f"API returned non-JSON: {raw[:500]}")
    if not isinstance(data, dict):
        sys.exit(f"API returned an unexpected response: {raw[:500]}")
    return data


def record_staged(manifest_path: Path, batch: dict) -> None:
    line = {"batch_id": batch.get("id"), "status": batch.get("status"), "manifest": manifest_path.name,
            "sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
            "supersedes_batch_id": batch.get("supersedes_batch_id"),
            "at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")}
    with (preflight.default_work_dir(manifest_path) / "staged.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(line) + "\n")


def refusals(manifest_path: Path, manifest: dict, api: str) -> list[str]:
    """Everything that stops a batch before it is sent."""
    if refusal := preflight.verify(manifest_path):
        return [refusal]
    found = licence.manifest_problems(manifest)
    try:
        found += existing_authors(manifest.get("authors") or [], api)
    except OSError as e:
        # the server merges a known author by name with a warning, which exits 2 below
        print(f"warning: could not check the declared authors against the library ({e})", file=sys.stderr)
    return found


@app.command()
def main(
    manifest: Annotated[Path, typer.Argument(help="The manifest preflight passed")],
    supersedes_batch_id: Annotated[Optional[int], typer.Option(
        help="The pending batch this one corrects (same works, same owner, still the tip)")] = None,
    timeout: Annotated[float, typer.Option(help="Seconds to wait for the staging report")] = 120,
) -> None:
    """Stage the manifest as a pending batch and record it in staged.jsonl."""
    token = credential("SCHOLA_IMPORT_TOKEN")
    if not token.startswith("stci_"):
        sys.exit("SCHOLA_IMPORT_TOKEN should start with stci_")
    api = credential("SCHOLA_API_URL", required=False) or API
    path = manifest.resolve()
    try:
        m = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        sys.exit(f"Invalid JSON in {path}: {e}")
    if found := refusals(path, m, api):
        sys.exit("REFUSED:\n  " + "\n  ".join(found))
    resp = post(api, token, m, timeout, supersedes_batch_id)
    batch = {k: resp.get(k) for k in ("id", "status", "batch_slug", "title", "content_hash",
                                      "validation_report", "supersedes_batch_id",
                                      "superseded_by_batch_id", "is_current_revision")}
    record_staged(path, batch)
    json.dump({"submitted": summarize(m), "batch": batch}, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    warnings = (resp.get("validation_report") or {}).get("warnings") or []
    for w in warnings:
        print(f"WARNING (fix with a revision): {w}", file=sys.stderr)
    raise typer.Exit(2 if warnings else 0)


if __name__ == "__main__":
    app()
