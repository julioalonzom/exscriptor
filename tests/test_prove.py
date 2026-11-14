"""scripts/prove.py: what a pull request must show before it merges on its own."""
import importlib.util
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "prove.py"
spec = importlib.util.spec_from_file_location("prove", SCRIPT)
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


def test_a_deleted_src_file_is_a_change_and_a_deleted_test_is_not_run():
    changed = ["src/exscriptor/gate.py", "tests/test_gate.py"]
    deleted = frozenset(changed)
    assert prove.decide(changed, "drop the gate", deleted) == ("unproven", [])
    assert prove.decide(changed, "refactor: drop the gate", deleted) == (
        "refactor-touches-tests", ["tests/test_gate.py"])


# main() on a real repository: the base has src/mod.py (f() == 1); each case
# commits a pull request on top and runs the script as CI does.
TEST_HEADER = "import sys\nsys.path.insert(0, 'src')\n"


def git(repo, *args):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=repo, check=True,
                   capture_output=True)


def pull_request(tmp_path, files, delete=()):
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "tests").mkdir()
    (repo / "src" / "mod.py").write_text("def f():\n    return 1\n")
    git(repo, "init", "-q")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "base")
    base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    for name, text in files.items():
        (repo / name).write_text(text)
    for name in delete:
        (repo / name).unlink()
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "change")
    r = subprocess.run([sys.executable, str(SCRIPT), base, "change"], cwd=repo, capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


def test_main_proves_a_test_that_fails_on_the_base(tmp_path):
    code, out = pull_request(tmp_path, {
        "src/mod.py": "def f():\n    return 2\n",
        "tests/test_mod.py": TEST_HEADER + "from mod import f\ndef test_f():\n    assert f() == 2\n"})
    assert code == 0 and out.splitlines()[-1].startswith("PROVEN"), out


def test_main_calls_a_test_that_passes_on_the_base_hollow(tmp_path):
    code, out = pull_request(tmp_path, {
        "src/mod.py": "def f():\n    return 1  # reworded\n",
        "tests/test_mod.py": TEST_HEADER + "from mod import f\ndef test_f():\n    assert f() == 1\n"})
    assert code == 1 and "HOLLOW" in out, out


def test_main_proves_a_new_module_its_test_cannot_import_on_the_base(tmp_path):
    code, out = pull_request(tmp_path, {
        "src/new.py": "def g():\n    return 3\n",
        "tests/test_new.py": TEST_HEADER + "from new import g\ndef test_g():\n    assert g() == 3\n"})
    assert code == 0 and out.splitlines()[-1].startswith("PROVEN"), out


def test_main_does_not_wave_through_a_deleted_module(tmp_path):
    code, out = pull_request(tmp_path, {}, delete=["src/mod.py"])
    assert code == 1 and "UNPROVEN" in out, out
