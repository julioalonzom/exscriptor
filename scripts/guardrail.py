#!/usr/bin/env python3
"""May this pull request merge without the maintainer? CI's `guardrail` check.

    gh api repos/OWNER/REPO/pulls/N/files --paginate --jq '.[]' \
        | python3 scripts/guardrail.py [--approved]

It reads the pull request's files, one JSON object per line, as GitHub's
API lists them (filename, status, previous_filename, patch).

Everything else merges on its own once its checks are green: the tests, the
proof check (scripts/prove.py) and the sample job (tests/test_pipeline.py)
are the review. These paths are what those checks stand on, so a change to
them waits for the maintainer: CI and these scripts, the rules agents
follow (AGENTS.md, CONTRIBUTING.md, the review instructions), dependencies
and test configuration, the sample job's inputs, and the spelling list,
whose rows no test can judge. So does removing a test: deleting or renaming
a test file, or dropping a test function. The proof check sees a pull
request add tests, never take them away; a test made weaker in place is
the one gap left, and the sample job and preflight are what stand behind it.

`--approved` means the pull request carries the `maintainer-approved` label,
which an agent adds only when the maintainer said yes in its conversation.
The workflow removes the label on every push, so a yes covers the head it
was given for. CI runs main's copy of this script (pull_request_target), so
a pull request cannot loosen the check that judges it.
"""
from __future__ import annotations

import json
import re
import sys

GUARDRAILS = re.compile(
    r"^(\.github/|scripts/|AGENTS\.md$|CONTRIBUTING\.md$|docs/review\.md$"
    r"|pyproject\.toml$|uv\.lock$|(.*/)?(conftest\.py|pytest\.ini|tox\.ini|setup\.cfg)$"
    r"|tests/test_(prove|guardrail|pipeline|review|house)\.py$|tests/fixtures/sample-work/"
    r"|src/exscriptor/spelling-map\.tsv$)")


TEST_FILE = re.compile(r"^tests/(.*/)?test_[^/]*\.py$")
TEST_DEF = re.compile(r"^([+-])\s*(?:async\s+)?def\s+(test_\w+)", re.M)


def touched(changed: list[str]) -> list[str]:
    return sorted(f for f in changed if GUARDRAILS.search(f))


def removed_tests(files: list[dict]) -> list[str]:
    """Test files deleted or renamed, and test functions dropped (a name on a
    removed diff line that no added line brings back)."""
    out = []
    for f in files:
        name = f["filename"]
        if f.get("status") in ("removed", "renamed") and TEST_FILE.match(f.get("previous_filename") or name):
            out.append(f"{f.get('previous_filename') or name} ({f['status']})")
        elif TEST_FILE.match(name):
            lines = TEST_DEF.findall(f.get("patch") or "")
            dropped = {n for s, n in lines if s == "-"} - {n for s, n in lines if s == "+"}
            out += [f"{name}::{n} (removed)" for n in sorted(dropped)]
    return out


def main() -> None:
    approved = "--approved" in sys.argv[1:]
    files = [json.loads(line) for line in sys.stdin if line.strip()]
    paths = [p for f in files for p in (f["filename"], f.get("previous_filename")) if p]
    hits = touched(paths) + removed_tests(files)
    if not hits:
        print("PASS: touches no guardrail; it merges when its checks are green.")
        return
    listing = "\n  ".join(hits)
    if approved:
        print(f"PASS: the maintainer approved this head. Guardrails touched:\n  {listing}")
        return
    sys.exit(f"WAIT FOR THE MAINTAINER: this pull request touches guardrails:\n  {listing}\n"
             "Ask the maintainer; on their yes, add the label maintainer-approved.")


if __name__ == "__main__":
    main()
