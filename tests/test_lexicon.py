import json
from collections import Counter

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
