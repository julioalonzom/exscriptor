"""scripts/prove.py: what a pull request must show before it merges on its own."""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("prove", Path(__file__).parents[1] / "scripts" / "prove.py")
prove = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prove)


def test_no_src_change_needs_no_proof():
    assert prove.decide(["skills/translation/SKILL.md", "README.md"], "skills: wording") == ("none", [])


def test_a_src_change_runs_its_changed_tests():
    changed = ["src/exscriptor/ledger.py", "tests/test_alignment.py", "tests/fixtures/x.json"]
    assert prove.decide(changed, "alignment: pair by id") == ("run", ["tests/test_alignment.py"])


def test_a_src_change_without_a_test_is_unproven():
    assert prove.decide(["src/exscriptor/ledger.py", "README.md"], "fix") == ("unproven", [])


def test_changed_expected_outputs_run_the_sample_job():
    changed = ["src/exscriptor/expand.py", "tests/fixtures/sample-expected/edition/pg-009.md"]
    assert prove.decide(changed, "expand: x") == ("run", ["tests/test_pipeline.py"])


def test_a_refactor_must_leave_tests_alone():
    assert prove.decide(["src/exscriptor/a.py"], "refactor: split a helper") == ("refactor", [])
    assert prove.decide(["src/exscriptor/a.py", "tests/test_a.py"], "Refactor: x") == (
        "refactor-touches-tests", ["tests/test_a.py"])


def test_only_a_failing_or_uncollectable_test_proves():
    assert prove.verdict(1) and prove.verdict(2)
    assert not any(prove.verdict(code) for code in (0, 3, 4, 5))
