import zipfile
from pathlib import Path

from exscriptor import supplied
from exscriptor.supplied import diff, read, read_docx, read_html

DOC = """<?xml version="1.0"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:body>
<w:p><w:r><w:t>Version of June 2020. Boilerplate.</w:t></w:r></w:p>
<w:p><w:r><w:t>in subsiste</w:t></w:r><w:r><w:t>ndo nam omnis ratio</w:t></w:r></w:p>
<w:p><w:r><w:rPr><w:i/></w:rPr><w:t>Solvitur obiectio.</w:t></w:r></w:p>
<w:p><w:r><w:t>quodam here</w:t></w:r><w:r><w:footnoteReference w:id="1"/></w:r></w:p>
</w:body></w:document>"""

FOOT = """<?xml version="1.0"?>
<w:footnotes xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:footnote w:id="-1"><w:p><w:r><w:t>separator</w:t></w:r></w:p></w:footnote>
<w:footnote w:id="1"><w:p><w:r><w:t>Vivès has immortali.</w:t></w:r></w:p></w:footnote>
</w:footnotes>"""

HTML = """<html><head><meta http-equiv="Content-Type" content="text/html; charset=UTF-8"></head>
<body>
<p><a href="../index.html">Home</a></p>
<p>DISPUTATIO I</p>
<p>in subsistendo nam omnis ratio</p>
<p><i>Solvitur obiectio.</i></p>
<p>quoddam here<a href="#sdfootnote1"><sup>1</sup></a></p>
<div id="sdfootnote1"><p class="sdfootnote"><a class="sdfootnotesym" href="#sdfootnote1anc">1</a> Vivès has immortali.</p></div>
</body></html>"""


def _docx(tmp: Path, doc: str = DOC, foot: str | None = FOOT) -> Path:
    p = tmp / "a.docx"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("[Content_Types].xml", "<x/>")
        z.writestr("word/document.xml", doc)
        if foot:
            z.writestr("word/footnotes.xml", foot)
    return p


def test_read_docx_rejoins_run_split_words_and_reads_notes(tmp_path):
    blocks = read_docx(_docx(tmp_path))
    assert blocks[1].text == "in subsistendo nam omnis ratio", blocks[1].text
    assert blocks[2].words() == [("Solvitur", True), ("obiectio", True)]
    assert blocks[-1].note == 1 and blocks[-1].text.startswith("Vivès has")
    assert not any(b.text.startswith("separator") for b in blocks)


def test_read_html_drops_navigation_and_note_symbols(tmp_path):
    p = tmp_path / "b.html"
    p.write_text(HTML, encoding="utf-8")
    blocks = read_html(p)
    assert [b.text for b in blocks][0] == "DISPUTATIO I", [b.text for b in blocks]
    assert blocks[3].words()[-1] == ("here", False)  # the <sup>1</sup> marker
    assert blocks[-1].note == 1 and "immortali" in blocks[-1].text


def test_diff_classifies_word_span_and_only_sites(tmp_path):
    a = _docx(tmp_path)
    b = tmp_path / "b.html"
    b.write_text(HTML, encoding="utf-8")
    r = diff(a, b, drop=["Version of June"])
    got = {(s["kind"], s["a"], s["b"]) for s in r["sites"]}
    assert ("word", "quodam", "quoddam") in got, got        # the spell-check class
    assert ("b-block-only", "", "DISPUTATIO I") in got, got  # a heading A lacks
    assert not any(k == "word" and x == y for k, x, y in got), got
    assert not any(k == "span" and x == y for k, x, y in got), got
    blocks = {s["id"]: (s["block_a"], s["block_b"]) for s in r["sites"]}
    assert (2, 3) in blocks.values(), blocks  # the paragraph pair, not a drift


def test_note_bodies_compare_without_their_own_number(tmp_path):
    a = _docx(tmp_path)
    b = tmp_path / "b.html"
    b.write_text(HTML, encoding="utf-8")
    r = diff(a, b, drop=["Version of June"])
    assert not any(s["note_a"] and s["note_a"] == s["note_b"]
                   for s in r["sites"]), "note bodies agree"


def test_invisible_characters_and_bracket_notes(tmp_path):
    p = tmp_path / "c.html"
    p.write_text("<html><body>"
                 "<p>ra&#173;tio and com&#173;munem and a&#160;nobreak</p>"
                 "<p>[4] essentiales, alit. essentialiter</p>"
                 "</body></html>", encoding="utf-8")
    blocks = read_html(p)
    assert blocks[0].words() == [("ratio", False), ("and", False), ("communem", False),
                                 ("and", False), ("a", False), ("nobreak", False)], blocks[0].words()
    assert blocks[1].note == 4 and blocks[1].text == "essentiales, alit. essentialiter"


def test_glue_reported_as_one_site(tmp_path):
    docx = DOC.replace("in subsiste</w:t></w:r><w:r><w:t>ndo", "amplius</w:t></w:r><w:r><w:t>declaretur")
    a = _docx(tmp_path, doc=docx)
    b = tmp_path / "b.html"
    b.write_text(HTML.replace("in subsistendo", "amplius declaretur"), encoding="utf-8")
    rows = [s for s in diff(a, b, drop=["Version of June"])["sites"]
            if s["kind"].startswith("glue")]
    assert rows and all(s["kind"] == "glue-a" for s in rows), rows
    assert ("amplius", "amplius") not in {(s["kind"], s["a"]) for s in rows}
    assert any(s["a"] == "ampliusdeclaretur" and s["b"] == "amplius declaretur" for s in rows), rows


