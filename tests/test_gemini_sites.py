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
    assert make_site_request(site, thinking="low")["request"]["generationConfig"]["thinkingConfig"] == {"thinkingLevel": "low"}


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


def test_a_site_not_found_in_its_crop_is_resent_once_with_its_page(tmp_path, monkeypatch):
    # Hurtado p3-021: the OCR lost p. 35's lines, the crop held a look-alike line, and the
    # reader rightly said the passage was not there.
    import exscriptor.gemini_sites as G
    from PIL import Image
    (tmp_path / "c.png").write_bytes(b"img")
    Image.new("RGB", (4000, 6000), "white").save(tmp_path / "p.jpg")
    sites = [{"id": "w02", "unit": "pg-035", "a": "ſecúda", "context": "in prima, & […] propoſitione, & negatos",
              "crop": str(tmp_path / "c.png"), "page": str(tmp_path / "p.jpg")},
             {"id": "w03", "unit": "pg-064", "a": "hæc", "context": "Quia verò […] ſententia",
              "crop": str(tmp_path / "c.png"), "page": str(tmp_path / "p.jpg")}]
    out = tmp_path / "run"
    out.mkdir()
    (out / "readings.jsonl").write_text(
        json.dumps({"id": "w02", "found": False, "word": ""}) + "\n" + json.dumps({"id": "w03", "found": True, "word": "hęc"}) + "\n")
    sent = []
    monkeypatch.setattr(G, "call", lambda path, payload=None, method="GET": sent.append(payload) or {"name": "batches/1"})
    G.submit(sites, out, "models/m", 12)
    reqs = sent[0]["batch"]["input_config"]["requests"]["requests"]
    assert [q["metadata"]["key"] for q in reqs] == ["w02#page"]
    parts = reqs[0]["request"]["contents"][0]["parts"]
    assert "one whole page" in parts[0]["text"] and len(parts) == 2
    import base64, io
    assert Image.open(io.BytesIO(base64.b64decode(parts[1]["inline_data"]["data"]))).size == (2048, 3072)
    st = {"response": {"inlinedResponses": {"inlinedResponses": [{"metadata": {"key": "w02#page"}, "response": {
        "candidates": [{"content": {"parts": [{"text": json.dumps({"found": True, "word": "ſecũda"})}]}}]}}]}}}
    harvest(st, {s["id"]: s for s in sites}, out)
    last = json.loads((out / "readings.jsonl").read_text().splitlines()[-1])
    assert (last["id"], last["wide"], last["word"], last["unit"]) == ("w02", True, "ſecũda", "pg-035")
    (out / "jobs.json").write_text(json.dumps([{"name": "batches/1", "ids": ["w02#page"], "harvested": True}]))
    sent.clear()
    G.submit(sites, out, "models/m", 12)
    assert not sent  # read once wide: nothing left to send
