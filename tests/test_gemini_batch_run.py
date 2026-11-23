
from pathlib import Path
import json

from exscriptor.gemini_batch_run import make_config, make_request


def test_make_config_default(tmp_path):
    cfg = make_config()
    assert cfg["temperature"] == 0
    assert "mediaResolution" not in cfg
    assert "thinkingConfig" not in cfg


def test_make_config_knobs():
    cfg = make_config(resolution="high", thinking="minimal")
    assert cfg["mediaResolution"] == "MEDIA_RESOLUTION_HIGH"
    assert cfg["thinkingConfig"] == {"thinkingLevel": "minimal"}


def test_make_request_uses_prompt_and_key(tmp_path):
    img = tmp_path / "pg-007.jpg"
    img.write_bytes(b"\xff\xd8\xffjpeg")
    req = make_request(7, tmp_path, "TRANSCRIBE THIS")
    assert "metadata" not in req
    req = make_request(7, tmp_path, "TRANSCRIBE THIS", key=True)
    assert req["metadata"]["key"] == "pg-007"
    inner = req["request"]
    parts = inner["contents"][0]["parts"]
    assert parts[0]["text"] == "TRANSCRIBE THIS"
    assert parts[1]["inline_data"]["mime_type"] == "image/jpeg"


def test_submitting_pages_requires_an_explicit_model(tmp_path, monkeypatch):
    """A paid route must never run on a default model (AGENTS.md, Money)."""
    from typer.testing import CliRunner
    from exscriptor import gemini_batch_run as g

    def no_network(*a, **k):
        raise AssertionError("must refuse before any API call")
    monkeypatch.setattr(g, "call", no_network)
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("transcribe")
    result = CliRunner().invoke(g.app, [
        "--images", str(tmp_path), "--out", str(tmp_path / "out"),
        "--jobs", str(tmp_path / "jobs.json"), "--prompt-file", str(prompt),
        "--pages", "1-2"])
    assert result.exit_code != 0
    assert "--model" in result.output


def test_module_carries_no_default_model():
    from exscriptor import gemini_batch_run as g
    assert not hasattr(g, "MODEL")


def test_thinking_off_is_a_zero_budget():
    """Legacy models can still request a zero thinking budget."""
    assert make_config(thinking="off")["thinkingConfig"] == {"thinkingBudget": 0}


def test_gemini_38_refuses_unsupported_off_and_minimal():
    import pytest
    for level in (None, "off", "minimal"):
        with pytest.raises(ValueError, match="3.8.*low"):
            make_config(thinking=level, model="models/gemini-3.8-flash")
    assert make_config(thinking="low", model="models/gemini-3.8-flash")["thinkingConfig"] == {"thinkingLevel": "low"}


def test_gemini_38_page_submission_refuses_off_before_network(tmp_path, monkeypatch):
    import pytest
    from exscriptor import gemini_batch_run as g
    monkeypatch.setattr(g, "call", lambda *a, **k: pytest.fail("must refuse before network"))
    with pytest.raises(ValueError, match="3.8.*low"):
        g.submit(tmp_path, tmp_path, [1], 1, tmp_path / "jobs.json", "read", thinking="off",
                 model="models/gemini-3.8-flash")


def test_gemini_38_page_submission_requires_explicit_output_cap(tmp_path, monkeypatch):
    import pytest
    from exscriptor import gemini_batch_run as g
    monkeypatch.setattr(g, "call", lambda *a, **k: pytest.fail("must refuse before network"))
    with pytest.raises(ValueError, match="output.*cap"):
        g.submit(tmp_path, tmp_path, [1], 1, tmp_path / "jobs.json", "read", thinking="low",
                 model="models/gemini-3.8-flash")


def test_gemini_38_page_submission_sends_explicit_cap(tmp_path, monkeypatch):
    from exscriptor import gemini_batch_run as g
    (tmp_path / "pg-001.jpg").write_bytes(b"jpeg")
    sent = []
    monkeypatch.setattr(g, "call", lambda path, payload=None, **kwargs: sent.append(payload) or {
        "name": "batches/1", "metadata": {"state": "BATCH_STATE_PENDING"}})
    monkeypatch.setattr(g.time, "sleep", lambda *a: None)
    g.submit(tmp_path, tmp_path, [1], 1, tmp_path / "jobs.json", "read", thinking="low",
             model="models/gemini-3.8-flash", max_output_tokens=4096)
    config = sent[0]["batch"]["input_config"]["requests"]["requests"][0]["request"]["generationConfig"]
    assert config["thinkingConfig"] == {"thinkingLevel": "low"}
    assert config["maxOutputTokens"] == 4096


def _job_status(items):
    return {"response": {"inlinedResponses": {"inlinedResponses": items}}}


def _item(page, text, finish="STOP"):
    return {"key": f"pg-{page:03d}", "response": {
        "candidates": [{"content": {"parts": [{"text": text}]}, "finishReason": finish}],
        "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 5}}}


def test_harvest_rejects_a_page_that_did_not_finish(tmp_path):
    """A page cut by the token cap or a recitation block is never written as a page file."""
    from exscriptor.gemini_batch_run import harvest
    job = {"name": "batches/x", "pages": [1, 2], "first_page": 1}
    harvest(job, _job_status([_item(1, "whole page"), _item(2, "half a pa", "MAX_TOKENS")]), tmp_path)
    assert (tmp_path / "pg-001.md").read_text() == "whole page\n"
    assert not (tmp_path / "pg-002.md").exists()
    assert "MAX_TOKENS" in (tmp_path / "rejected" / "pg-002.md").read_text()
    usage = [json.loads(l) for l in (tmp_path / "usage.jsonl").read_text().splitlines()]
    assert [u["finish"] for u in usage] == ["STOP", "MAX_TOKENS"]


def test_a_rejected_page_is_submitted_again(tmp_path, monkeypatch):
    """Resubmission follows the page files, not the job list: a page with no file goes out again."""
    from exscriptor import gemini_batch_run as g
    (tmp_path / "pg-001.jpg").write_bytes(b"\xff\xd8\xffjpeg")
    (tmp_path / "pg-002.jpg").write_bytes(b"\xff\xd8\xffjpeg")
    out = tmp_path / "out"; out.mkdir()
    (out / "pg-001.md").write_text("done\n")
    jobs = tmp_path / "jobs.json"
    jobs.write_text(json.dumps([{"name": "batches/old", "pages": [1, 2], "first_page": 1,
                                 "state": "BATCH_STATE_SUCCEEDED", "harvested": True}]))
    sent = []
    monkeypatch.setattr(g, "call", lambda path, payload=None, **k: sent.append(payload) or
                        {"name": "batches/new", "metadata": {"state": "PENDING"}})
    monkeypatch.setattr(g.time, "sleep", lambda s: None)
    g.submit(out, tmp_path, [1, 2], 15, jobs, "p", model="models/m")
    keys = [r["metadata"]["key"] for r in sent[0]["batch"]["input_config"]["requests"]["requests"]]
    assert keys == ["pg-002"]
