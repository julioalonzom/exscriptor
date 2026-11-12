"""Save a live work as the snapshot ``append_texts`` builds from.

``GET /api/works/{slug}/outline`` is the whole tree without text bodies; this
adds every section's current texts from ``/sections/texts``, 40 sections a
request (the API's limit), so ``sections[...]["texts"][lang]["content"]`` is
what the reader shows today.

    python3 -m exscriptor.snapshot <slug> --out <work>/live.json
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Annotated

import typer

from exscriptor import https
from exscriptor.credentials import credential
from exscriptor.manifest import API

PER_REQUEST = 40


def get(api: str, path: str):
    req = urllib.request.Request(api.rstrip("/") + path, headers={"Accept": "application/json"})
    with https.urlopen(req, timeout=90) as r:
        return json.loads(r.read().decode("utf-8"))


def nodes(sections: list[dict]):
    for s in sections:
        yield s
        yield from nodes(s.get("children") or [])


def snapshot(slug: str, api: str) -> dict:
    base = f"/api/works/{urllib.parse.quote(slug)}"
    work = get(api, base + "/outline")
    by_id = {s["id"]: s for s in nodes(work.get("sections") or [])}
    for s in by_id.values():
        s["texts"] = {}
    ids = list(by_id)
    for i in range(0, len(ids), PER_REQUEST):
        query = urllib.parse.urlencode([("section_ids", x) for x in ids[i:i + PER_REQUEST]])
        for item in get(api, f"{base}/sections/texts?{query}")["sections"]:
            by_id[item["id"]]["texts"] = item["texts"]
    return work


def main(slug: Annotated[str, typer.Argument(help="The live work's slug")],
         out: Annotated[Path, typer.Option(help="Where to save it, in the work dir")]) -> None:
    """Save the live work, with every section's current texts."""
    work = snapshot(slug, credential("SCHOLA_API_URL", required=False) or API)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(work, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    all_ = list(nodes(work.get("sections") or []))
    print(f"{out}: {len(all_)} sections, {sum(1 for s in all_ if s['texts'])} with text")


if __name__ == "__main__":
    typer.run(main)