def test_glue_merge_when_the_other_side_keeps_several_words(tmp_path):
    # A glued a pair; B has the remainder as two words, so the raw
    # concatenation does not match and only a space-blind compare finds it.
    docx = DOC.replace("in subsiste</w:t></w:r><w:r><w:t>ndo nam omnis",
                       "amplius</w:t></w:r><w:r><w:t>declaretur nos")
    a = _docx(tmp_path, doc=docx)
    b = tmp_path / "b.html"
    b.write_text(HTML.replace("in subsistendo nam omnis", "amplius declaretur nos"),
                 encoding="utf-8")
    rows = [s for s in diff(a, b, drop=["Version of June"])["sites"] if s["kind"].startswith("glue")]
    assert rows and rows[0]["kind"] == "glue-a", rows


def test_glue_run_of_a_whole_paragraph_is_one_site():
    # The spaces can go across many words at once; that is one event, and the
    # run must not be reported as a pile of word differences.
    from exscriptor.supplied import _merge_glue

    rows = [
        {"kind": "word", "a": "Inhacergo", "b": "In", "context": "c"},
        {"kind": "word", "a": "significationeconstat", "b": "hac", "context": "c"},
        {"kind": "b-only", "a": "", "b": "ergo significatione constat", "context": "c"},
    ]
    out = _merge_glue(rows)
    assert len(out) == 1 and out[0]["kind"] == "glue-a", out
    assert out[0]["a"] == "Inhacergo significationeconstat", out[0]["a"]
    assert out[0]["b"] == "In hac ergo significatione constat", out[0]["b"]

    # A real difference inside the run keeps it from merging.
    rows = [
        {"kind": "word", "a": "quidamuidentur", "b": "quidam", "context": "c"},
        {"kind": "b-only", "a": "", "b": "uidentur dicere ens non est", "context": "c"},
    ]
    assert [r["kind"] for r in _merge_glue(rows)] == ["word", "b-only"]

    # A glued pair the other way round is glue-b.
    rows = [
        {"kind": "word", "a": "quod", "b": "quodsit", "context": "c"},
        {"kind": "word", "a": "sit ens", "b": "ens", "context": "c"},
    ]
    out = _merge_glue(rows)
    assert len(out) == 1 and out[0]["kind"] == "glue-b", out


def test_numeral_notation_is_not_a_reading():
    from exscriptor.supplied import numeral
    assert numeral("VII") == 7 and numeral("7") == 7 and numeral("i.") == 1
    assert numeral("quod") is None and numeral("Cicero") is None
    assert numeral("IV") == 4 and numeral("MCMXC") == 1990


def test_numeral_class_in_diff(tmp_path):
    docx = DOC.replace("in subsiste</w:t></w:r><w:r><w:t>ndo nam omnis",
                       "sect.</w:t></w:r><w:r><w:t>V nam omnis")
    a = _docx(tmp_path, doc=docx)
    b = tmp_path / "b.html"
    b.write_text(HTML.replace("in subsistendo nam omnis", "sect. 5 nam omnis"),
                 encoding="utf-8")
    sites = diff(a, b, drop=["Version of June"])["sites"]
    kinds = [s["kind"] for s in sites]
    assert "numeral" in kinds, kinds
    num = [s for s in sites if s["kind"] == "numeral"]
    assert num[0]["a"] == "V" and num[0]["b"] == "5", num


def test_non_breaking_hyphen_is_a_character(tmp_path):
    # Dropping <w:noBreakHyphen/> turns 'I-II' into 'III': a different
    # reference, and a phantom site against the other witness.
    docx = DOC.replace("<w:p><w:r><w:t>quodam here</w:t></w:r>",
                       "<w:p><w:r><w:t>D. Thom., I</w:t></w:r><w:r><w:noBreakHyphen/></w:r>"
                       "<w:r><w:t>II, q. 57</w:t></w:r></w:p>"
                       "<w:p><w:r><w:t>quodam here</w:t></w:r>")
    a = _docx(tmp_path, doc=docx)
    text = " ".join(b.text for b in read(a))
    assert "D. Thom., I-II, q. 57" in text, text


def test_diff_ignoring_boilerplate_is_clean(tmp_path):
    a = _docx(tmp_path)
    b = tmp_path / "b.html"
    b.write_text(HTML, encoding="utf-8")
    r = diff(a, b, drop=["Version of June", "^Anmerkungen$"])
    assert all("Version" not in s["a"] for s in r["sites"])


def test_lost_space_split_into_two_rows_is_one_glue():
    """`etscientiae` against `et`, then a b-only `scientiæ`: one event."""
    rows = [{"kind": "word", "a": "etscientiae", "b": "et", "context": "x", "id": 1},
            {"kind": "b-only", "a": "", "b": "scientiæ", "context": "x", "id": 2}]
    out = supplied._merge_glue(rows)
    assert len(out) == 1, out
    assert out[0]["kind"] == "glue-a"
    assert out[0]["a"] == "etscientiae" and out[0]["b"] == "et scientiæ"


def test_a_shorter_word_is_not_a_glue():
    """`localiter` against `lo` + `aliter`: the other witness split the word."""
    rows = [{"kind": "word", "a": "localiter", "b": "lo", "context": "x", "id": 1},
            {"kind": "b-only", "a": "", "b": "aliter", "context": "x", "id": 2}]
    out = supplied._merge_glue(rows)
    assert [r["kind"] for r in out] == ["word", "b-only"], out


def test_a_dropped_citation_is_not_swallowed_as_a_lost_space():
    """`necessariametaphora` against `necessaria` + `6 metaphora`."""
    rows = [{"kind": "word", "a": "necessariametaphora", "b": "necessaria",
             "context": "x", "id": 1},
            {"kind": "b-only", "a": "", "b": "6 metaphora", "context": "x", "id": 2}]
    out = supplied._merge_glue(rows)
    assert [r["kind"] for r in out] == ["word", "b-only"], out
