import json

from exscriptor import status


def test_legacy_work(tmp_path):
    assert status.compute(tmp_path)["legacy"]


def test_steps_follow_the_files(tmp_path):
    (tmp_path / "work.json").write_text(json.dumps(
        {"track": "modern", "pages": {"first": 1, "last": 3}, "languages": ["la", "en"]}))
    st = status.compute(tmp_path)
    assert st["next"].startswith("scout")
    (tmp_path / "SCOUT.md").write_text("x")
    (tmp_path / "structure.json").write_text("{}")
    (tmp_path / "transcription").mkdir()
    for n in (1, 3):
        (tmp_path / "transcription" / f"pg-{n:03d}.md").write_text("Textus.")
    st = status.compute(tmp_path)
    assert st["pages"]["missing"] == "2" and st["next"].startswith("transcribe")
    (tmp_path / "transcription" / "pg-002.md").write_text("Textus.")
    assert status.compute(tmp_path)["next"].startswith("assemble")
