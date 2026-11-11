"""The merge gate merges only a reviewed, green, ordinary change."""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "merge_gate", Path(__file__).resolve().parent.parent / "scripts/merge_gate.py")
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)

HEAD = "a" * 40
OLD = "b" * 40
PR = {"state": "OPEN", "isDraft": False, "baseRefName": "main", "headRefOid": HEAD, "mergeable": "MERGEABLE"}
GREEN = [{"name": "pytest (3.10)", "conclusion": "SUCCESS"}, {"name": "pytest (3.12)", "conclusion": "SUCCESS"}]


OWNER = "owner"


def review(sha, verdict="No blocking issues", door="two-way", at="2026-11-11T10:00:00Z", by=OWNER):
    body = f"## Review\nReviewer: Pi CLI\nReviewed: {sha}\nVerdict: {verdict}\nDoor: {door}\nnone\n"
    return {"body": body, "created_at": at, "user": {"login": by}}


def ok(files=("src/exscriptor/expand.py",), comments=None, checks=GREEN, pr=PR):
    comments = [review(HEAD)] if comments is None else comments
    return all(passed for passed, _ in gate.decide(pr, list(files), comments, checks, OWNER))


def test_reviewed_green_ordinary_change_merges():
    assert ok()


def test_a_review_of_an_older_head_does_not_count():
    assert not ok(comments=[review(OLD)])


def test_a_refusal_of_the_head_holds_whatever_comes_after():
    later = review(HEAD, "Changes requested", at="2026-11-11T11:00:00Z")
    assert not ok(comments=[review(HEAD), later])
    rerun = review(HEAD, at="2026-11-11T12:00:00Z")
    assert not ok(comments=[later, rerun])
    assert ok(comments=[review(OLD, "Changes requested"), review(HEAD)])


def test_a_quoted_header_is_not_a_review():
    quoted = {**review(HEAD, at="2026-11-11T12:00:00Z"), "body": "As agreed:\n" + review(HEAD)["body"]}
    assert not ok(comments=[quoted])


def test_a_review_posted_by_anyone_else_does_not_count():
    assert not ok(comments=[review(HEAD, by="someone-else")])


def test_one_way_door_or_blocking_verdict_stops_it():
    assert not ok(comments=[review(HEAD, door="one-way")])
    assert not ok(comments=[review(HEAD, "Block merge")])


def test_red_or_missing_ci_stops_it():
    assert not ok(checks=[GREEN[0]])
    assert not ok(checks=[GREEN[0], {"name": "pytest (3.12)", "conclusion": "FAILURE"}])
    assert not ok(checks=[{"name": "pytest (3.10)", "status": "IN_PROGRESS"}, GREEN[1]])
    assert not ok(checks=[*GREEN, {"context": "legacy/status", "state": "PENDING"}])
    assert ok(checks=[*GREEN, {"context": "legacy/status", "state": "SUCCESS"}])
    assert ok(checks=[*GREEN, {"name": "optional", "conclusion": "SKIPPED"}])
    assert not ok(checks=[GREEN[0], {"name": "pytest (3.12)", "conclusion": "SKIPPED"}])
    assert not ok(checks=[*GREEN, {"name": "pytest (3.12)", "conclusion": "FAILURE"}])


def test_guardrails_and_dependencies_go_to_the_maintainer():
    for path in (".github/workflows/tests.yml", "scripts/merge_gate.py", "scripts/review.py",
                 "tests/test_merge_gate.py", "docs/review.md", "AGENTS.md", "CONTRIBUTING.md", "pyproject.toml",
                 "conftest.py", "tests/conftest.py", "pytest.ini"):
        assert not ok(files=[path]), path
    assert ok(files=["skills/corpus-import/SKILL.md", "scripts/other.py", "tests/test_expand.py",
                     "src/exscriptor/spelling-map.tsv"])


def test_no_checks_at_all_is_not_green():
    assert not ok(checks=None)


def test_the_merge_command_pins_the_reviewed_head():
    assert gate.merge_command("5", "o/r", HEAD) == f"gh pr merge 5 --repo o/r --merge --match-head-commit {HEAD}"


def test_draft_or_conflicted_stops_it():
    assert not ok(pr={**PR, "isDraft": True})
    assert not ok(pr={**PR, "mergeable": "CONFLICTING"})


def test_required_checks_are_the_workflow_matrix():
    import re
    workflow = (Path(__file__).resolve().parent.parent / ".github/workflows/tests.yml").read_text()
    job = re.search(r"^  (\w+):\n    runs-on", workflow, re.M)[1]
    versions = re.search(r"python: \[(.+)\]", workflow)[1].replace('"', "").split(", ")
    assert set(gate.REQUIRED_CHECKS) == {f"{job} ({v})" for v in versions}
