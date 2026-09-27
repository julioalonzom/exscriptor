#!/usr/bin/env python3
"""Filter and check the layers of a printed edition that a project does not publish.

Many scholarly editions are LAYERED: they print the author's text alongside
something the author did not write — a commentary on that text, a prior
translation, editorial apparatus, a quoted source in another language. A digitizing
project usually publishes only one layer and must not republish the others.

The layers are marked in the page files with an explicit open/close pair, and the
assembler drops everything between them structurally:

    <<<THOMAS>>>
    ... text the project does not publish ...
    <<<END THOMAS>>>

The marker names are a per-work convention, not a library constant: a commentary
on the Summa, an edition of Aristotle with a translator's facing text, and a
critical edition with apparatus all need this and none of them share a vocabulary.
So the names are parameters. The default follows the two-voice convention used by
`check_markers`.

## The failure this exists to catch

**Absence of a dropped layer is not damage, and presence of one is.** Both look
alike from the outside — a section simply looks wrong — and the two failure modes
are mirror images:

  * a section looks SHORT. The base text is simply not ours to publish, and its
    absence is correct. Reading that as a transcription loss sends an agent to
    "repair" a section that is already right, and the repair publishes the layer
    the project excluded.
  * a section looks LONG, or a quoted authority appears where the commentator
    should be. The layer was never marked, so the assembler never dropped it, and
    one voice is being published as the other.

Neither is visible to a count, a length, or a coverage metric. Only the page
decides which voice a passage belongs to.

The second, sharper failure is `authorial_in_dropped`: **the excluded layer was
marked, but a line that belongs to the PUBLISHED voice was caught inside it.** The
assembler then deletes it silently, and the text loses an editorial judgement
that was on the page all along. This is why a zone boundary is an editorial
decision and not a transcription convenience, and it is the one thing here worth
running a gate over.

## Usage

    ex-layer-zones page.md                    # check and report
    ex-layer-zones page.md --check-only       # report, write nothing
    ex-layer-zones page.md -o filtered.md     # write the published text

    # a different edition's vocabulary
    ex-layer-zones page.md --zone BASE --zone APPARATUS
    ex-layer-zones page.md --zone "Summa:Theologiae" --authorial "Conclusio"

Environment: `DIGITIZE_ZONES` sets the default zone names, comma-separated, in
the same spirit as `check_markers`.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import typer
from typing_extensions import Annotated

# The two-voice convention, and the only sensible default: a commentary prints its
# base text in a marked zone that the assembler drops.
DEFAULT_ZONES = ("THOMAS",)

OPEN = "<<<{name}>>>"
CLOSE = "<<<END {name}>>>"


def _marker_re(name: str) -> re.Pattern:
    return re.compile(r"^\s*<<<(?P<kind>END\s+)?%s>>>\s*$" % re.escape(name),
                      re.IGNORECASE)


def zone_names(zones: tuple[str, ...] | None = None) -> tuple[str, ...]:
    if zones:
        return tuple(z for z in zones if z)
    env = os.environ.get("DIGITIZE_ZONES", "")
    if env:
        return tuple(z.strip() for z in env.split(",") if z.strip())
    return DEFAULT_ZONES


def filter_layers(
    text: str,
    zones: tuple[str, ...] | None = None,
    authorial: tuple[str, ...] = (),
) -> dict:
    """Drop every marked zone. Returns kept text plus everything worth reporting.

    The dropped material is returned rather than discarded silently: it is the
    audit trail, and a large drop is the expected case, not a suspicious one.
    """
    names = zone_names(zones)
    # One pass over the lines, tracking which zone (if any) is open.
    auth_res = [re.compile(a, re.IGNORECASE) for a in authorial if a]
    kept_lines: list[str] = []
    dropped_lines: list[str] = []
    open_name: str | None = None
    unbalanced: list[str] = []
    authorial_in_dropped: list[str] = []

    for line in text.split("\n"):
        matched = None
        for name in names:
            m = _marker_re(name).match(line)
            if m:
                matched = (name, bool(m.group("kind")))
                break
        if matched:
            name, is_close = matched
            if is_close:
                if open_name is None:
                    unbalanced.append(
                        f"{CLOSE.format(name=name)} with no opening marker")
                elif open_name != name:
                    unbalanced.append(
                        f"{CLOSE.format(name=name)} closes {open_name}")
                open_name = None
            else:
                if open_name is not None:
                    unbalanced.append(
                        f"{OPEN.format(name=name)} opened inside {open_name}")
                open_name = name
            dropped_lines.append(line)
            continue
        if open_name is not None:
            dropped_lines.append(line)
            for rx in auth_res:
                if rx.search(line):
                    authorial_in_dropped.append(
                        f"[{open_name}] {line.strip()[:70]}")
                    break
            continue
        kept_lines.append(line)

    if open_name is not None:
        unbalanced.append(f"{OPEN.format(name=open_name)} never closed")

    kept = "\n".join(kept_lines)
    return {
        "kept": kept,
        "dropped": "\n".join(dropped_lines),
        "dropped_nonblank": [l for l in dropped_lines if l.strip()],
        "unbalanced": unbalanced,
        "authorial_in_dropped": authorial_in_dropped,
        "zones": names,
    }


def blocks(text: str) -> list[str]:
    return [b for b in re.split(r"\n\s*\n", text) if b.strip()]


app = typer.Typer(add_completion=False)


@app.command()
def main(
    source: Annotated[Path, typer.Argument(help="page file to check")],
    out: Annotated[Path | None, typer.Option("--out", "-o",
                                            help="write the published text here")] = None,
    check_only: Annotated[bool, typer.Option("--check-only",
                                             help="report only, write nothing")] = False,
    zone: Annotated[list[str] | None, typer.Option("--zone",
                                                    help="zone name; repeatable")] = None,
    authorial: Annotated[list[str] | None, typer.Option(
        "--authorial", help="regex for a line of the PUBLISHED voice; repeatable")] = None,
) -> int:
    text = source.read_text()
    res = filter_layers(text, tuple(zone) if zone else None,
                        tuple(authorial or ()))

    n_names = len(res["zones"])
    print(f"source            : {source}")
    print(f"  lines           : {len(text.splitlines())}")
    print(f"  zone names      : {', '.join(res['zones'])} ({n_names})")
    print(f"published (kept)  : {len(blocks(res['kept']))} blocks "
          f"({len(res['kept'])} chars)")
    print(f"dropped in zones  : {len(res['dropped_nonblank'])} non-blank lines")
    if not res["zones"]:
        print("\nnothing to do: no zone names given and DIGITIZE_ZONES is unset")
        return 0

    ok = True
    if res["authorial_in_dropped"]:
        ok = False
        print("\nFAIL — the PUBLISHED voice is inside a dropped zone and the "
              "assembler will\n  delete it silently. Move the zone boundary:")
        for a in res["authorial_in_dropped"]:
            print(f"    {a}")
    if res["unbalanced"]:
        ok = False
        print("\nFAIL — unbalanced zone markers:")
        for u in res["unbalanced"]:
            print(f"    {u}")
    if ok:
        print("\nzone scoping: OK (markers balanced, no published-voice line "
              "inside a zone)")

    if out and not check_only:
        Path(out).write_text(res["kept"].rstrip() + "\n")
        print(f"\nwrote {out}")
    elif not check_only:
        print("\n(dry run; pass --out to write)")
    # typer's app() discards a return value, so a plain `return 1` would leave
    # the process exiting 0 on failure. A gate that cannot fail a caller is not a
    # gate: raise, so the exit code is real.
    if not ok:
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
