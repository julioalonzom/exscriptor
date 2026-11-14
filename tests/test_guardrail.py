"""scripts/guardrail.py: which changes wait for the maintainer."""
import importlib.util
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


def run(*args):
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True)


def test_a_guardrail_waits_until_approved():
    assert run("src/exscriptor/expand.py").returncode == 0
    held = run("src/exscriptor/expand.py", "AGENTS.md")
    assert held.returncode == 1 and "AGENTS.md" in held.stderr
    assert run("AGENTS.md", "--approved").returncode == 0
