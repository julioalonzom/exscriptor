"""What the platform says about a work's staged batches. Read-only.

``<work>/staged.jsonl`` records what was submitted; only the platform knows
what an editor approved, rejected or left pending. Draw lessons from approved
work only: a rejected batch may have taught a wrong one.

    python3 -m exscriptor.batch_status <work>
    python3 -m exscriptor.batch_status <work> --batch 702 --require approved   # exit 1 unless approved

Prints one JSON object: {"work", "batches": [{batch_id, manifest,
staged_status, status, review_note}], "ok"}.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import List, Optional

import typer
from typing_extensions import Annotated

from exscriptor import https
from exscriptor.credentials import credential
from exscriptor.manifest import API

app = typer.Typer(add_completion=False)


def staged(work: Path) -> list[dict]:
    p = work / "staged.jsonl"
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()] if p.exists() else []


def fetch(api: str, token: str, batch_id: int) -> dict:
    req = urllib.request.Request(f"{api.rstrip('/')}/api/corpus-imports/{batch_id}",
                                 headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
    try:
        with https.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return {"status": f"http-{e.code}"}


def report(work: Path, batches: list[int] | None, require: str | None, fetch=fetch) -> dict:
    rows = [r for r in staged(work) if not batches or r.get("batch_id") in batches]
    if batches:
        rows += [{"batch_id": b} for b in sorted(set(batches) - {r.get("batch_id") for r in rows})]
    if not rows:
        return {"work": str(work), "batches": [], "ok": False, "error": "no staged batch for this work"}
    api = credential("SCHOLA_API_URL", required=False) or API
    token = credential("SCHOLA_IMPORT_TOKEN")
    out = []
    for r in rows:
        live = fetch(api, token, r["batch_id"])
        out.append({"batch_id": r["batch_id"], "manifest": r.get("manifest"), "staged_status": r.get("status"),
                    "status": live.get("status"), "review_note": live.get("review_note")})
    failed = any(str(b["status"]).startswith("http-") for b in out)
    ok = not failed and (all(b["status"] == require for b in out) if require else True)
    return {"work": str(work), "batches": out, "ok": ok}


@app.command()
def main(
    work: Annotated[Path, typer.Argument(help="The work dir")],
    batch: Annotated[Optional[List[int]], typer.Option(help="Only these batch ids (repeatable)")] = None,
    require: Annotated[Optional[str], typer.Option(help="Exit 1 unless every batch has this status")] = None,
) -> None:
    """Print each staged batch's status on the platform."""
    result = report(work, batch, require)
    print(json.dumps(result, ensure_ascii=False))
    raise typer.Exit(0 if result["ok"] else 1)


if __name__ == "__main__":
    app()
