#!/usr/bin/env python3
"""The work-dir contract as a checkable policy: may this tool call run?

A rule an agent only *reads* is a rule a weaker model breaks. "Never edit
``edition/`` by hand" lived in prose, and the next ``expand`` silently reverted
every hand edit; "never call a paid API without authorization" lived in prose,
and a key in an env file looked like permission. This module turns those rules
into a decision a harness can enforce before the call runs:

    check(call, policy) -> Verdict(allow, reason, rule)

A *call* is what an agent harness is about to execute: a file write/edit
(``path``), a file read (``path``), or a shell command (``command``). The
built-in rules are the pipeline's own contract and need no configuration:

* **derived** -- files that exscriptor builds (``edition/``, ``assembled/``,
  ``manifests/``, ``expansions.tsv``, ``pending.tsv``, ``long-s.tsv``,
  ``ASSEMBLY.json``, ``*.preflight.json``, ``staged.jsonl``) are never written
  by hand inside a work dir (a directory holding ``work.json``). The commands
  that legitimately build them (``exscriptor.expand``/``assemble``/
  ``preflight``, plus any ``producers`` in the policy) are allowed.

Everything else comes from a policy file (JSON), because it names the
consumer's own paths and services:

    {
      "forbidden_roots": ["~/code/platform"],        # no writes, ever
      "secret_files": [".env", "backend/.env"],      # never read or printed
      "producers": ["build_manifest.py"],            # may write derived files
      "paid_commands": ["gemini_batch_run", "openai"],  # need a grant
      "territory": ["works/x/transcription/pg-01[0-9].md"]  # optional
    }

``territory`` (or ``--territory`` on the command line) confines writes to the
given globs: a subagent reading pages 10-19 may write only those page files.
A paid command runs only when the caller passes ``--grant paid``; granting is
the harness's job (a human-only command), never the model's.

Shell commands are screened heuristically (redirections, ``tee``,
``sed -i``, ``cp``/``mv`` targets, ``cat``/``source`` of secrets). The
screen is a guard rail against accidents and drift, not a sandbox.

Usage:

    python3 -m exscriptor.guard check --tool write --path works/x/edition/pg-001.md
    python3 -m exscriptor.guard check --tool bash --command "cat .env" --policy policy.json
    python3 -m exscriptor.guard claude-hook --policy policy.json   # Claude Code PreToolUse hook
"""
from __future__ import annotations

import fnmatch
import json
import os
import re
import shlex
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

import typer
from typing_extensions import Annotated

DERIVED_DIRS = ("edition", "assembled", "manifests")
DERIVED_FILES = ("expansions.tsv", "pending.tsv", "long-s.tsv", "ASSEMBLY.json", "staged.jsonl")
DERIVED_SUFFIXES = (".preflight.json",)
BUILTIN_PRODUCERS = (
    "exscriptor.expand", "exscriptor.assemble", "exscriptor.preflight",
    "ex-expand", "ex-assemble", "ex-preflight",
)

WRITE_TOOLS = {"write", "edit", "multiedit", "notebookedit"}
READ_TOOLS = {"read", "grep", "find", "ls", "glob"}
SHELL_TOOLS = {"bash", "shell", "powershell"}


@dataclass
class Policy:
    forbidden_roots: list[str] = field(default_factory=list)
    secret_files: list[str] = field(default_factory=list)
    producers: list[str] = field(default_factory=list)
    paid_commands: list[str] = field(default_factory=list)
    territory: list[str] = field(default_factory=list)

    @classmethod
    def load(cls, path: Path | None) -> "Policy":
        if path is None or not Path(path).exists():
            return cls()
        data = json.loads(Path(path).read_text())
        known = {k: data[k] for k in cls.__dataclass_fields__ if k in data}
        return cls(**known)


@dataclass
class Verdict:
    allow: bool
    reason: str = ""
    rule: str = ""


@dataclass
class Call:
    tool: str
    path: str | None = None
    command: str | None = None
    cwd: str = "."


def _abs(p: str, cwd: str) -> Path:
    return Path(os.path.normpath(Path(cwd, os.path.expanduser(p)).absolute()))


def _work_dir(p: Path) -> Path | None:
    for d in p.parents:
        if (d / "work.json").exists():
            return d
    return None


def derived_reason(p: Path) -> str | None:
    """Why ``p`` is a derived file of some work dir, or None."""
    wd = _work_dir(p)
    if wd is None:
        return None
    rel = p.relative_to(wd)
    if rel.parts and rel.parts[0] in DERIVED_DIRS:
        return f"{rel.parts[0]}/ is built by the pipeline; fix the page files and rebuild"
    if rel.name in DERIVED_FILES or rel.name.endswith(DERIVED_SUFFIXES):
        return f"{rel.name} is built by the pipeline; never edit it by hand"
    return None


def _under(p: Path, root: str, cwd: str) -> bool:
    r = _abs(root, cwd)
    return p == r or r in p.parents


def _is_secret(p: Path, policy: Policy, cwd: str) -> bool:
    for s in policy.secret_files:
        if "/" in s or s.startswith("~"):
            if p == _abs(s, cwd):
                return True
        elif p.name == s:
            return True
    return False


def _in_territory(p: Path, territory: list[str], cwd: str) -> bool:
    return any(fnmatch.fnmatch(str(p), str(_abs(g, cwd))) for g in territory)


def _check_write(p: Path, policy: Policy, cwd: str) -> Verdict:
    for root in policy.forbidden_roots:
        if _under(p, root, cwd):
            return Verdict(False, f"{root} is off-limits: no writes without explicit approval", "forbidden-root")
    if _is_secret(p, policy, cwd):
        return Verdict(False, f"{p.name} holds credentials; never written by an agent", "secret")
    why = derived_reason(p)
    if why:
        return Verdict(False, why, "derived")
    if policy.territory and not _in_territory(p, policy.territory, cwd):
        return Verdict(False, f"{p} is outside this agent's territory ({', '.join(policy.territory)})", "territory")
    return Verdict(True)


