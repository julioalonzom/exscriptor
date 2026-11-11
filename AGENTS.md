# Exscriptor agent guide

## What this repo is

Generic tooling for digitizing scanned texts: batch VLM transcription,
OCR second witness, witness collation, deterministic cleanup, structure
screens, credential resolution. See README.md for usage.

The library contains no edition-specific logic: no work names, no
publisher names, no hardcoded paths. Anything edition-specific belongs in
the consumer's own project, built on top of this library. If a change
would require naming a specific work or edition here, parameterize
instead.

One policy is shipped here on purpose: the corpus spelling list,
`src/exscriptor/spelling-map.tsv`, so that every project and every work
reads the same reviewed list. Change it only as CONTRIBUTING.md says (a
class, evidence in the reason, collisions searched, the trap test kept).

`skills/` is the other: the agent skills for Schola Thomistica jobs, which
name the corpus and its API by design. The work-agnostic rule still holds
in them (no work names as rules, no machine paths, no person's name). A
change to a command's flags updates the skills that cite it;
`tests/test_skills.py` checks that every file a skill points to exists.

## For agents working with this library

1. Install: `pip install git+https://github.com/julioalonzom/exscriptor.git`
   (or a local clone, editable).
2. If something is missing, hardcoded, or awkward for your use case, that
   is a bug in this library — fix it here with a test, through a pull
   request (below).
   Do not copy-and-patch the logic into your own project; that fork is
   exactly what this library exists to avoid.
3. Keep the work-agnostic rule above when you change things.
4. Commit messages should say what changed and why; small, one-concern
   commits.

## Changing exscriptor

`main` is what every job runs: the maintainer's sessions, the cloud worker
(at a pinned commit) and every magister who pulls. Nobody reads this code
but agents, so the guardrails are the tests, CI and an independent review.

1. Work on a short-lived branch in your own worktree, never in a shared
   checkout another session is using. One branch per change or experiment;
   merge it or close it, never keep a long-lived personal branch.
2. Open a pull request. CI runs the tests on it.
3. Review: from a clean checkout of the branch at its pushed head, run
   `python3 scripts/review.py <PR>`. DeepSeek reviews it read-only against
   `docs/review.md` and the script posts the verdict. Fix what it finds,
   push, and review the new head.
4. Merge: `python3 scripts/merge_gate.py <PR>`. On `MERGE`, run exactly the
   command it prints. On `ASK JULIO` (the change touches CI, the review or
   gate scripts, `docs/review.md`, this file or a dependency, or the review
   or CI failed), bring Julio the failing lines and wait.
