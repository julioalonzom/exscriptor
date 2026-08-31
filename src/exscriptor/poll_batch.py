#!/usr/bin/env python3
"""Poll a batch by id; print status until done or the wait elapses."""
import json
import time
import urllib.request

import typer
from typing_extensions import Annotated

from exscriptor.credentials import credential


def main(
    batch_id: Annotated[str, typer.Argument(help="Batch id")],
    wait_s: Annotated[int, typer.Argument(help="Seconds to keep polling")] = 0,
):
    """Poll batch status; exit when done or the wait elapses."""
    key = credential("OPENROUTER_API_KEY")
    deadline = time.time() + wait_s
    while True:
        req = urllib.request.Request(
            f"https://openrouter.ai/api/v1/batches/{batch_id}",
            headers={"Authorization": f"Bearer {key}"})
        with urllib.request.urlopen(req) as r:
            d = json.load(r)
        data = d.get("data", d)
        print(data.get("status"), "| ended?:", data.get("ended_at"))
        if data.get("status") in ("completed", "failed", "expired", "cancelled"):
            break
        if time.time() >= deadline:
            break
        time.sleep(20)


app = typer.Typer()
app.command()(main)


if __name__ == "__main__":
    app()
