#!/usr/bin/env python3
"""May an agent merge this pull request?

    python3 scripts/merge_gate.py <PR>

Prints one line per check, then `MERGE: <command>` (exit 0) or `ASK JULIO`
(exit 1); exit 2 means it could not decide, which counts as ASK. An agent
merges only with the printed command, which pins the reviewed head.

Merged without a person: an independent review (scripts/review.py) of the
exact head with an accepted verdict and `Door: two-way`, and every CI check
green on that head. Julio decides changes to these guardrails themselves
(CI, the review and gate scripts, the review instructions, AGENTS.md) and to
dependencies, which every job installs.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys

GUARDRAILS = re.compile(
    r"^(\.github/|scripts/(review|merge_gate)\.py$|docs/review\.md$|AGENTS\.md$|pyproject\.toml$|uv\.lock$)")
ACCEPTED = ("No blocking issues", "Mergeable with noted risks")
REVIEW = re.compile(r"## Review\r?\nReviewer: .+\r?\nReviewed: ([0-9a-f]{40})\r?\n"
                    r"Verdict: (.+?)\s*\r?\nDoor: (\S+)")
REQUIRED_CHECKS = ("pytest (3.10)", "pytest (3.12)")


def latest_review(comments: list[dict], head: str) -> tuple[str | None, str | None]:
    """The verdict and door of the newest review that names `head`; a comment
    that merely quotes the header later in its text does not count."""
    verdict = door = None
    for comment in sorted(comments, key=lambda c: c["created_at"]):
        match = REVIEW.match(comment["body"].lstrip())
        if match and match[1] == head:
            verdict, door = match[2], match[3]
    return verdict, door


def decide(pr: dict, files: list[str], comments: list[dict], checks: list[dict]) -> list[tuple[bool, str]]:
    head = pr["headRefOid"]
    results = [(pr["state"] == "OPEN" and not pr["isDraft"] and pr["baseRefName"] == "main",
                "an open, ready pull request into main"),
               (pr["mergeable"] == "MERGEABLE", f"GitHub can merge it ({pr['mergeable']})")]
    touched = sorted(f for f in files if GUARDRAILS.search(f))
    results.append((not touched, "touches no guardrail or dependency" if not touched else
                    "touches a guardrail or dependency: " + ", ".join(touched)))
    verdict, door = latest_review(comments, head)
    results.append((verdict in ACCEPTED, f"review of {head[:8]}: {verdict or 'none posted'}"))
    results.append((door == "two-way", f"reviewer's Door: {door or 'not stated'}"))
    states = {c["name"]: c.get("conclusion") or c.get("status") for c in checks}
    missing = [name for name in REQUIRED_CHECKS if name not in states]
    red = sorted(f"{name}={state}" for name, state in states.items() if state != "SUCCESS")
    results.append((not missing and not red, f"CI on {head[:8]}: " + (
        "green" if not missing and not red else ", ".join([f"{m}=missing" for m in missing] + red))))
    return results


def gh(*arguments: str) -> str:
    return subprocess.check_output(["gh", *arguments], text=True)


def main() -> None:
    number = sys.argv[1] if len(sys.argv) > 1 else ""
    if not number.isdigit():
        sys.exit("usage: python3 scripts/merge_gate.py <PR>")
    try:
        repo = gh("repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner").strip()
        pr = json.loads(gh("pr", "view", number, "--repo", repo, "--json",
                           "state,isDraft,baseRefName,headRefOid,mergeable,statusCheckRollup"))
        pages = json.loads(gh("api", f"repos/{repo}/pulls/{number}/files?per_page=100", "--paginate", "--slurp"))
        files = [name for page in pages for f in page for name in (f["filename"], f.get("previous_filename")) if name]
        pages = json.loads(gh("api", f"repos/{repo}/issues/{number}/comments?per_page=100", "--paginate", "--slurp"))
        comments = [c for page in pages for c in page]
        results = decide(pr, files, comments, pr["statusCheckRollup"])
    except (subprocess.CalledProcessError, json.JSONDecodeError, KeyError) as error:
        print(f"CANNOT DECIDE: {error}")
        sys.exit(2)
    for ok, message in results:
        print(f"{'PASS' if ok else 'FAIL'}  {message}")
    if not all(ok for ok, _ in results):
        print("ASK JULIO")
        sys.exit(1)
    print(f"MERGE: gh pr merge {number} --repo {repo} --merge --match-head-commit {pr['headRefOid']}")


if __name__ == "__main__":
    main()
