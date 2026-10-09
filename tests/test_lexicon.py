import json
from collections import Counter
from pathlib import Path

from exscriptor import lexicon as lx

LEX = Counter({"tamen": 41400, "tamem": 2, "non": 274477, "nom": 280, "concursum": 50,
               "numquam": 999, "nunquam": 2507, "voluntas": 900, "ulterius": 611})


def test_unique_frequency_variant_none():
    assert lx.expand_nasal("cõcursum", LEX)["choice"] == "concursum"
    r = lx.expand_nasal("tamẽ", LEX)
    assert (r["status"], r["choice"]) == ("frequency", "tamen")  # word-final "means m" would ship tamem
    assert lx.expand_nasal("nõ", LEX)["choice"] == "non"
    assert lx.expand_nasal("nũquam", LEX)["status"] == "variant"
    assert lx.expand_nasal("tõpus", LEX)["status"] == "none"


def test_variant_broken_by_edition_habit_and_case_kept():
    r = lx.expand_nasal("Nũquam", LEX, prefer=Counter({"numquam": 5}))
    assert (r["status"], r["choice"]) == ("prefer", "Numquam")


def test_other_marks_are_not_guessed():
    assert lx.expand_nasal("ꝓcisam", LEX)["status"] == "other-marks"
    assert lx.nasal_candidates("plain") is None


def test_build_skips_marked_tokens_and_duplicate_texts():
    forms = lx.build(["Tamen nõ est.", "Tamen nõ est."])
    assert forms == Counter({"tamen": 1, "est": 1})


def test_oov_lists_misreads_not_marked_tokens():
    found = lx.oov(["voluntas viterius virtuofioris nõdum"], LEX)
    assert set(found) == {"viterius", "virtuofioris"}


def test_read_texts_from_manifest_with_exclude(tmp_path):
    m = {"works": [{"sections": [{"section_key": "a", "title": "T",
                                  "texts": [{"language": "la", "content": "verbum"}]}]}]}
    (tmp_path / "keep.json").write_text(json.dumps(m))
    (tmp_path / "skip-superseded.json").write_text(json.dumps(m))
    got = lx.read_texts([str(tmp_path / "*.json")], exclude=["*superseded*"])
    assert [t for _, t in got] == ["verbum"]


def test_print_forms_are_never_vocabulary():
    assert lx.build(["Qvibvs quibus maior major quòd"]) == Counter({"quibus": 1, "maior": 1})


def test_lexicon_built_from_the_work_under_examination_is_refused(tmp_path):
    work, other = tmp_path / "works" / "w", tmp_path / "works" / "other"
    for d in (work / "manifests", other / "manifests"):
        d.mkdir(parents=True)
    (work / "manifests" / "w-v1.json").write_text("{}")
    (other / "manifests" / "o.md").write_text("verbum")
    (work / "manifests" / "w.md").write_text("virtuofioris")
    lex = tmp_path / "lex.json"
    texts = lx.read_texts([str(tmp_path / "works/*/manifests/*.md")])
    lx.save(lx.build([t for _, t in texts]), lex, len(texts), [str(Path(l).resolve()) for l, _ in texts])
    assert "rebuild it with --exclude" in lx.contamination(lex, work)
    assert lx.contamination(lex, other.parent / "third") is None
    assert lx.default_work_dir(str(work / "manifests" / "w-v1.json")) == work.resolve()
    lex.write_text(json.dumps({"forms": {}}))  # an old build records no sources
    assert "does not record its sources" in lx.contamination(lex, work)


def test_build_records_manifest_files_and_excludes(tmp_path):
    from typer.testing import CliRunner
    m = {"works": [{"sections": [{"section_key": "a", "title": "T",
                                  "texts": [{"language": "la", "content": "verbum"}]}]}]}
    (tmp_path / "a.json").write_text(json.dumps(m))
    out = tmp_path / "lex.json"
    r = CliRunner().invoke(lx.app, ["build", str(tmp_path / "*.json"), "--out", str(out), "--exclude", "*superseded*"])
    assert r.exit_code == 0, r.output
    data = json.loads(out.read_text())
    assert data["files"] == [str((tmp_path / "a.json").resolve())] and data["exclude"] == ["*superseded*"]
