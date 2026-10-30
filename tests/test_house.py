import json

import pytest

from exscriptor import expand as ex
from exscriptor import house
from exscriptor import preflight as pf

MAP = """form\tedition\treason
charit\tcarit\tfalse h
caeter\tceter\tfalse ae
coeter\tceter\tfalse oe
coetern\tcoetern\tco-aeternus is genuine
quum$\tcum\tpseudo-classical
Sylvi\tSylvi\tthe name Sylvius
sylv\tsilv\tfalse y
intellig\tintellig\tscholastic form, kept (CT)
"""


@pytest.fixture
def rows(tmp_path):
    (tmp_path / house.MAP_NAME).write_text(MAP, encoding="utf-8")
    return house.read_map(tmp_path / house.MAP_NAME)


def test_respell_prefix_case_keep_and_whole_word(rows):
    got = {w: (house.respell(w, rows) or (w,))[0] for w in
           ["Charitas", "CAETERUM", "coeteris", "coeternus", "quum", "quumque", "Sylvius",
            "sylvis", "Sylvae", "intelligere", "deus"]}
    assert got == {"Charitas": "Caritas", "CAETERUM": "CETERUM", "coeteris": "ceteris",
                   "coeternus": "coeternus", "quum": "cum", "quumque": "quumque",
                   "Sylvius": "Sylvius", "sylvis": "silvis", "Sylvae": "Silvae",
                   "intelligere": "intelligere", "deus": "deus"}


def test_map_refuses_rows_without_reason_or_twice(tmp_path):
    p = tmp_path / house.MAP_NAME
    p.write_text("form\tedition\treason\ncharit\tcarit\t\n", encoding="utf-8")
    with pytest.raises(ValueError, match="reason"):
        house.read_map(p)
    p.write_text("form\tedition\treason\ncharit\tcarit\th\nCharit\tcarit\th\ncharit\tcarit\tx\n", encoding="utf-8")
    with pytest.raises(ValueError, match="twice"):
        house.read_map(p)


def test_expand_applies_map_and_spacing_but_not_inside_editors_notes(rows):
    text = "Charitas est ; caetera quum sint :^[Editor's note: the print reads charitas.]"
    r = ex.expand_text(text, "p001", rules=[], decisions=[], lexicon=None, spelling=rows)
    assert r.text == "Caritas est; cetera cum sint:^[Editor's note: the print reads charitas.]"
    methods = {m for _, _, m, _ in r.changes}
    assert {"spelling", "rule"} <= methods


def test_expand_leaves_allow_file_tokens(rows):
    r = ex.expand_text("Charitas", "p001", rules=[], decisions=[], lexicon=None,
                       spelling=rows, keep={"Charitas"})
    assert r.text == "Charitas"


def test_spacing_keeps_markdown_tables_and_ellipses():
    t = "| a | b |\n| :--- | ---: |\nsic . . . non"
    assert house.fix_spacing(t) == (t, 0)
    assert house.fix_spacing("est : sed , non ?") == ("est: sed, non?", 3)


def test_english_quotes_nesting_and_apostrophes():
    t = "He says « the Lord’s word « fiat » is true » and the Fathers’ reading."
    assert house.english_quotes(t) == "He says “the Lord’s word ‘fiat’ is true” and the Fathers’ reading."


def test_punctuation_rows_may_move_marks_or_case_never_letters(tmp_path):
    p = tmp_path / "punctuation.tsv"
    head = "page\tfind\toccurrence\treplace\trule\tevidence\n"
    p.write_text(head + "p001\tdicendum, quod\t1\tdicendum quod\tdaril-quod\tdeclarative\n"
                        "p001\tTheologus\t*\ttheologus\tcase-common\tcommon noun\n", encoding="utf-8")
    rows = house.read_punctuation(p)
    text, applied, stale = house.apply_punctuation("Theologus: dicendum, quod sic.", "p001", rows)
    assert text == "theologus: dicendum quod sic." and len(applied) == 2 and not stale
    _, _, stale = house.apply_punctuation("nihil", "p001", rows)
    assert len(stale) == 2
    p.write_text(head + "p001\tdicendum, quod\t1\tdicendum, quia\tdaril-quod\tx\n", encoding="utf-8")
    with pytest.raises(ValueError, match="changed a letter"):
        house.read_punctuation(p)
    p.write_text(head + "p001\tdicendum, quod\t1\tDicendum quod\tdaril-quod\tx\n", encoding="utf-8")
    with pytest.raises(ValueError, match="changed a letter or its case"):
        house.read_punctuation(p)
    p.write_text(head + "p001\ta, b\t1\ta b\tmy-taste\tx\n", encoding="utf-8")
    with pytest.raises(ValueError, match="closed list"):
        house.read_punctuation(p)


