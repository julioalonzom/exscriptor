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


def test_tesseract_words_group_into_vision_line_boxes():
    tsv = ("level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
           "5\t1\t1\t1\t1\t1\t100\t200\t50\t20\t90\tnon\n"
           "5\t1\t1\t1\t1\t2\t160\t198\t80\t24\t90\tmediat\n"
           "5\t1\t1\t1\t2\t1\t100\t240\t60\t20\t90\tconceptus\n")
    lines = S.tesseract_lines(tsv, 1000, 1000)
    assert [l[0] for l in lines] == ["non mediat", "conceptus"]
    text, x, y, w, h = lines[0]
    assert (x, round(y, 3), w, h) == (0.1, 0.778, 0.14, 0.024)  # origin bottom-left, as Vision


def test_a_misreading_becomes_a_site_found_by_its_context(tmp_path):
    # Hurtado 1624 (p3-007): the worker cropped the OCR word nearest the form
    # and read other lines (amatu -> "ab"); a site is found by its context.
    page = tmp_path / "pg-085.md"
    page.write_text("**35.** Sed distinguo: quando inter supremum Subiectum rationem, non mediar conceptus differentiae, "
                    "et consequenter neque species.\n")
    report = {"gates": {"misreadings": {"findings": [
        "mediar: once in the batch, one letter from 'mediat' (600 in the corpus): a likely misreading."],
        "waived": [{"finding": "nusqua: once in the batch, one letter from 'nusquam' (900 in the corpus): x",
                    "reason": "r"}, {"finding": "svbiectum: once in the batch, one letter from 'subiectum' (9 in the corpus): x",
                    "reason": "r"}]}}}
    rows = S.misreading_sites(report, [page], columns=2)
    assert [(r["a"], r["b"], r["key"], r["kind"]) for r in rows] == [("mediar", "mediat", "pg-085-c1", "misreading")]
    assert rows[0]["context"] == "quando inter supremum Subiectum rationem, non […] conceptus differentiae, et consequenter neque species."
    boxes = {"pg-085-c1": [["Sed diftinguo: quando inter fupremum", 0, .6, 1, .02],
                           ["rationem, non mediat conceptus differentiæ, &", 0, .5, 1, .02],
                           ["conſequenter neque ſpecies.", 0, .4, 1, .02]], "pg-085-c2": [["alia", 0, .5, 1, .02]],
             "pg-087-c1": [["quando inter fupremum Subiectum rationem, non mediat conceptus differentiæ, & conſequenter",
                            0, .5, 1, .02]]}  # the same sentence on another page: never the site's
    assert S.locate(rows[0], boxes, sorted(boxes))[0] == "pg-085-c1"


def test_a_witness_disagreement_is_a_site_at_its_own_spot(tmp_path):
    # Hurtado p3-018: 'sit' was looked up by itself and read at its first occurrence.
    import exscriptor.shared as S
    (tmp_path / "w").mkdir()
    page = tmp_path / "pg-064.md"
    page.write_text("Cum enim obiecti ſit multiplex. *Nihil* colligitur, nec ſit abſolutè ſyllogiſmus "
                    "ex illis.^[Editor's note: x.]\n<!-- notes: none -->\n")
    (tmp_path / "w" / "pg-064.md").write_text("Cum enim obiecti sit multiplex. Nihil colligitur, nec fit absolutè syllogismus ex illis.")
    rows = S.witness_sites([page], tmp_path / "w")
    assert [(r["a"], r["b"]) for r in rows] == [("ſit", "fit")]
    assert rows[0]["context"] == "obiecti ſit multiplex. *Nihil* colligitur, nec […] abſolutè ſyllogiſmus ex illis."


def test_a_doubt_mark_is_a_site_at_its_own_spot(tmp_path):
    # Pilot 4: the corrector marks what the scan would not settle; all go to the site reader at the end.
    page = tmp_path / "pg-015.md"
    page.write_text("Cum enim authore Dionyſio bonum ſuapte ⟦natura?⟧ ſui ſit ipſius diffuſiuum, duas "
                    "Deus^[⟦M⟧ *Dionyſ.*] ⟦ſubſtãtias?⟧ ſui capaces ſtatuit.\n<!-- notes: uncertainties: 2 -->\n")
    rows = S.doubt_sites([page], columns=2)
    assert [(r["a"], r["kind"], r["key"]) for r in rows] == [("natura", "doubt", "pg-015-c1"), ("ſubſtãtias", "doubt", "pg-015-c1")]
    assert rows[0]["context"] == "Cum enim authore Dionyſio bonum ſuapte […] ſui ſit ipſius diffuſiuum, duas Deus"
    assert rows[1]["context"] == "ſui ſit ipſius diffuſiuum, duas Deus […] ſui capaces ſtatuit."


def test_ocr_page_cache_binds_image_and_settings(tmp_path):
    from exscriptor import shared
    image = tmp_path / 'pg-001.jpg'
    image.write_bytes(b'original scan')
    cache = tmp_path / 'cache'
    options = {'engine': 'tesseract', 'version': 'v1', 'columns': 2, 'language': 'la'}
    data = {'texts': {'pg-001-c1': 'test'}, 'boxes': {'pg-001-c1': []}}
    assert shared.read_ocr_cache(cache, image, options) is None
    shared.write_ocr_cache(cache, image, options, data)
    assert shared.read_ocr_cache(cache, image, options) == data
    assert shared.read_ocr_cache(cache, image, {**options, 'language': 'en'}) is None
    image.write_bytes(b'changed scan')
    assert shared.read_ocr_cache(cache, image, options) is None


def test_ocr_cache_is_shared_across_work_tmp_outputs(tmp_path):
    from exscriptor import shared
    tmp = tmp_path / 'works' / 'example' / 'tmp'
    assert shared.default_ocr_cache(tmp / 'longs' / 'ocr.json') == tmp / '.ocr-cache'
    assert shared.default_ocr_cache(tmp / 'misreadings' / 'ocr.json') == tmp / '.ocr-cache'
    assert shared.default_ocr_cache(tmp_path / 'ocr.json') == tmp_path / '.ocr-cache'
