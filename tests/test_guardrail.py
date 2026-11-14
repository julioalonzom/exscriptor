"""scripts/guardrail.py: which changes wait for the maintainer."""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "guardrail.py"
spec = importlib.util.spec_from_file_location("guardrail", SCRIPT)
guardrail = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guardrail)


def test_what_the_checks_stand_on_is_a_guardrail():
    held = [".github/workflows/tests.yml", "scripts/prove.py", "scripts/review.py", "AGENTS.md",
            "CONTRIBUTING.md", "docs/review.md", "pyproject.toml", "tests/conftest.py",
            "tests/test_pipeline.py", "tests/test_prove.py", "tests/test_guardrail.py", "tests/test_house.py",
            "tests/fixtures/sample-work/decisions.tsv", "src/exscriptor/spelling-map.tsv"]
    assert guardrail.touched(held) == sorted(held)


def test_ordinary_work_merges_on_its_checks():
    free = ["src/exscriptor/expand.py", "tests/test_expand.py", "skills/translation/SKILL.md", "README.md",
            "tests/fixtures/sample-expected/edition/pg-009.md", "docs/house-rules-and-prompts.md"]
    assert guardrail.touched(free) == []


def test_removing_a_test_waits_for_the_maintainer():
    files = [
        {"filename": "tests/test_alignment.py", "status": "removed"},
        {"filename": "tests/test_new.py", "previous_filename": "tests/test_expand.py", "status": "renamed"},
        {"filename": "tests/test_assemble.py", "status": "modified",
         "patch": "@@\n-def test_joins_a_hyphen():\n-    assert x\n+def test_space():\n"},
    ]
    assert guardrail.removed_tests(files) == [
        "tests/test_alignment.py (removed)", "tests/test_expand.py (renamed)",
        "tests/test_assemble.py::test_joins_a_hyphen (removed)"]


def test_adding_or_editing_a_test_is_not_removing_one():
    files = [
        {"filename": "tests/test_new.py", "status": "added", "patch": "+def test_a():\n+    pass\n"},
        {"filename": "tests/test_expand.py", "status": "modified",
         "patch": "@@\n-def test_b(x):\n+def test_b(x, y):\n+def test_c():\n"},
        {"filename": "tests/fixtures/x.json", "status": "removed"},
    ]
    assert guardrail.removed_tests(files) == []


def run(*args, files=()):
    stdin = "".join(json.dumps(f) + "\n" for f in files)
    return subprocess.run([sys.executable, str(SCRIPT), *args], input=stdin, capture_output=True, text=True)


def test_a_guardrail_waits_until_approved():
    src = {"filename": "src/exscriptor/expand.py", "status": "modified"}
    agents = {"filename": "AGENTS.md", "status": "modified"}
    assert run(files=[src]).returncode == 0
    held = run(files=[src, agents])
    assert held.returncode == 1 and "AGENTS.md" in held.stderr
    assert run("--approved", files=[agents]).returncode == 0
    gone = run(files=[{"filename": "tests/test_alignment.py", "status": "removed"}])
    assert gone.returncode == 1 and "tests/test_alignment.py (removed)" in gone.stderr
