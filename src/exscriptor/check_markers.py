#!/usr/bin/env python3
"""Marker-balance screen for zoned pages: [*N] keys vs marginalia lines,
[N] apparatus keys vs apparatus lines, per page.

Zone names default to the two-voice (author/commentator) convention; override
with DIGITIZE_ZONES="A,B" (comma-separated) for other editions.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import typer
from typing_extensions import Annotated

KEY = re.compile(r"\[\*(\d+)\]")
APP_KEY = re.compile(r"\[\*?(\d+)\]")  # text-side apparatus key (numeric, may be bare)
NOTE = re.compile(r"^\[?\*(\d+)\]?[ \t]+", re.M)
APP_NOTE = re.compile(r"^(\d+)[\])]?", re.M)


def check_page(text: str, name: str) -> list[str]:
    issues = []
    zones = {}
    cur = None
    for line in text.splitlines():
        if line.startswith("<<<"):
            cur = line.strip("<>")
            zones.setdefault(cur, [])
        elif cur is not None:
            zones[cur].append(line)
    # per-zone balance: each zone's keys against ITS OWN marginalia
    zone_names = [z.strip() for z in os.environ.get("DIGITIZE_ZONES", "AUTHOR,COMMENTATOR").split(",")]
    for zname in zone_names:
        body = " ".join(zones.get(zname, []))
        marg = "\n".join(zones.get(f"{zname}-MARGINALIA", []))
        star_keys = {k for k in KEY.findall(body)}
        star_notes = {k for k in NOTE.findall(marg)}
        for k in sorted(star_keys - star_notes):
            issues.append(f"{name}: {zname} [*{k}] has no marginalia line")
        for k in sorted(star_notes - star_keys):
            issues.append(f"{name}: {zname} marginalia *{k} has no text key")
    app = " ".join(zones.get(f"{zone_names[0]}-APPARATUS", []))
    app_notes = [m.group(1) for m in APP_NOTE.finditer(app)]
    if app and len(app_notes) == 0:
        issues.append(f"{name}: apparatus present but no numbered notes parsed")
    return issues


def main(
    pages: Annotated[str, typer.Option(help='Pages to check, e.g. "1-50,77"')],
    runs: Annotated[list[Path], typer.Argument(help="Run dirs containing pg-NNN.md files")],
):
    """Check zone-marker / marginalia balance on transcribed pages."""
    nums = []
    for part in pages.split(","):
        if "-" in part:
            lo, hi = part.split("-")
            nums.extend(range(int(lo), int(hi) + 1))
        else:
            nums.append(int(part))
    all_issues = []
    for num in nums:
        for run in runs:
            f = run / f"pg-{num:03d}.md"
            if f.is_file():
                all_issues.extend(check_page(f.read_text(), f.parent.name + "/" + f.stem))
    if all_issues:
        print(f"{len(all_issues)} marker issues:")
        for i in all_issues[:60]:
            print("  ", i)
        raise typer.Exit(1)
    print("marker screen clean")


app = typer.Typer()
app.command()(main)


if __name__ == "__main__":
    app()
