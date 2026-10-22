from collections import Counter

from exscriptor import shared as S

WORDS = ("primo dicendum est quod forma substantialis non potest esse sine materia nisi divinitus "
         "conservetur quia omnis actio naturalis supponit subiectum in quo recipiatur et ideo "
         "agens creatum numquam producit formam sine materia praeexistente sed semper ex potentia "
         "materiae educit illam ut docet Aristoteles in libro physicorum").split()
LEX = Counter({S.norm(w): 500 for w in WORDS} | {"contractu": 300, "formae": 400, "formam": 400})


def ocr_of(words, per=12):
    return {f"pg-{i // per + 1:04d}-c1": " ".join(words[i:i + per]) for i in range(0, len(words), per)}


def run(text_words, ocr_words):
    stream, keys = S.ocr_stream(ocr_of(ocr_words))
    return S.screen("d1", " ".join(text_words), stream, keys, LEX)


def test_a_word_the_print_has_otherwise_is_a_site():
    ocr, text = list(WORDS), list(WORDS)
    text[20] = "contactu"
    ocr[20] = "contractu"
    rows = run(text, ocr)
    assert [(r["a"], r["b"], r["key"]) for r in rows] == [("contactu", "contractu", "pg-0002-c1")]
    assert rows[0]["context"].startswith("quia omnis actio naturalis supponit subiectum […] quo")


def test_ocr_confusions_and_spellings_are_not_sites():
    text, ocr = list(WORDS), list(WORDS)
    ocr[12] = "fonnam"  # rn/m, not in the lexicon anyway
    text[25] = "formam"
    ocr[25] = "forman"  # a final nasal under a tilde
    text[30] = "quamvis"
    ocr[30] = "quanuis"  # m before q/d is the edition's spelling
    assert run(text, ocr) == []


def test_long_s_folds_to_s():
    assert S.norm("ſubſtantia") == S.norm("fubftantia") == "substantia"
    assert S.norm("Divinitùs") == "diuinitus"


def test_select_keeps_rare_own_words_and_once_seen_pairs():
    rows = [{"a": "ilam", "b": "illam", "fa": 0, "fb": 900},
            {"a": "formam", "b": "formae", "fa": 400, "fb": 400},
            {"a": "formam", "b": "formae", "fa": 400, "fb": 400},  # the OCR's habit
            {"a": "dicitur", "b": "dicit", "fa": 900, "fb": 900},  # a truncation
            {"a": "materia", "b": "materiae", "fa": 900, "fb": 150},  # OCR word not common
            {"a": "potentia", "b": "potestas", "fa": 900, "fb": 900}]
    assert [r["a"] for r in S.select(rows)] == ["ilam", "potentia"]


def test_window_grows_until_unique_and_keeps_punctuation_and_capital():
    text = "Et ideo forma est. Unde forma, est actus; forma est."
    site = {"a": "forma,", "context": "est. Unde […] est actus; forma est."}
    assert S.window(text, site, "formae") == ("Unde forma, est", "Unde formae, est")
    assert S.window("a Forma b", {"a": "Forma", "context": "a […] b"}, "formae") == ("a Forma b", "a Formae b")
    assert S.window("x Forma y x Forma y", {"a": "Forma", "context": "x […] y"}, "formae") is None


def test_locate_finds_the_lines_in_a_neighbouring_key():
    boxes = {"pg-0001-c1": [["aliud nihil hic", 0, .9, 1, .02]],
             "pg-0001-c2": [["unde patet formam", 0, .8, 1, .02], ["substantialem esse actum", 0, .78, 1, .02],
                            ["primum materiae", 0, .76, 1, .02]]}
    site = {"key": "pg-0001-c1", "a": "formam", "context": "unde patet […] substantialem esse actum primum"}
    assert S.locate(site, boxes, sorted(boxes)) == ("pg-0001-c2", 0, 3)


def test_fold_for_packets_treats_spelling_as_the_same_reading():
    assert S._fold("praecipuè") == S._fold("precipue")
    assert S._fold("Summo") != S._fold("Sumo")


def test_a_dropped_tilde_is_recognised():
    assert S._tilde_drop("pertinent", "pertinet")
    assert S._tilde_drop("individuum", "indiuidui")
    assert S._tilde_drop("ordinantur", "ordinatur")
    assert not S._tilde_drop("pertinet", "pertinent")  # the edition lacks the nasal
    assert S._tilde_drop("Summo", "Sumo")  # sūmo
    assert not S._tilde_drop("formam", "forman")


def test_a_tilde_site_gets_a_close_crop(tmp_path):
    import pytest
    Image = pytest.importorskip("PIL.Image")
    Image.new("RGB", (400, 100), "white").save(tmp_path / "pg-0001.png")
    lines = tmp_path / "lines.json"
    lines.write_text('{"pg-0001-c2": [["alpha pertinent beta gamma", 0, 0.4, 1, 0.2]], "pg-0001-c1": []}')
    sites = tmp_path / "sites.jsonl"
    rows = [{"unit": "d1", "id": "s1", "key": "pg-0001-c2", "a": "pertinent", "b": "pertinet",
             "context": "alpha […] beta gamma"},
            {"unit": "d1", "id": "s2", "key": "pg-0001-c2", "a": "pertinent", "b": "pertinens",
             "context": "alpha […] beta gamma"}]
    sites.write_text("".join(__import__("json").dumps(r) + "\n" for r in rows))
    S.crop(sites, lines=lines, image=str(tmp_path / "{leaf}.png"), out_dir=tmp_path / "crops", pad=0)
    tilde, other = S._load_jsonl(sites)
    assert other["zoom"] is None
    zoom = Image.open(tilde["zoom"])
    assert zoom.width == 3 * 60  # 30% of one column of two, three times
