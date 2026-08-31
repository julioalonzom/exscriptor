
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
