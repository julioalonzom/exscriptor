
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
    assert "key" not in req
    req = make_request(7, tmp_path, "TRANSCRIBE THIS", key=True)
    assert req["key"] == "pg-007"
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
