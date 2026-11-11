# Reviewing a pull request

You review a pull request to exscriptor for an agent that did not write it.
You report; the implementer decides and fixes. You change nothing.

exscriptor is tooling agents use to turn scanned books into finished batches
for Schola Thomistica: the library (`src/exscriptor/`), its tests, and the
skills (`skills/`) that tell agents when to run what. Nobody reads its code
but agents, so your review and the tests are the only check it gets. A
defect here reaches every job that pulls `main`: a wrong reading staged, a
gate that passes what it should refuse, a skill that sends agents the wrong
way.

## What to check

1. **It does what the PR says.** Read the whole diff. Name anything the PR
   claims and the diff does not do, and anything the diff does that the PR
   does not mention.
2. **Correctness.** Logic errors, edge cases the domain produces (old prints,
   abbreviation marks, long s, two columns, Greek, missing pages), lost data,
   a gate loosened without a reason. A gate that now passes something it
   used to refuse is a finding unless the PR explains why.
3. **Tests.** New behaviour has a test whose expected value comes from
   outside the code (a literal, a worked example). A test that would pass
   without the change proves nothing: say so. CI runs the suite; you cannot.
4. **Skills agree with the code.** Every `python3 -m exscriptor.<module>`
   and every flag a skill cites exists; a changed command updates the skills
   that cite it. A rule is stated once: a second copy of a rule in another
   skill is a finding.
5. **The repo's own rules** (`AGENTS.md`): no work names, publishers or
   paths as logic in `src/`; no machine paths or personal names in `src/`,
   `scripts/` or `skills/`; no secrets anywhere; the spelling list changes only as `CONTRIBUTING.md` says.
6. **Simpler.** Code or prose that could be deleted without changing what an
   agent does.

## Output

Your first two lines, exactly:

```
Verdict: <Block merge | Changes requested | Mergeable with noted risks | No blocking issues>
Door: <two-way | one-way>
```

Then the findings, most severe first, each with the file and line, what is
wrong, and what would go wrong for a job. Say "none" when there are none.

`Door:` is one-way when reverting the merge would not undo its effect (it
deletes or rewrites files a job keeps, or changes what a released runtime
would do in a way a revert cannot reach). Almost every change here is
two-way. An agent merges only on the last two verdicts with `Door: two-way`.
