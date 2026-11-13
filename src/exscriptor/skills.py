"""Link exscriptor's skills into an agent's skills folder, and check the links.

    python3 -m exscriptor.skills link ~/.agents/skills [~/.claude/skills ...]
    python3 -m exscriptor.skills check ~/.agents/skills

The skills ship with the code they call, so they come from the checkout this
Python imports exscriptor from (a clone, installed with ``pip install -e``):
one ``git pull`` updates both. ``link`` points ``<dest>/<skill>`` (and
``<dest>/reference``, which the skills cite) at that checkout, replacing a
link that points elsewhere but never a real file or folder. ``check`` exits 1
when a skill is missing, points elsewhere, or a folder in ``<dest>`` carries
an exscriptor skill's name (a stale copy shadows the real one).
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import List

import typer
from typing_extensions import Annotated

app = typer.Typer(add_completion=False)


def source() -> Path:
    skills = Path(__file__).resolve().parents[2] / "skills"
    if not skills.is_dir():
        sys.exit(f"no skills folder at {skills}: install exscriptor from a clone (pip install -e <clone>)")
    return skills


def entries(skills: Path) -> list[Path]:
    """Every skill, plus the reference folder they cite."""
    return sorted(p for p in skills.iterdir() if (p / "SKILL.md").is_file() or p.name == "reference")


def problems(dest: Path, skills: Path) -> list[str]:
    found = []
    for src in entries(skills):
        target = dest / src.name
        if target.is_symlink():
            if target.resolve() != src.resolve():
                found.append(f"{target} -> {target.resolve()}, not {src}")
        elif target.exists():
            found.append(f"{target} is a copy, not a link: it shadows {src}")
        else:
            found.append(f"{target} is missing")
    return found


def link(dest: Path, skills: Path) -> list[str]:
    """Create or repoint every link; returns what could not be linked."""
    dest.mkdir(parents=True, exist_ok=True)
    refused = []
    for src in entries(skills):
        target = dest / src.name
        if target.exists() and not target.is_symlink():
            refused.append(f"{target} is a real folder; move it away, then link again")
            continue
        if target.is_symlink():
            target.unlink()
        target.symlink_to(src)
    return refused


@app.command("link")
def link_cmd(dests: Annotated[List[Path], typer.Argument(help="Skills folders to link into")]) -> None:
    """Link every skill into each folder."""
    skills = source()
    refused = [r for d in dests for r in link(d.expanduser(), skills)]
    for r in refused:
        print(f"REFUSED: {r}")
    print(f"{len(entries(skills))} entries from {skills} linked into {len(dests)} folder(s)")
    raise typer.Exit(1 if refused else 0)


@app.command("check")
def check_cmd(dests: Annotated[List[Path], typer.Argument(help="Skills folders to check")]) -> None:
    """Exit 1 unless every skill in each folder links into this checkout."""
    skills = source()
    found = [p for d in dests for p in problems(d.expanduser(), skills)]
    for p in found:
        print(p)
    print("ok" if not found else f"{len(found)} problem(s)")
    raise typer.Exit(1 if found else 0)


if __name__ == "__main__":
    app()
