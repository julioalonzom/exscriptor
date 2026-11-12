"""Send a batch's facsimile pages to Schola Thomistica with your agent key.

Each facsimile row names a page render (``filename``, e.g. ``pg-012.jpg``).
This sends every named render once to

    PUT $SCHOLA_API_URL/api/corpus-imports/scans/<sha256 of the file>

with ``SCHOLA_IMPORT_TOKEN``, and writes that hash into each row's ``sha256``.
The server re-encodes the page, screens it, and holds it; approving the batch
publishes it. Nothing is public before then. A page already held is not
processed again, so a rerun is safe. Held pages expire after 30 days: a batch
staged later than that is refused for a missing image; rerun this, then stage.

    python3 -m exscriptor.upload_scans <work>/manifests/<stem>.json            # renders in <work>/pages
    python3 -m exscriptor.upload_scans <manifest> --pages <dir>

Run it on the finished manifest, before preflight (it rewrites the file, and
preflight binds its report to the file's sha256). A rebuild drops the hashes:
run it again after any rebuild.
"""
from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import typer
from typing_extensions import Annotated

from exscriptor import http
from exscriptor.credentials import credential

WORKERS = 4
RETRIES = 3


def facsimile_rows(manifest: dict) -> list[dict]:
    """Every facsimile row of the manifest, ``edit``'s ``set_facsimile`` included."""
    rows = []
    for w in manifest.get("works") or []:
        rows += w.get("facsimile") or []
        for op in w.get("operations") or []:
            if op.get("op") == "set_facsimile":
                rows += op.get("pages") or []
    return rows


def put_scan(api: str, token: str, sha: str, data: bytes) -> dict:
    """PUT one page; retries what a later try can fix (429, 5xx, the network)."""
    req = urllib.request.Request(
        f"{api.rstrip('/')}/api/corpus-imports/scans/{sha}", data=data, method="PUT",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/octet-stream"})
    for attempt in range(RETRIES + 1):
        try:
            with http.urlopen(req, timeout=120) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            if e.code != 429 and e.code < 500 or attempt == RETRIES:
                detail = e.read().decode(errors="replace")
                try:
                    detail = json.loads(detail).get("detail", detail)
                except (ValueError, AttributeError):
                    pass
                raise RuntimeError(f"HTTP {e.code}: {detail}") from None
        except urllib.error.URLError as e:
            if attempt == RETRIES:
                raise RuntimeError(f"network: {e.reason}") from None
        time.sleep(2 ** attempt * 5)
    raise AssertionError("unreachable")


def upload(manifest: dict, pages: Path, send=None) -> tuple[int, int, list[str]]:
    """Send every page the rows name and set each row's ``sha256``.

    Returns (sent, already held, failures); rows change only when all pages went."""
    rows = facsimile_rows(manifest)
    files = {r["filename"] for r in rows}
    missing = sorted(f for f in files if not (pages / f).is_file())
    if missing:
        return 0, 0, [f"{f}: no such file in {pages}" for f in missing]
    hashes = {f: hashlib.sha256((pages / f).read_bytes()).hexdigest() for f in files}
    if send is None:
        api, token = credential("SCHOLA_API_URL"), credential("SCHOLA_IMPORT_TOKEN")
        send = lambda sha, data: put_scan(api, token, sha, data)

    def one(f: str):
        try:
            return f, send(hashes[f], (pages / f).read_bytes()), None
        except RuntimeError as e:
            return f, None, f"{f}: {e}"

    with ThreadPoolExecutor(WORKERS) as pool:
        results = list(pool.map(one, sorted(files)))
    failures = [err for _, _, err in results if err]
    if failures:
        return 0, 0, failures
    held = sum(1 for _, receipt, _ in results if receipt.get("already_staged"))
    for r in rows:
        r["sha256"] = hashes[r["filename"]]
    return len(files) - held, held, []


def main(
    manifest: Annotated[Path, typer.Argument(help="The finished manifest carrying the facsimile")],
    pages: Annotated[Path | None, typer.Option(help="Dir of the page renders (default <work>/pages)")] = None,
):
    """Send the facsimile pages and write their hashes into the manifest."""
    from exscriptor.preflight import default_work_dir
    m = json.loads(manifest.read_text(encoding="utf-8"))
    if not facsimile_rows(m):
        print("no facsimile rows: nothing to send")
        raise typer.Exit(0)
    sent, held, failures = upload(m, pages or default_work_dir(manifest) / "pages")
    for f in failures:
        print("  " + f)
    if failures:
        print(f"{len(failures)} page(s) failed; the manifest is unchanged")
        raise typer.Exit(1)
    manifest.write_text(json.dumps(m, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{sent} page(s) sent, {held} already held -> sha256 written into {manifest}")
    print("next: python3 -m exscriptor.preflight, then submit")


app = typer.Typer(add_completion=False)
app.command()(main)


if __name__ == "__main__":
    app()
