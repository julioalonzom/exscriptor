import json

from exscriptor.gemini_sites import harvest, make_site_request


def test_a_site_request_names_neither_form_and_carries_both_images(tmp_path):
    (tmp_path / "c.png").write_bytes(b"png")
    (tmp_path / "z.png").write_bytes(b"zoom")
    site = {"id": "m41", "a": "mediar", "b": "media", "context": "non […] conceptus",
            "crop": str(tmp_path / "c.png"), "zoom": str(tmp_path / "z.png")}
    req = make_site_request(site)
    parts = req["request"]["contents"][0]["parts"]
    assert req["metadata"]["key"] == "m41"
    assert "non […] conceptus" in parts[0]["text"]
    assert "mediar" not in parts[0]["text"] and "media" not in parts[0]["text"]
    assert [p["inline_data"]["mime_type"] for p in parts[1:]] == ["image/png", "image/png"]


def test_harvest_writes_one_reading_per_key(tmp_path):
    st = {"response": {"inlinedResponses": {"inlinedResponses": [
        {"metadata": {"key": "m41"}, "response": {"candidates": [{"content": {"parts": [
            {"text": json.dumps({"found": True, "word": "mediat", "printed_line": "x",
                                 "confidence": "high", "note": ""})}]}}]}},
        {"key": "m42", "response": {"candidates": [{"content": {"parts": [{"text": "not json"}]}}]}},
    ]}}}
    assert harvest(st, {"m41": {"unit": "pg-085", "a": "mediar"}}, tmp_path) == 2
    rows = [json.loads(l) for l in (tmp_path / "readings.jsonl").read_text().splitlines()]
    assert rows[0]["word"] == "mediat" and rows[0]["edition"] == "mediar"
    assert "error" in rows[1]
