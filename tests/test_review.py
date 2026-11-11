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


def test_emphasis_is_dropped_and_text_above_the_verdict_moves_below():
    raw = "1. a finding\n\n**Verdict:** Changes requested\n**Door:** two-way\n\nmore\n"
    assert review.normalize(raw) == "Verdict: Changes requested\nDoor: two-way\n\nmore\n\n1. a finding\n"


@pytest.mark.parametrize("raw", [
    "Verdict: Looks fine\nDoor: two-way\n",                    # unknown verdict
    "Verdict: No blocking issues\n\nnone\n",                   # no Door
    "Verdict: No blocking issues\nDoor: sideways\n",            # unknown door
    "Verdict: No blocking issues\nDoor: two-way\nReviewed: " + HEAD + "\n",  # forges the head
])
def test_a_malformed_review_is_refused(raw):
    with pytest.raises(ValueError):
        review.normalize(raw)


def test_a_blank_line_between_verdict_and_door_is_accepted():
    assert review.normalize("Verdict: No blocking issues\n\nDoor: two-way\nnone\n") == \
        "Verdict: No blocking issues\nDoor: two-way\nnone\n"


def test_the_comment_header_is_fixed():
    assert review.comment("m", HEAD, "Verdict: X\n") == f"## Review\nReviewer: Pi CLI, m (read-only, scripts/review.py)\nReviewed: {HEAD}\nVerdict: X\n"


def test_the_posted_comment_is_what_the_gate_reads():
    body = review.comment("deepseek/deepseek-flash", HEAD,
                          review.normalize("Verdict: Mergeable with noted risks\nDoor: two-way\nnone\n"))
    comments = [{"body": body, "created_at": "2026-11-11T10:00:00Z", "user": {"login": "owner"}}]
    assert gate.latest_review(comments, HEAD, "owner") == ("Mergeable with noted risks", "two-way")


@pytest.mark.parametrize("text", ["sk-" + "a1" * 12, "ghp_" + "Z9" * 10, "-----BEGIN RSA PRIVATE KEY"])
def test_a_secret_shaped_body_is_caught(text):
    assert review.SECRET.search(f"Verdict: No blocking issues\nDoor: two-way\n{text}\n")


def test_an_ordinary_review_is_not_taken_for_a_secret():
    assert not review.SECRET.search("Verdict: No blocking issues\nDoor: two-way\nsk-learn is fine; task-list ok\n")


def test_the_key_file_line_is_read(tmp_path, monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    env = tmp_path / ".env"
    env.write_text('OTHER=1\nDEEPSEEK_API_KEY="abc123"\n')
    assert review.read_key(env) == "abc123"
    assert review.read_key(tmp_path / "missing") == ""
