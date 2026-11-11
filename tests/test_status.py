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


def test_translation_parity_is_checked_as_units_land(tmp_path):
    (tmp_path / "work.json").write_text(json.dumps(
        {"track": "modern", "pages": {"first": 1, "last": 1}, "languages": ["la", "en"]}))
    (tmp_path / "assembled").mkdir()
    (tmp_path / "translation-en").mkdir()
    (tmp_path / "assembled" / "a.md").write_text("Verbum.^[Nota.]\n\nAlterum.")
    (tmp_path / "assembled" / "b.md").write_text("Tertium.")
    (tmp_path / "translation-en" / "a.md").write_text("Word.\n\nOther.")
    st = status.compute(tmp_path)
    assert st["translation-en"]["parity"] == ["a (footnotes differ: en=0, la=1)"]
    step = next(s for s in st["steps"] if s["step"].startswith("parity en"))
    assert not step["done"] and "a (footnotes" in step["step"]
    (tmp_path / "translation-en" / "a.md").write_text("Word.^[Note.]\n\nOther.")
    assert status.compute(tmp_path)["translation-en"]["parity"] == []


def test_assembly_paths_recorded_inside_the_work_dir(tmp_path, monkeypatch):
    import hashlib
    (tmp_path / "work.json").write_text(json.dumps(
        {"track": "modern", "pages": {"first": 1, "last": 1}, "languages": ["la"]}))
    (tmp_path / "transcription").mkdir()
    (tmp_path / "assembled").mkdir()
    page = tmp_path / "transcription" / "pg-001.md"
    page.write_text("Textus.")
    (tmp_path / "assembled" / "ASSEMBLY.json").write_text(json.dumps({"sections": {}, "pages": [
        {"name": "pg-001", "path": "transcription/pg-001.md",
         "sha256": hashlib.sha256(page.read_bytes()).hexdigest()}]}))
    monkeypatch.chdir(tmp_path.parent)
    assert status.compute(tmp_path)["assembly"]["stale_pages"] == []


def test_declared_page_files_always_expand(tmp_path):
    """Whoever read the pages, a declared work goes diplomatic -> expand ->
    edition, and the editor's doubts (pending, long s) gate the edition."""
    (tmp_path / "work.json").write_text(json.dumps(
        {"page_files": {"contract": "diplomatic-v1", "print": "modern", "dir": "diplomatic"},
         "pages": {"first": 1, "last": 1}, "languages": ["la"], "scouted_in": "SCOUT.md"}))
    (tmp_path / "diplomatic").mkdir()
    (tmp_path / "diplomatic" / "pg-001.md").write_text("Textus.")
    assert status.compute(tmp_path)["next"].startswith("expand")
    (tmp_path / "edition").mkdir()
    (tmp_path / "edition" / "pg-001.md").write_text("Textus.")
    (tmp_path / "pending.tsv").write_text("page\ttoken\toccurrence\tstatus\tcandidates\n")
    (tmp_path / "long-s.tsv").write_text("token\tcount\ts_reading\ts_count\tkind\nfit\t1\tsit\t9\tcontext\n")
    assert status.compute(tmp_path)["next"].startswith("expand")
    (tmp_path / "long-s.tsv").write_text("token\tcount\ts_reading\ts_count\tkind\n")
    assert status.compute(tmp_path)["next"].startswith("assemble")
    (tmp_path / "work.json").write_text(json.dumps(
        {"page_files": {"contract": "diplomatic-v1", "print": "old", "dir": "diplomatic"},
         "pages": {"first": 1, "last": 1}, "languages": ["la"], "scouted_in": "SCOUT.md"}))
    assert "abbreviations.tsv" in status.compute(tmp_path)["next"]


def test_declared_active_version_does_not_reopen_older_drafts(tmp_path):
    (tmp_path / 'work.json').write_text(json.dumps({'mode':'translate-only','languages':['la'],
        'manifest': {'batch_slug':'book-v3'}}))
    (tmp_path / 'SCOUT.md').write_text('x')
    (tmp_path / 'structure.json').write_text('{}')
    (tmp_path / 'manifests').mkdir()
    for stem in ('book-v1','book-v2','book-v3','other-v1'):
        (tmp_path / 'manifests' / f'{stem}.json').write_text('{}')
    st = status.compute(tmp_path)
    stage = [s['step'] for s in st['steps'] if s['step'].startswith('stage ')]
    assert sorted(stage) == sorted(['stage book-v3.json (submit wrapper)', 'stage other-v1.json (submit wrapper)'])
    assert len(st['manifests']) == 4


def test_pending_batch_waits_for_approval(tmp_path):
    import hashlib
    (tmp_path / 'work.json').write_text(json.dumps({'mode':'translate-only','languages':['la'], 'manifest':{'batch_slug':'book-v1'}}))
    (tmp_path / 'SCOUT.md').write_text('x')
    (tmp_path / 'structure.json').write_text('{}')
    (tmp_path / 'manifests').mkdir()
    p=tmp_path / 'manifests/book-v1.json'
    p.write_text('{}')
    (tmp_path / 'manifests/book-v1.preflight.json').write_text(json.dumps({'passed':True,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}))
    (tmp_path / 'staged.jsonl').write_text(json.dumps({'status':'pending','batch_id':880,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})+'\n')
    assert 'await approval' in status.compute(tmp_path)['next']


def test_cleanup_is_named_only_after_approval_and_spares_the_page_files(tmp_path):
    import hashlib
    (tmp_path / 'work.json').write_text(json.dumps({'mode': 'translate-only', 'languages': ['la']}))
    (tmp_path / 'SCOUT.md').write_text('x')
    (tmp_path / 'structure.json').write_text('{}')
    (tmp_path / 'manifests').mkdir()
    m = tmp_path / 'manifests/book.json'
    m.write_text('{}')
    sha = hashlib.sha256(m.read_bytes()).hexdigest()
    (tmp_path / 'manifests/book.preflight.json').write_text(json.dumps({'passed': True, 'sha256': sha}))
    for d in ('pages', 'tmp', 'diplomatic'):
        (tmp_path / d).mkdir()
    (tmp_path / 'pages/pg-001.png').write_bytes(b'x' * 6_000_000)
    (tmp_path / 'tmp/notes.json').write_bytes(b'x' * 6_000_000)
    (tmp_path / 'diplomatic/pg-001.png').write_bytes(b'x' * 50_000_000)

    def staged(state):
        (tmp_path / 'staged.jsonl').write_text(json.dumps({'status': state, 'batch_id': 1, 'sha256': sha}) + '\n')
        return status.compute(tmp_path)

    for state in ('pending', 'rejected'):
        assert 'free' not in staged(state)['next'], state
    st = staged('approved')
    assert st['regenerable_gb'] == 0.01   # pages/ + tmp/ = 12 MB; diplomatic/ is not counted
    assert st['next'] == ('verify live, close out (KB report), then free 0.01 GB: pages/ and tmp/ are'
                          ' rebuilt from the source scans, if you keep them')
