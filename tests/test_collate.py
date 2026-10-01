from collections import Counter

from exscriptor import collate as C


PAGE_A = """<<<THOMAS>>>
Sed contra est quod dicitur in III *Metaphys.*[*1]. Ut dicit Dionysius[*2] in libro[α].
<<<THOMAS-APPARATUS>>>
α) libro. – Om. A.
<<<THOMAS-MARGINALIA>>>
*1 Art. II.
*2 D. 115.
<<<CAIETANUS>>>
Secundo impugnat, posito quod esset materiales, probando.
"""

PAGE_B = """<<<THOMAS>>>
Sed contra est quod dicitur in III *Metaphys.*[*1]. Ut dicit Dionysius[*2] in libro.
<<<THOMAS-MARGINALIA>>>
*1 D. 115.
*2 Art. II.
<<<CAIETANUS>>>
Secundo impugnat, posito quod essent materiales, probando.
"""


def test_parse_blocks_open_only_and_end_markers():
    text = "<<<A>>>\nx\n<<<B>>>\ny\n<<<END B>>>\nz\n"
    names = [b[0] for b in C.parse_blocks(text)]
    assert names == ["A", "B"]
    assert C.parse_blocks("plain text\n") == [("BODY", 0, 11)]


def test_notes_spliced_at_anchor_across_an_apparatus_block():
    s = C.page_streams(PAGE_A, 20, {"THOMAS-APPARATUS"})
    norms = [t.norm for t in s["THOMAS"]]
    i = norms.index("⟨")
    assert norms[i:i + 4] == ["⟨", "art", "ii", "⟩"]
    assert "THOMAS-MARGINALIA" not in s  # consumed, not an orphan stream
    assert "α" not in norms and "libro" in norms


def test_swapped_notes_and_misread_word_are_sites():
    a = C.page_streams(PAGE_A, 20, {"THOMAS-APPARATUS"})
    b = C.page_streams(PAGE_B, 20, set())
    sites = C.collate_voice("THOMAS", a["THOMAS"], b["THOMAS"], [], None)
    assert len(sites) == 2  # each anchor's note differs
    assert {s["a"] for s in sites} == {"Art II", "D 115"}
    caj = C.collate_voice("CAIETANUS", a["CAIETANUS"], b["CAIETANUS"], [], None)
    assert [(s["a"], s["b"]) for s in caj] == [("esset", "essent")]
    span = caj[0]["a_span"]
    assert PAGE_A[span["start"]:span["end"]] == "esset"


def test_fold_ignores_case_ligatures_accents():
    assert C.fold("Quæcumque") == C.fold("quaecumque")
    assert C.fold("Cœlum") == "coelum"
    assert C.fold("à") == "a"


def _ocr(words, page=20):
    xml = "".join(f'<line><word xMin="{i*10}" yMin="100" xMax="{i*10+8}" yMax="110">{w}</word></line>'
                  for i, w in enumerate(words))
    return C.parse_bbox_xml(xml, page)


def test_ocr_hyphenation_rejoined_and_site_evidence():
    ocr = _ocr("Secundo impugnat , posito quod es- sent materiales, probando eandem".split())
    assert [t.norm for t in ocr][3:5] == ["quod", "essent"]
    a = C.page_streams(PAGE_A, 20, {"THOMAS-APPARATUS"})["CAIETANUS"]
    b = C.page_streams(PAGE_B, 20, set())["CAIETANUS"]
    (site,) = C.collate_voice("CAIETANUS", a, b, ocr, None)
    assert site["ocr"] == "essent" and site["ocr_agrees"] == "b"
    assert site["bbox"]["page"] == 20


def test_ocr_only_site_needs_lexicon_word():
    words = "unum duo tres quattuor quinque sex septem octo".split()
    a = [C.Tok(C.fold(w), w, 1, k * 10, k * 10 + len(w)) for k, w in enumerate(words)]
    a[4] = C.Tok("quinqve", "quinqve", 1, 40, 47)  # both readers share this misreading
    ocr = _ocr(words, page=1)
    lex = Counter({w: 5 for w in words})
    sites = C.collate_voice("BODY", a, list(a), ocr, lex)
    assert [(s["kind"], s["a"], s["ocr"]) for s in sites] == [("ocr-only", "quinqve", "quinque")]
    assert C.collate_voice("BODY", a, list(a), ocr, Counter()) == []


def test_apply_writes_decisions_and_refuses_stale(tmp_path):
    (tmp_path / "pg-020.md").write_text(PAGE_A, encoding="utf-8")
    a = C.page_streams(PAGE_A, 20, {"THOMAS-APPARATUS"})["CAIETANUS"]
    b = C.page_streams(PAGE_B, 20, set())["CAIETANUS"]
    rows = C.collate_voice("CAIETANUS", a, b, [], None, {20: PAGE_A}, {20: PAGE_B})
    rows[0]["id"] = "s0001"
    assert rows[0]["a_text"] == "esset" and rows[0]["b_text"] == "essent"
    edits, errors = C.plan_edits(rows, {"s0001": ("=b", "crop pg-020")})
    assert not errors
    ((start, end, text, sid),) = edits[20]
    assert PAGE_A[start:end] == "esset" and text == "essent"
    edits, errors = C.plan_edits(rows, {"s0009": ("x", "e")})
    assert errors == ["s0009: no such site"]


def test_apply_end_to_end_and_stale_refusal(tmp_path):
    a_dir, b_dir = tmp_path / "a", tmp_path / "b"
    a_dir.mkdir(); b_dir.mkdir()
    (a_dir / "pg-020.md").write_text(PAGE_A, encoding="utf-8")
    (b_dir / "pg-020.md").write_text(PAGE_B, encoding="utf-8")
    out = tmp_path / "sites.jsonl"
    from typer.testing import CliRunner
    r = CliRunner().invoke(C.app, ["sites", str(a_dir), str(b_dir), "--range", "20-20", "--out", str(out),
                                   "--skip", "THOMAS-APPARATUS"])
    assert r.exit_code == 0, r.output
    rows = C.load_sites(out)
    caj = next(s for s in rows if s["voice"] == "CAIETANUS")
    note = next(s for s in rows if s["voice"] == "THOMAS")
    dec = tmp_path / "d.tsv"
    dec.write_text(f"{caj['id']}\t=b\tcrop\n{note['id']}\t{note['b_text']}\tcrop\n", encoding="utf-8")
    r = CliRunner().invoke(C.app, ["apply", str(out), str(dec), str(a_dir)])
    assert r.exit_code == 0, r.output
    text = (a_dir / "pg-020.md").read_text(encoding="utf-8")
    assert "quod essent materiales" in text and "*1 D. 115." in text
    r = CliRunner().invoke(C.app, ["apply", str(out), str(dec), str(a_dir)])
    assert r.exit_code == 1 and "no longer has" in r.output
