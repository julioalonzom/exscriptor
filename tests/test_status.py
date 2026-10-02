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


def test_declared_scouting_and_assembler(tmp_path):
    import os
    (tmp_path / "work.json").write_text(json.dumps(
        {"track": "modern", "pages": {"first": 1, "last": 1}, "languages": ["la"],
         "scouted_in": "README.md", "assembler": "assemble.py"}))
    (tmp_path / "transcription").mkdir()
    page = tmp_path / "transcription" / "pg-001.md"
    page.write_text("Textus.")
    st = status.compute(tmp_path)
    assert st["next"].startswith("assemble (assemble.py): stale")
    (tmp_path / "assembled").mkdir()
    (tmp_path / "assembled" / "q1.md").write_text("Textus.")
    os.utime(page, (1, 1))
    st = status.compute(tmp_path)
    assert st["steps"][0] == {"done": True, "step": "scout: in README.md"}
    assert st["next"] == "build the manifest"


def test_every_manifest_is_checked(tmp_path):
    (tmp_path / "work.json").write_text(json.dumps({"mode": "translate-only", "languages": ["la"]}))
    (tmp_path / "SCOUT.md").write_text("x")
    (tmp_path / "structure.json").write_text("{}")
    (tmp_path / "manifests").mkdir()
    for stem in ("a-v1", "b-v1"):
        (tmp_path / "manifests" / f"{stem}.json").write_text("{}")
    st = status.compute(tmp_path)
    assert sorted(m["name"] for m in st["manifests"]) == ["a-v1.json", "b-v1.json"]
    assert sum(s["step"].startswith("stage ") for s in st["steps"]) == 2
