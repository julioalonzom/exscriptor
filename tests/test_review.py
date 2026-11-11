"""The review script posts only a well-formed verdict, in the header the gate reads."""
import importlib.util
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"


def load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


review, gate = load("review"), load("merge_gate")
HEAD = "c" * 40


def test_preamble_and_emphasis_are_dropped():
    raw = "I read the diff.\n\n**Verdict:** No blocking issues\n**Door:** two-way\n\nnone\n"
    assert review.normalize(raw) == "Verdict: No blocking issues\nDoor: two-way\n\nnone\n"


@pytest.mark.parametrize("raw", [
    "Verdict: Looks fine\nDoor: two-way\n",                    # unknown verdict
    "Verdict: No blocking issues\n\nnone\n",                   # no Door
    "Verdict: No blocking issues\nDoor: sideways\n",            # unknown door
    "Verdict: No blocking issues\nDoor: two-way\nReviewed: " + HEAD + "\n",  # forges the head
])
def test_a_malformed_review_is_refused(raw):
    with pytest.raises(ValueError):
        review.normalize(raw)


def test_the_posted_comment_is_what_the_gate_reads():
    body = review.comment("deepseek/deepseek-flash", HEAD,
                          review.normalize("Verdict: Mergeable with noted risks\nDoor: two-way\nnone\n"))
    comments = [{"body": body, "created_at": "2026-11-11T10:00:00Z", "user": {"login": "owner"}}]
    assert gate.latest_review(comments, HEAD, "owner") == ("Mergeable with noted risks", "two-way")
