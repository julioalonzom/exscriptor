import json
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


def test_garbled_ocr_still_raises_a_site_through_its_letter_confusions():
    """« quen-dam » printed, the reader wrote the commoner « quemdam », the OCR « qucndam »
    (c for e): not a word, so no site, and the misreading went to the edition (tome V p. 93)."""
    words = "unum duo tres quattuor quendam sex septem octo".split()
    a = [C.Tok(C.fold(w), w, 1, k * 10, k * 10 + len(w)) for k, w in enumerate(words)]
    a[4] = C.Tok("quemdam", "quemdam", 1, 40, 47)
    ocr = _ocr([w if w != "quendam" else "qucndam" for w in words], page=1)
    lex = Counter({w: 5 for w in words + ["quemdam"]})
    sites = C.collate_voice("BODY", a, list(a), ocr, lex)
    assert [(s["a"], s["ocr"]) for s in sites] == [("quemdam", "qucndam")]
    # OCR noise that repairs to the reading itself is no site
    ocr = _ocr([w if w != "quendam" else "qucmdam" for w in words], page=1)
    assert C.collate_voice("BODY", a, list(a), ocr, lex) == []


def test_ocr_anchors_on_another_page_are_not_a_site():
    """A local mis-alignment to a repeated phrase on another page must not make
    a site: its crop would be cut from the wrong page (tome V pp. 95, 97, 105)."""
    words = "unum duo tres quattuor quinque sex septem octo".split()
    a = [C.Tok(C.fold(w), w, 1, k * 10, k * 10 + len(w)) for k, w in enumerate(words)]
    a[4] = C.Tok("quinqve", "quinqve", 1, 40, 47)
    ocr = _ocr(words, page=2)
    lex = Counter({w: 5 for w in words})
    assert C.collate_voice("BODY", a, list(a), ocr, lex) == []


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


def test_sheet_lists_unsettled_sites_and_manual_refuses(tmp_path):
    rows = [
        {"id": "s0001", "kind": "a-b", "voice": "V", "ocr_agrees": "a", "pages": [1], "before": "x", "after": "y",
         "a": "essent", "b": "esset", "a_text": "essent", "b_text": "esset", "ocr": "essent", "a_span": {"page": 1, "start": 0, "end": 6}},
        {"id": "s0002", "kind": "a-b", "voice": "V", "ocr_agrees": "neither", "pages": [1], "before": "x", "after": "y",
         "a": "Art 2", "b": "D 115", "a_text": None, "b_text": None, "ocr": "", "a_span": {"page": 1, "start": 9, "end": 12}},
    ]
    sites = tmp_path / "s.jsonl"
    sites.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    out = tmp_path / "sheet.md"
    from typer.testing import CliRunner
    r = CliRunner().invoke(C.app, ["sheet", str(sites), "--out", str(out), "--sample", "0"])
    assert r.exit_code == 0, r.output
    text = out.read_text(encoding="utf-8")
    assert "## s0002" in text and "MANUAL" in text and "## s0001" not in text
    _, errors = C.plan_edits(rows, {"s0002": ("MANUAL", "note *2 is Cf. cap. IV.")})
    assert errors and "MANUAL" in errors[0]


def test_flag_on_agreed_word_is_a_site_and_span_covers_brackets():
    pa = "<<<CAIETANUS>>>\nut dicit ⟦Damascenus?⟧ in libro.\n"
    pb = "<<<CAIETANUS>>>\nut dicit Damascenus in libro.\n"
    a = C.page_streams(pa, 5, set())["CAIETANUS"]
    b = C.page_streams(pb, 5, set())["CAIETANUS"]
    (site,) = C.collate_voice("CAIETANUS", a, b, [], None, {5: pa}, {5: pb})
    assert site["kind"] == "flag" and site["a_text"] == "⟦Damascenus?⟧"
    edits, errors = C.plan_edits([dict(site, id="s1")], {"s1": ("Damascenus", "crop")})
    ((s0, e0, new, _),) = edits[5]
    assert not errors and pa[:s0] + new + pa[e0:] == pb


