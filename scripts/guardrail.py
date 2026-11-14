#!/usr/bin/env python3
"""May this pull request merge without the maintainer? CI's `guardrail` check.

    python3 scripts/guardrail.py <changed file>... [--approved]

Everything else merges on its own once its checks are green: the tests, the
proof check (scripts/prove.py) and the sample job (tests/test_pipeline.py)
are the review. These paths are what those checks stand on, so a change to
them waits for the maintainer: CI and these scripts, the rules agents
follow (AGENTS.md, CONTRIBUTING.md, the review instructions), dependencies
and test configuration, the sample job's inputs, and the spelling list,
whose rows no test can judge.

`--approved` means the pull request carries the `maintainer-approved` label,
which an agent adds only when the maintainer said yes in its conversation.
The workflow removes the label on every push, so a yes covers the head it
was given for. CI runs main's copy of this script (pull_request_target), so
a pull request cannot loosen the check that judges it.
"""
from __future__ import annotations

import re
import sys

GUARDRAILS = re.compile(
    r"^(\.github/|scripts/|AGENTS\.md$|CONTRIBUTING\.md$|docs/review\.md$"
    r"|pyproject\.toml$|uv\.lock$|(.*/)?(conftest\.py|pytest\.ini|tox\.ini|setup\.cfg)$"
    r"|tests/test_(prove|guardrail|pipeline|review|house)\.py$|tests/fixtures/sample-work/"
    r"|src/exscriptor/spelling-map\.tsv$)")


def touched(changed: list[str]) -> list[str]:
    return sorted(f for f in changed if GUARDRAILS.search(f))


def main() -> None:
    args = sys.argv[1:]
    approved = "--approved" in args
    hits = touched([a for a in args if a != "--approved"])
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
