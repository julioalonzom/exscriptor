#!/usr/bin/env python3
"""Print the FULL batch JSON (errors included)."""
import json
import urllib.request

import typer
from typing_extensions import Annotated

from exscriptor.credentials import credential


def main(
    batch_id: Annotated[str, typer.Argument(help="Batch id")],
):
    """Print the FULL batch JSON (errors included)."""
    key = credential("OPENROUTER_API_KEY")
    req = urllib.request.Request(
        f"https://openrouter.ai/api/v1/batches/{batch_id}",
        headers={"Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(req) as r:
        print(json.dumps(json.load(r), indent=2))


app = typer.Typer()
app.command()(main)


if __name__ == "__main__":
    app()