def test_bare_flag_touching_a_word_is_absorbed():
    pa = "<<<C>>>\nparte II, ⟦?⟧ap. XLII.\n"
    a = C.page_streams(pa, 1, set())["C"]
    assert a[2].raw == "ap" and a[2].flagged
    (site,) = C.collate_voice("C", a, list(a), [], None, {1: pa}, {1: pa})
    assert site["kind"] == "flag" and site["a_text"] == "⟦?⟧ap"


def test_contract_tags_are_markup_not_doubts():
    """An inline marginal note (`^[⟦M⟧ …]`) is not a flagged reading, and its tag is no word."""
    from exscriptor.collate import page_streams
    toks = page_streams("<<<THOMAS>>>\nsupra^[⟦M⟧ Art. 2.] dictum ⟦essse?⟧ est\n<<<END THOMAS>>>\n", 5, set())["THOMAS"]
    assert [t.norm for t in toks] == ["supra", "art", "2", "dictum", "essse", "est"]
    assert [t.norm for t in toks if t.flagged] == ["essse"]


def _site(**kw):
    base = {"id": "s1", "kind": "ocr-only", "a": "separetur", "a_text": "separetur", "ocr": "separaretur",
            "before": "si per intellectum", "after": "ab", "pages": [31]}
    return {**base, **kw}


def test_tiebreak_takes_the_print_from_a_confident_blind_crop_reading():
    from exscriptor.collate import tiebreak_verdict
    read = {"found": True, "word": "separaretur", "confidence": "high"}
    reading, evidence = tiebreak_verdict(_site(), read)
    assert reading == "separaretur" and "as the OCR" in evidence
    assert tiebreak_verdict(_site(a="separaretur", a_text="separaretur", ocr="separetur"), read)[0] == "=a"


def test_tiebreak_never_guesses():
    from exscriptor.collate import tiebreak_verdict
    assert tiebreak_verdict(_site(), {"found": True, "word": "separaretur", "confidence": "medium"}) is None
    assert tiebreak_verdict(_site(), {"found": True, "word": "separatur", "confidence": "high"}) is None
    assert tiebreak_verdict(_site(), {"found": False, "word": "", "confidence": "high"}) is None
    assert tiebreak_verdict(_site(), None) is None


def test_tiebreak_settles_a_reader_doubt_by_dropping_its_brackets():
    from exscriptor.collate import tiebreak_verdict
    site = _site(kind="flag", a="quoad", a_text="⟦quoad?⟧", ocr="")
    assert tiebreak_verdict(site, {"found": True, "word": "quoad", "confidence": "high"})[0] == "quoad"


def test_tiebreak_command_appends_and_respects_earlier_answers(tmp_path):
    from typer.testing import CliRunner
    from exscriptor.collate import app
    sites = tmp_path / "sites.jsonl"
    sites.write_text("\n".join(json.dumps(_site(id=i)) for i in ("s1", "s2", "s3")) + "\n")
    reads = tmp_path / "readings.jsonl"
    reads.write_text("\n".join(json.dumps({"id": i, "found": True, "word": "separaretur", "confidence": c})
                               for i, c in (("s1", "high"), ("s2", "high"), ("s3", "low"))) + "\n")
    dec = tmp_path / "decisions.tsv"
    dec.write_text("s2\t=a\tadjudicator: crop shows separetur\n")
    r = CliRunner().invoke(app, ["tiebreak", str(sites), str(reads), "--decisions", str(dec),
                                 "--escalate", str(tmp_path / "esc.jsonl")])
    assert r.exit_code == 0, r.output
    lines = dec.read_text().splitlines()
    assert lines[0].startswith("s2\t=a") and lines[1].startswith("s1\tsepararetur")
    assert [json.loads(l)["id"] for l in (tmp_path / "esc.jsonl").read_text().splitlines()] == ["s3"]


def test_tiebreak_folds_superscript_abbreviations():
    from exscriptor.collate import tiebreak_verdict
    site = _site(a="Iª IIae", a_text="Iª IIae", ocr="I II")
    assert tiebreak_verdict(site, {"found": True, "word": "Iᵃ IIᵃᵉ", "confidence": "high"})[0] == "=a"


