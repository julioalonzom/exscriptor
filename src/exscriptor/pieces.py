#!/usr/bin/env python3
"""Join a page written in pieces back into one page file.

A reader may have to write a page in short pieces: a provider's output filter
can stop a model reproducing a long stretch of a famous text verbatim, even a
public-domain one, and a page written in one call then never lands. Pieces
are ``pg-NNN.p01.md``, ``pg-NNN.p02.md``, … in reading order; a piece whose
last line is ``⟨CONT⟩`` continues its paragraph into the next piece (joined
with one space, or with nothing after a line-end hyphen; emphasis closed at
the cut and reopened after it is merged into one span); otherwise pieces are
separate paragraphs. ``pg-NNN.done`` marks a finished page: pages without it
are left alone, as are pages whose output already exists.

Usage:

    python3 -m exscriptor.pieces runs/passC/pieces runs/passC
"""
from __future__ import annotations

import re
from pathlib import Path

import typer
from typing_extensions import Annotated

CONT = "⟨CONT⟩"
PIECE = re.compile(r"^(pg-\d+)\.p(\d+)\.md$")


def join(pieces: list[str]) -> str:
    out = ""
    cont = False
    for text in pieces:
        lines = text.strip("\n").splitlines()
        nxt_cont = bool(lines) and lines[-1].strip() == CONT
        if nxt_cont:
            lines = lines[:-1]
        body = "\n".join(lines).strip("\n")
        if not out:
            out = body
        elif cont:
            head = body.lstrip()
            k = next((k for k in (2, 1) if out.rstrip().endswith("*" * k) and head.startswith("*" * k)
                      and not head.startswith("*" * (k + 1))), 0)
            if k:  # emphasis closed at the cut and reopened after it: one span
                out = out.rstrip()[:-k]
                body = head[k:]
            if out.endswith("-") and not out.endswith(" -"):
                out = out[:-1] + body.lstrip()
            else:
                out = out.rstrip() + " " + body.lstrip()
        else:
            out = out.rstrip("\n") + "\n\n" + body
        cont = nxt_cont
    return re.sub(r"\n{3,}", "\n\n", out).strip() + "\n"


def main(
    pieces_dir: Annotated[Path, typer.Argument(help="Directory of pg-NNN.pKK.md pieces")],
    out_dir: Annotated[Path, typer.Argument(help="Where joined pg-NNN.md pages go")],
) -> None:
    pages: dict[str, list[tuple[int, Path]]] = {}
    for p in pieces_dir.iterdir():
        m = PIECE.match(p.name)
        if m:
            pages.setdefault(m.group(1), []).append((int(m.group(2)), p))
    done = 0
    for stem, items in sorted(pages.items()):
        target = out_dir / f"{stem}.md"
        if not (pieces_dir / f"{stem}.done").exists():
            typer.echo(f"{stem}: not done, left alone")
            continue
        if target.exists():
            typer.echo(f"{stem}: {target} exists, left alone")
            continue
        nums = sorted(n for n, _ in items)
        if nums != list(range(1, len(nums) + 1)):
            typer.echo(f"{stem}: pieces {nums} are not 1..N, left alone")
            continue
        target.write_text(join([p.read_text(encoding="utf-8") for _, p in sorted(items)]), encoding="utf-8")
        done += 1
    typer.echo(f"joined {done} page(s) into {out_dir}")


if __name__ == "__main__":
    typer.run(main)