def _check_read(p: Path, policy: Policy, cwd: str) -> Verdict:
    if _is_secret(p, policy, cwd):
        return Verdict(False, f"{p.name} holds credentials: scripts parse the one variable they need; never print it", "secret")
    return Verdict(True)


_REDIRECT = re.compile(r"(?:^|[^0-9&<>])>{1,2}\s*([^\s;|&<>]+)")
_SEGMENT_SPLIT = re.compile(r"\|\||&&|[;|\n]")


def _shell_targets(command: str) -> tuple[list[str], list[str]]:
    """(written paths, read paths) a shell command names, heuristically."""
    writes = [m.group(1) for m in _REDIRECT.finditer(command)]
    reads: list[str] = []
    for seg in _SEGMENT_SPLIT.split(command):
        try:
            argv = shlex.split(seg, posix=True)
        except ValueError:
            argv = seg.split()
        argv = [a for a in argv if not re.match(r"^\d?>{1,2}", a)]
        if not argv:
            continue
        cmd, args = os.path.basename(argv[0]), [a for a in argv[1:] if not a.startswith("-")]
        if cmd == "tee":
            writes += args
        elif cmd == "sed" and any(a.startswith("-i") for a in argv[1:]):
            writes += args[1:]
        elif cmd in ("cp", "mv", "install", "rsync") and len(args) >= 2:
            writes.append(args[-1])
        elif cmd in ("rm", "touch", "truncate"):
            writes += args
        if cmd in ("cat", "less", "more", "head", "tail", "source", ".", "grep", "bat", "strings", "xxd"):
            reads += args
    return writes, reads


def _check_shell(call: Call, policy: Policy, grants: set[str]) -> Verdict:
    command, cwd = call.command or "", call.cwd
    for pat in policy.paid_commands:
        if re.search(pat, command) and "paid" not in grants:
            return Verdict(False, f"`{pat}` is a paid route; it runs only on a job the owner authorized (no grant in this session)", "paid")
    producer = any(p in command for p in (*BUILTIN_PRODUCERS, *policy.producers))
    writes, reads = _shell_targets(command)
    for w in writes:
        p = _abs(w, cwd)
        if producer and derived_reason(p):
            continue
        v = _check_write(p, policy, cwd)
        if not v.allow:
            return v
    for r in reads:
        v = _check_read(_abs(r, cwd), policy, cwd)
        if not v.allow:
            return v
    if not producer:
        for root in policy.forbidden_roots:
            r = str(_abs(root, cwd))
            if re.search(r"\bgit\s+(commit|push)|\bgh\s+pr\s+create", command) and (
                    str(_abs(".", cwd)).startswith(r) or r in command):
                return Verdict(False, f"{root} is off-limits: no commits or PRs without explicit approval", "forbidden-root")
    return Verdict(True)


def check(call: Call, policy: Policy, grants: set[str] | None = None) -> Verdict:
    grants = grants or set()
    tool = call.tool.lower()
    if tool in WRITE_TOOLS and call.path:
        return _check_write(_abs(call.path, call.cwd), policy, call.cwd)
    if tool in READ_TOOLS and call.path:
        return _check_read(_abs(call.path, call.cwd), policy, call.cwd)
    if tool in SHELL_TOOLS and call.command:
        return _check_shell(call, policy, grants)
    return Verdict(True)


app = typer.Typer(add_completion=False, help="May this tool call run? The work-dir contract as a policy.")


@app.command("check")
def check_cmd(
    tool: Annotated[str, typer.Option(help="write | edit | read | bash | ...")],
    path: Annotated[str, typer.Option()] = None,
    command: Annotated[str, typer.Option()] = None,
    cwd: Annotated[str, typer.Option()] = ".",
    policy: Annotated[Path, typer.Option(help="Policy JSON")] = None,
    territory: Annotated[list[str], typer.Option(help="Allowed write glob (repeatable)")] = None,
    grant: Annotated[list[str], typer.Option(help="Grants held by this session, e.g. paid")] = None,
):
    """Print {allow, reason, rule} as JSON; exit 1 when blocked."""
    pol = Policy.load(policy)
    if territory:
        pol.territory = list(territory)
    v = check(Call(tool=tool, path=path, command=command, cwd=cwd), pol, set(grant or []))
    print(json.dumps(asdict(v), ensure_ascii=False))
    raise typer.Exit(0 if v.allow else 1)


_CLAUDE_TOOLS = {"Write": "write", "Edit": "edit", "MultiEdit": "edit", "NotebookEdit": "edit",
                 "Read": "read", "Bash": "bash"}


@app.command("claude-hook")
def claude_hook_cmd(
    policy: Annotated[Path, typer.Option(help="Policy JSON")] = None,
    grant: Annotated[list[str], typer.Option()] = None,
):
    """A Claude Code PreToolUse hook: reads the hook JSON on stdin, exits 2 to block."""
    data = json.load(sys.stdin)
    inp = data.get("tool_input") or {}
    tool = _CLAUDE_TOOLS.get(data.get("tool_name", ""))
    if tool is None:
        raise typer.Exit(0)
    call = Call(tool=tool, path=inp.get("file_path") or inp.get("notebook_path"),
                command=inp.get("command"), cwd=data.get("cwd") or ".")
    v = check(call, Policy.load(policy), set(grant or []))
    if not v.allow:
        print(f"Blocked by the work-dir contract ({v.rule}): {v.reason}", file=sys.stderr)
        raise typer.Exit(2)


if __name__ == "__main__":
    app()