def test_ocr_only_site_carries_its_text_so_apply_can_write_it():
    """An OCR-only correction must be applicable like any other site (tome V: 13 of 13 were refused)."""
    words = "unum duo tres quattuor quinque sex septem octo".split()
    text = " ".join(words).replace("quinque", "quinqve")
    a, k = [], 0
    for w in text.split():
        a.append(C.Tok(C.fold(w), w, 1, k, k + len(w))); k += len(w) + 1
    lex = Counter({w: 5 for w in words})
    (site,) = C.collate_voice("BODY", a, list(a), _ocr(words, page=1), lex, {1: text})
    assert site["a_text"] == "quinqve"
    site["id"] = "s1"
    edits, errors = C.plan_edits([site], {"s1": ("quinque", "crop")})
    assert not errors and edits[1][0][2] == "quinque"


def test_tiebreak_joins_a_line_end_hyphen_from_the_crop():
    """The crop shows print lines; the page file joins a word split at a line end."""
    from exscriptor.collate import tiebreak_verdict
    site = _site(a="considerant", a_text="considerant", ocr="considerantur")
    assert tiebreak_verdict(site, {"found": True, "word": "con-siderantur", "confidence": "high"})[0] == "considerantur"


def test_a_span_across_a_note_boundary_is_not_one_run():
    """«1149.], inquantum»: replacing it would break the note's bracket (tome V p. 81)."""
    text = "ad materiam^[⟦M⟧ D. 471, 1149.], inquantum in ipso"
    i, j = text.index("1149"), text.index("inquantum")
    toks = [C.Tok("1149", "1149", 1, i, i + 4), C.Tok("inquantum", "inquantum", 1, j, j + 9)]
    assert C._slice(toks, {1: text}) is None


def test_site_rows_carry_the_page_files_line_for_the_second_pass(tmp_path):
    from typer.testing import CliRunner
    from exscriptor.collate import app
    (tmp_path / "pg-081.md").write_text("<<<THOMAS>>>\nut supra^[⟦M⟧ Qu. lv, art. 2.] dictum est\nnext line\n")
    text = (tmp_path / "pg-081.md").read_text()
    s = text.index("Qu. lv")
    site = {"id": "s40", "kind": "ocr-only", "a": "Qu lv art 2", "a_text": "Qu. lv, art. 2", "ocr": "dictum est",
            "before": "ut supra", "after": "dictum est", "pages": [81], "a_span": {"page": 81, "start": s, "end": s + 14}}
    (tmp_path / "sites.jsonl").write_text(json.dumps(site) + "\n")
    r = CliRunner().invoke(app, ["site-rows", str(tmp_path / "sites.jsonl"), "--crops", str(tmp_path),
                                 "--out", str(tmp_path / "rows.jsonl"), "--a-dir", str(tmp_path)])
    assert r.exit_code == 0, r.output
    assert json.loads((tmp_path / "rows.jsonl").read_text())["line"] == "ut supra^[⟦M⟧ Qu. lv, art. 2.] dictum est"


def test_a_keyed_witness_raises_only_real_differences(tmp_path):
    """Tome V p. 93: the reader's « quemdam » for the print's « quendam », which the garbled OCR
    could not raise; the keyed text (Corpus Thomisticum) has it. Its text beyond the range, the
    page file's notes and a word split at a line end raise nothing."""
    from typer.testing import CliRunner
    from exscriptor.collate import app
    (tmp_path / "pg-093.md").write_text("<<<THOMAS>>>\n**ARTICULUS III**\n2. Praeterea, per quemdam^[⟦M⟧ Art. 2.] modum "
                                        "pro-\npriam cognitionem habent.\n<<<END THOMAS>>>\n")
    (tmp_path / "ct.txt").write_text("Ad primum sic proceditur. Praeterea, per quendam modum propriam cognitionem habent. Sed contra.")
    r = CliRunner().invoke(app, ["witness", str(tmp_path), str(tmp_path / "ct.txt"), "--voice", "THOMAS", "--range", "93-93",
                                 "--out", str(tmp_path / "w.jsonl"), "--drop", r"\^\[[^\]]*\]", "--drop", r"^\*\*.*\*\*$",
                                 "--drop", r"^\d+\.(?= )"])
    assert r.exit_code == 0, r.output
    rows = [json.loads(l) for l in (tmp_path / "w.jsonl").read_text().splitlines()]
    assert [(x["id"], x["a_text"], x["b"], x["pages"]) for x in rows] == [("w0001", "quemdam", "quendam", [93])]


