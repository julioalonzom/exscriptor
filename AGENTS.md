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
class, evidence in the reason, collisions searched, the trap test kept);
no test can judge a row, so a change to it waits for the maintainer.

`skills/` is the other: the agent skills for Schola Thomistica jobs, which
name the corpus and its API by design. The work-agnostic rule still holds
in them (no work names as rules, no machine paths, no person's name). A
change to a command's flags updates the skills that cite it;
`tests/test_skills.py` checks that every file a skill points to exists.

## For agents working with this library

1. Install: `pip install git+https://github.com/julioalonzom/exscriptor.git`
   (or a local clone, editable; `pip install -e '.[test]'` to run the tests).
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
but agents, so a change merges on verification, not on anyone's reading:

- `pytest`: the suite, including the sample job (`tests/test_pipeline.py`),
  which runs a real four-page job through every command and requires that
  the finished batches pass preflight. Its outputs must equal
  `tests/fixtures/sample-expected/`. When a change is meant to alter them,
  regenerate with `EXSCRIPTOR_UPDATE_EXPECTED=1 python3 -m pytest
  tests/test_pipeline.py`, and the diff shows in the pull request.
- `proof` (`scripts/prove.py`): a change to `src/` comes with a test that
  fails on the base's code. A pull request titled `refactor: …` instead
  leaves `tests/` untouched.
- `guardrail` (`scripts/guardrail.py`, run from `main`): a change to what
  these checks stand on (CI, `scripts/`, this file, CONTRIBUTING.md, the
  review instructions, dependencies, test configuration, the sample job's
  inputs, the spelling list) waits for the maintainer. So does removing a
  test: deleting or renaming a test file, or dropping a test function. Fix
  a red test by fixing the code, or by changing the test in place when its
  expectation was wrong.

1. Work on a short-lived branch in your own worktree, never in a shared
   checkout another session is using. One branch per change or experiment;
   merge it or close it, never keep a long-lived personal branch.
2. Prove it before you push: run the suite, and show your new test fails
   without your change (the `proof` check does the same).
3. Open the pull request and arm auto-merge in the same step:
   `gh pr merge <PR> --auto --merge`. GitHub merges it once every check
   is green. Nobody has to come back for it, and you don't wait for it.
4. A red check is yours to fix: push to the same branch.
5. `guardrail` fails: tell the maintainer in your conversation what the
   change does to the guardrail and why. On their yes, and only then, add
   the label: `gh pr edit <PR> --add-label maintainer-approved`. A later
   push removes it, so that yes covers only the head they saw.
6. A second opinion is your tool, not a gate. For a change whose risk no test
   can see (a skill's instructions, a judgment call in a gate), run
   `python3 scripts/review.py <PR>` (DeepSeek, read-only, against
   `docs/review.md`; the key in `DEEPSEEK_API_KEY` or `--key-file`), once.
   Decide each finding yourself: fix it, or record it on an issue. Its
   verdict blocks nothing.

When a merged change turns out wrong, revert it with a pull request, and
add the test or check that would have caught it.