def test_preflight_gates_spelling_and_quotes(tmp_path):
    (tmp_path / house.MAP_NAME).write_text(MAP, encoding="utf-8")
    wd = tmp_path / "works" / "w"
    (wd / "manifests").mkdir(parents=True)
    m = {"work": {"slug": "w", "original_language": "la", "sections": [{
        "section_key": "s1", "title": "Prooemium",
        "texts": [{"language": "la", "role": "source", "content": "Charitas est ; sed non."},
                  {"language": "en", "role": "translation", "content": "Love « is »; but not."}]}]}}
    mp = wd / "manifests" / "m.json"
    mp.write_text(json.dumps(m), encoding="utf-8")
    rep = pf.run(mp, work_dir=wd)
    assert not rep["gates"]["spelling"]["passed"]
    assert any("Charitas->Caritas" in f for f in rep["gates"]["spelling"]["findings"])
    assert any("before a stop" in f for f in rep["gates"]["spelling"]["findings"])
    assert not rep["gates"]["quotes"]["passed"]
    assert rep["info"]["spelling-map"]["sha"]


def test_seam_fragments_keep_the_halves_a_page_break_splits(tmp_path):
    """simi- + liter is one word: respelling the half that a rule matches
    (liter -> litter) would assemble similitter."""
    (tmp_path / house.MAP_NAME).write_text(MAP + "liter\tlitter\tclassicized\n", encoding="utf-8")
    pages = tmp_path / "transcription"
    pages.mkdir()
    a = pages / "p001.md"
    b = pages / "p002.md"
    a.write_text("ergo simi-\n\n<!-- notes: catchword: liter; joins-next: hyphen -->\n", encoding="utf-8")
    b.write_text("liter cum reprobis, et charitas.\n\n<!-- notes: joins-next: space -->\n", encoding="utf-8")
    kept = house.seam_fragments([a, b])
    assert kept[a] == {"simi"} and kept[b] == {"liter"}
    assert not any(v for v in house.seam_fragments([a]).values() if v != {"simi"})
    # the halves survive `apply`, the whole word inside the line does not
    from typer.testing import CliRunner
    runner = CliRunner()
    result = runner.invoke(house.app, ["apply", str(pages / "p0*.md")])
    assert result.exit_code == 0, result.output
    assert b.read_text().startswith("liter cum reprobis, et caritas.")
    assert a.read_text().startswith("ergo simi-")


def test_expand_decides_a_page_break_word_on_the_joined_word(rows, tmp_path):
    rows2 = rows + [house.Row("liter", "litter", False, False, "test")]
    rows2 = sorted(rows2, key=lambda r: (-len(r.form), not r.whole))
    a = ex.expand_text("sed simi-", "p1", rules=[], decisions=[], lexicon=None, spelling=rows2,
                       next_head="liter")
    b = ex.expand_text("liter dicit, liter", "p2", rules=[], decisions=[], lexicon=None,
                       spelling=rows2, prev_tail="simi")
    assert a.text == "sed simi-" and b.text.startswith("liter dicit")
    c = ex.expand_text("Charitas et cha-<!-- notes -->", "p1", rules=[], decisions=[], lexicon=None,
                       spelling=rows, next_head="ritas")
    assert c.text == "Caritas et ca-<!-- notes -->"


def test_rekey_carries_only_pairs_changed_by_the_house_rules(rows):
    from exscriptor import alignment as al
    old = {"s": ("Charitas est .\n\nSed alia.", "Love « is ».\n\nBut other.")}
    new = {"s": ("Caritas est.\n\nSed aliud.", "Love “is”.\n\nBut other.")}
    rep = {"sections": {"s": {"flags": [
        {"index": 1, "disposition": {"verdict": "aligned", "note": "one two three four five six"}},
        {"index": 2, "disposition": {"verdict": "aligned", "note": "six five four three two one"}}]}}}
    carried, unread = al.rekey(old, new, rep, rows)
    assert list(carried) == [al.pair_key("s", 1, "Caritas est.", "Love “is”.")]
    assert unread == ["s#2: changed beyond the house rules"]