def test_tiebreak_takes_a_keyed_witness_reading_the_print_confirms():
    from exscriptor.collate import tiebreak_verdict
    site = _site(kind="witness", a="quemdam", a_text="quemdam", b="quendam", ocr="qucndam")
    reading, evidence = tiebreak_verdict(site, {"found": True, "word": "quendam", "confidence": "high"})
    assert reading == "quendam" and "keyed witness" in evidence


def test_a_witness_site_kept_as_read_names_the_witness_not_the_ocr():
    from exscriptor.collate import tiebreak_verdict
    site = _site(kind="witness", a="scit", a_text="scit", b="sit", ocr="scit")
    reading, evidence = tiebreak_verdict(site, {"found": True, "word": "scit", "confidence": "high"})
    assert reading == "=a" and "keyed witness has 'sit'" in evidence and "OCR" not in evidence


def test_read_decisions_refuses_a_site_decided_two_ways(tmp_path):
    import pytest
    from exscriptor.collate import read_decisions
    d = tmp_path / "d.tsv"
    d.write_text("s1\t=a\tscan\ns1\t=a\tscan again\ns2\t=ocr\tscan\n")
    assert read_decisions(d)["s1"][0] == "=a"  # the same reading twice is fine
    d.write_text("s1\t=a\tscan\ns1\tdebet\tscan\n")
    with pytest.raises(ValueError, match="decided twice"):
        read_decisions(d)


def test_tiebreak_writes_one_line_per_decision_when_the_crop_spans_a_line(tmp_path):
    from typer.testing import CliRunner
    from exscriptor.collate import app, read_decisions
    sites = tmp_path / "sites.jsonl"
    sites.write_text(json.dumps({"id": "s1", "kind": "ocr", "a": "obiecto. Et", "a_text": "obiecto. Et",
                                 "ocr": "obiccto I", "a_span": {"page": 1, "start": 0, "end": 11}}) + "\n")
    reads = tmp_path / "readings.jsonl"
    reads.write_text(json.dumps({"id": "s1", "found": True, "confidence": "high", "word": "obiecto.\nEt"}) + "\n")
    dec = tmp_path / "decisions.tsv"
    r = CliRunner().invoke(app, ["tiebreak", str(sites), str(reads), "--decisions", str(dec),
                                 "--escalate", str(tmp_path / "esc.jsonl")])
    assert r.exit_code == 0, r.output
    assert len(dec.read_text().splitlines()) == 1
    assert read_decisions(dec)["s1"][0] == "=a"


def test_site_rows_place_an_insertion_on_its_page(tmp_path):
    """A keyed witness's « Luc XX » where the print has it in the margin: the site inserts into
    the page file, so it spans no page of A's words (tome V, pg-125)."""
    from typer.testing import CliRunner
    from exscriptor.collate import app
    site = {"id": "w6", "kind": "witness", "a": "", "a_text": "", "b": "Luc XX", "ocr": "1",
            "before": "aequalitas angelorum", "after": "Sed anima", "pages": [],
            "a_span": {"page": 125, "start": 337, "end": 337, "insert": True}}
    (tmp_path / "sites.jsonl").write_text(json.dumps(site) + "\n")
    r = CliRunner().invoke(app, ["site-rows", str(tmp_path / "sites.jsonl"), "--crops", str(tmp_path),
                                 "--out", str(tmp_path / "rows.jsonl"), "--page-image", "pages/pg-{n:03d}.jpg"])
    assert r.exit_code == 0, r.output
    row = json.loads((tmp_path / "rows.jsonl").read_text())
    assert row["unit"] == "pg-125" and row["page"] == "pages/pg-125.jpg"
