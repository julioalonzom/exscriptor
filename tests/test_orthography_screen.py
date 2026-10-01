import json

from exscriptor.orthography_screen import char_category, failing, manifest_units, screen_text


def cats(text, **kw):
    return {k: dict(v) for k, v in screen_text(text, **kw).items()}


def test_nasal_bars_and_abbreviation_letters_fail():
    res = cats("nõ enim cõcursum est ꝓ quo, ⁊ alia; diuinę")
    assert res["abbrev-mark"] == {"nõ": 1, "cõcursum": 1, "ꝓ": 1, "⁊": 1, "diuinę": 1}


def test_combining_tilde_on_consonant_fails():
    assert "abbrev-mark" in cats("anteq̃ dicitur")


def test_clean_edition_latin_passes():
    assert cats("Respondeo dicendum quod veritas est in intellectu, ut aër et coöperatio.") == {}


def test_diaeresis_is_kept_but_print_accents_fail():
    res = cats("rebúsque aër Boëtius")
    assert res == {"accent": {"rebúsque": 1}}


def test_long_s_ligature_ampersand_j():
    res = cats("ſed quæ & eius ejus")
    assert set(res) == {"long-s", "ligature", "ampersand", "consonantal-j"}


def test_caps_v_and_qv_skip_roman_numerals():
    res = cats("PROBATVR QVOD VIA neqve LXV XIV VERVM")
    assert res["caps-v"] == {"PROBATVR": 1, "QVOD": 1, "VERVM": 1}
    assert res["qv"] == {"neqve": 1}


def test_enye_is_low_and_allow_list_works():
    res = screen_text("Peña dixit, Sà notat")
    assert set(res) == {"low-enye", "accent"}
    assert failing(screen_text("Peña dixit, Sà notat", allow={"Sà"})) == {}


def test_comments_and_link_targets_are_ignored():
    assert cats("verum <!-- notes: nõ --> [[S. Th.|summa-theologiae:pars.I/quaestio.2]]") == {}


def test_greek_accents_are_not_latin_accents():
    assert char_category("ά") is None and char_category("ῶ") is None


def test_manifest_titles_and_latin_texts_only():
    manifest = {"manifest": {"works": [{"sections": [
        {"section_key": "s1", "title": "QVAESTIO PRIMA",
         "texts": [{"language": "la", "content": "nõ est"},
                   {"language": "en", "content": "naïve & fine"}]}]}]}}
    units = dict(manifest_units(manifest))
    assert units == {"title:s1": "QVAESTIO PRIMA", "text:s1": "nõ est"}


def test_manifest_units_accepts_a_list_root():
    data = [{"section_key": "s", "title": "De Deo", "texts": [{"language": "la", "content": "Deus"}]}]
    assert dict(manifest_units(data)) == {"title:s": "De Deo", "text:s": "Deus"}


def test_editors_notes_in_english_are_not_screened():
    text = "verum est.^[3. Editor's note: the print reads [sic] *adjective* here.] Sed contra.^[4. Ioan. 1.]"
    assert cats(text) == {}
    assert "consonantal-j" in cats("verum.^[1. ejus loco]")


def test_titles_of_a_non_latin_work_are_skipped():
    m = {"works": [{"original_language": "en", "sections": [
        {"section_key": "s", "title": "The Judgment", "texts": [{"language": "en", "content": "x"}]}]}]}
    assert list(manifest_units(m)) == []


def test_titles_auto_follow_the_manifest_language():
    en_append = {"works": [{"import_mode": "append_texts", "sections": [
        {"section_key": "s", "title": "La evolución", "texts": [{"language": "en", "content": "x"}]}]}]}
    assert list(manifest_units(en_append)) == []
    titles_only = {"works": [{"sections": [{"section_key": "s", "title": "QVAESTIO"}]}]}
    assert list(manifest_units(titles_only)) == []
    assert list(manifest_units(titles_only, titles=True)) == [("title:s", "QVAESTIO")]


def test_allow_file_strips_reasons(tmp_path):
    from exscriptor.orthography_screen import read_allow_file
    f = tmp_path / "allow.txt"
    f.write_text("Sà   # Sánchez's siglum, as printed\n\n# comment only\nPère # French quotation\n")
    assert read_allow_file(f) == {"Sà", "Père"}
