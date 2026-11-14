#!/usr/bin/env python3
"""Does this pull request prove its change? CI's `proof` check.

    python3 scripts/prove.py <base sha> "<pull request title>"

A change to src/ comes with a test that fails without it: the pull
request's added or changed test files (and the sample job, when its
expected outputs changed) are run against the base's src/, and at least
one test must fail there (exit PROVEN). A test that passes on the
old code tests nothing new (HOLLOW, exit 1); src/ changed with no test file
changed is UNPROVEN (exit 1).

A pull request whose title starts `refactor:` claims no behaviour change:
it must leave tests/ untouched, so the existing suite, unchanged, is the
proof. A pull request that does not touch src/ needs no proof here.

Run from a checkout of the pull request's head. It overwrites src/ with the
base's copy in that checkout, so run it on a throwaway checkout (CI's).
"""
from __future__ import annotations

import re
import subprocess
import sys

TEST = re.compile(r"^tests/(.*/)?test_[^/]*\.py$")
EXPECTED, PIPELINE = "tests/fixtures/sample-expected/", "tests/test_pipeline.py"


def decide(changed: list[str], title: str) -> tuple[str, list[str]]:
    """What the pull request must show: ("none" | "refactor" | "run" | "unproven"
    | "refactor-touches-tests", the test files to run)."""
    if not any(f.startswith("src/") for f in changed):
        return "none", []
    tests = {f for f in changed if TEST.match(f)}
    if any(f.startswith(EXPECTED) for f in changed):  # the sample job's outputs changed
        tests.add(PIPELINE)
    tests = sorted(tests)
    if title.strip().lower().startswith("refactor:"):
        touched = [f for f in changed if f.startswith("tests/")]
        return ("refactor-touches-tests", touched) if touched else ("refactor", [])
    return ("run", tests) if tests else ("unproven", [])


def verdict(pytest_exit: int) -> bool:
    """1: tests failed on the old code (proven). 2: collection failed, as when the
    test imports what the change adds (proven: it cannot run without it).
    0: it passes without the change (hollow); 5: nothing collected."""
    return pytest_exit in (1, 2)


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], text=True)


def main() -> None:
    if len(sys.argv) != 3:
        sys.exit("usage: python3 scripts/prove.py <base sha> <title>")
    base, title = sys.argv[1], sys.argv[2]
    changed = git("diff", "--name-only", "--diff-filter=d", f"{base}...HEAD").split()
    kind, tests = decide(changed, title)
    if kind == "none":
        print("PROVEN: src/ is unchanged; nothing to prove.")
        return
    if kind == "refactor":
        print("PROVEN: a refactor that leaves tests/ untouched; the unchanged suite is the proof.")
        return
    if kind == "refactor-touches-tests":
        sys.exit("UNPROVEN: a refactor: title claims no behaviour change, but tests/ changed: "
                 + ", ".join(tests) + ". Split the test change out, or drop the refactor: prefix.")
    if kind == "unproven":
        sys.exit("UNPROVEN: src/ changed and no test file did. Add a test that fails without the change, "
                 "or title the pull request 'refactor: …' if behaviour is unchanged.")
    subprocess.run(["git", "checkout", base, "--", "src"], check=True)
    exit_code = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *tests]).returncode
    if verdict(exit_code):
        print(f"PROVEN: {', '.join(tests)} fail on the base's src/ (pytest exit {exit_code}).")
        return
    sys.exit(f"HOLLOW: {', '.join(tests)} pass on the base's src/ (pytest exit {exit_code}), "
             "so they do not test this change. Make one fail without it.")


if __name__ == "__main__":
    main()
