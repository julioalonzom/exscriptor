import json

from typer.testing import CliRunner

from exscriptor import alignment as al
from exscriptor import ledger as lg
from exscriptor import preflight as pf

LA = "Primum argumentum est hoc.^[1. Arist.]\n\nSecundum sic procedit."
EN = "The first argument is this.^[1. Arist.]\n\nThe second proceeds thus."


def text(lang, content, role):
    return {"language": lang, "content": content, "source_key": "ed-1900", "role": role,
            "source_locator": "p. 1", "license_code": "public_domain", "rights_basis": "public_domain_edition"}


def manifest(la=LA, en=EN, summary="Latin and English."):
    texts = [text("la", la, "transcription")] + ([text("en", en, "translation")] if en else [])
    return {"title": "X", "summary": summary,
            "works": [{"original_language": "la", "sections": [{"section_key": "q1", "title": "De Deo",
                                                                 "texts": texts}]}]}


def make_work(tmp_path, m):
    wd = tmp_path / "work"
    (wd / "manifests").mkdir(parents=True)
    path = wd / "manifests" / "x-v1.json"
    path.write_text(json.dumps(m, ensure_ascii=False))
    return wd, path


def test_latin_only_clean_manifest_passes_and_binds_hash(tmp_path):
    wd, path = make_work(tmp_path, manifest(en=None))
    r = CliRunner().invoke(pf.app, [str(path)])
    assert r.exit_code == 0, r.output
    assert pf.verify(path) is None
    path.write_text(path.read_text() + " ")
    assert "changed" in pf.verify(path)


def test_each_gate_catches_its_defect(tmp_path):
    bad = manifest(la="Primum ⟦?⟧ argumentum est quòd hoc.^[1. Arist.]\n\nsecundum sic procedit",
                   summary="Some sites need Julio's review.")
    rep = pf.run(make_work(tmp_path, bad)[1], work_dir=tmp_path / "work")
    failed = {g for g, v in rep["gates"].items() if not v["passed"]}
    assert {"residue", "orthography", "seams", "alignment"} <= failed


def test_parity_and_alignment_gate(tmp_path):
    wd, path = make_work(tmp_path, manifest(en=EN.replace("^[1. Arist.]", "")))
    rep = pf.run(path, work_dir=wd)
    assert not rep["gates"]["parity"]["passed"]
    wd, path = make_work(tmp_path / "b", manifest())
    rep = pf.run(path, work_dir=wd)
    assert "no alignment report" in rep["gates"]["alignment"]["findings"][0]
    m = json.loads(path.read_text())
    pairs = al.pairs_by_section(m, "la", "en")
    sections = al.screen(pairs)
    for f in sections["q1"]["flags"]:
        f["disposition"] = {"verdict": "aligned", "note": f"block {f['index']}: both texts read, same argument throughout"}
    (wd / "alignment").mkdir()
    (wd / "alignment" / "x-v1.json").write_text(json.dumps({"target": "en", "sections": sections}))
    assert pf.run(path, work_dir=wd)["passed"]


def test_ledger_gate_and_waivers(tmp_path):
    wd, path = make_work(tmp_path, manifest(en=None))
    lg.save([lg.normalize({"id": "a", "unit": "q1", "category": "misreading", "quoted": "x",
                           "issue": "y"})], wd / "ledger.jsonl")
    rep = pf.run(path, work_dir=wd)
    assert not rep["gates"]["ledger"]["passed"]
    finding = rep["gates"]["ledger"]["findings"][0]
    (wd / "preflight-waivers.json").write_text(json.dumps(
        [{"gate": "ledger", "finding": finding, "reason": "tracked in another batch"}]))
    rep = pf.run(path, work_dir=wd)
    assert rep["gates"]["ledger"]["passed"] and rep["gates"]["ledger"]["waived"]


def test_default_work_dir(tmp_path):
    assert pf.default_work_dir(tmp_path / "w" / "manifests" / "m.json") == (tmp_path / "w").resolve()


def test_original_text_in_another_language_needs_no_alignment(tmp_path):
    m = manifest(en=None)
    m["works"][0]["sections"][0]["texts"] = [text("es", "Introducción del editor.", "original")]
    wd, path = make_work(tmp_path, m)
    assert pf.run(path, work_dir=wd)["gates"]["alignment"]["passed"]


def test_a_correction_of_the_source_language_needs_no_alignment(tmp_path):
    m = {"title": "X", "summary": "Notes closed.", "works": [{"import_mode": "edit", "slug": "w", "operations": [
        {"op": "put_text", "section_id": 1, "language": "la", "content": LA, "expected_text_id": 5,
         "source_key": "fix", "role": "correction"}]}]}
    wd, path = make_work(tmp_path, m)
    assert pf.run(path, work_dir=wd)["gates"]["alignment"]["passed"]


def test_residue_refuses_unclosed_doubled_and_nested_notes(tmp_path):
    ok = "Verba^[46. Verba Hugonis … censeas. [Editor's note: the print reads *Quiquid*; read *Quidquid*.]] sunt."
    assert pf.note_defects(ok) == []
    assert [k for k, _ in pf.note_defects("a^[1. b")] == ["unclosed"]
    assert [k for k, _ in pf.note_defects("a^[^[1. b]]")] == ["doubled"]
    assert [k for k, _ in pf.note_defects("a^[1. b^[2. Editor's note: c.] d]")] == ["nested"]
    nested = manifest(la=LA.replace("Arist.]", "Arist.^[Editor's note: x.]]"), en=None)
    rep = pf.run(make_work(tmp_path, nested)[1], work_dir=tmp_path / "work")
    assert "nested inline note" in " ".join(rep["gates"]["residue"]["findings"])


def test_residue_refuses_a_note_left_cut_at_the_page_foot(tmp_path):
    cases = {"Arist. habet ap-]": "note cut mid-word",
             "Arist. ap. [Editor's note: print ends the note here; no continuation follows.]]": "unfinished note"}
    for i, (bad, label) in enumerate(cases.items()):
        m = manifest(la=LA.replace("Arist.]", bad), en=None)
        rep = pf.run(make_work(tmp_path / str(i), m)[1], work_dir=tmp_path / str(i) / "work")
        assert label in " ".join(rep["gates"]["residue"]["findings"])


def test_residue_tells_the_numeral_thirty_from_a_placeholder():
    from exscriptor.preflight import RESIDUE
    rx = RESIDUE["todo"]
    assert not rx.search("XXX. Ad hoc breviter dicitur")
    assert not rx.search("ut supra^[Qu. XXX, art. 3.] dictum est")
    assert not rx.search("Scripturae, *Proverb.* XXX^[Vers. 4.]: *Quod nomen eius")
    assert not rx.search("ut habes in XXX Distinctione Primi")
    assert not rx.search("as you have in the XXX Distinction of the First Book")
    assert not rx.search("como tienes en la Distinción XXX del Primero")
    assert not rx.search("*Contra Gentiles*, chapters XXX and LV, and in")
    assert not rx.search("fue discutido en la cuestión XXX aquí")
    assert rx.search("the reading here is XXX until checked")
    assert rx.search("XXX")
    assert rx.search("TODO: fix")


def test_one_alignment_report_per_translated_language(tmp_path):
    wd, path = make_work(tmp_path, manifest())
    m = json.loads(path.read_text())
    # a second translation of the same section
    for sec in m["works"][0]["sections"]:
        en = [t for t in sec["texts"] if t["language"] == "en"]
        if en:
            sec["texts"].append(dict(en[0], language="es"))
    path.write_text(json.dumps(m))
    (wd / "alignment").mkdir()
    for lang in ("en", "es"):
        sections = al.screen(al.pairs_by_section(m, "la", lang))
        for s in sections.values():
            for f in s["flags"]:
                f["disposition"] = {"verdict": "aligned", "note": f"block {f['index']}: both texts read, same argument throughout"}
        (wd / "alignment" / f"x-v1.{lang}.json").write_text(
            json.dumps({"target": lang, "sections": sections}))
        if lang == "en":
            rep = pf.run(path, work_dir=wd)
            assert "no alignment report for it" in rep["gates"]["alignment"]["findings"][0]
    assert pf.run(path, work_dir=wd)["passed"]


def test_residue_finds_stray_asterisks_not_markup():
    from exscriptor.preflight import RESIDUE
    rx = RESIDUE["stray asterisk"]
    for bad in ("pues «sacra doctrina» ** se toma", "intelligentem? - *^[Num. 71.] *Sit*",
                "ad propositum **^[Cf. num. XXXI.]", "*Fourth, * he derives", "que «simpliciter» * * determina"):
        assert rx.search(bad), bad
    for good in ("**Ad primum** quod", "*Sent.*^[Cf.]", "the *fourth* point", "* a list item",
                 "ly *sacra doctrina* sumitur", "**QUAESTIO XVI**"):
        assert not rx.search(good), good


def test_page_check_finds_a_doubled_reference_mark_in_zoned_pages():
    from exscriptor.check_markers import check_page, markup_issues
    assert any("stray asterisk" in i for i in markup_issues("rationis *[*1] et", "pg", apparatus_keys=True))
    assert not any("stray asterisk" in i for i in markup_issues("rationis[*1] et *quod*[*2]", "pg",
                                                                apparatus_keys=True))
    assert not any("stray asterisk" in i for i in check_page("<<<AUTHOR>>>\nTextus[*1].\n"
                                                             "<<<AUTHOR-MARGINALIA>>>\n*1 Cf.\n", "pg"))


P1 = "1. Primum argumentum est quod omnis scientia habet obiectum suum proprium et adaequatum."
P2 = "2. Secundo arguitur quia metaphysica considerat ens in quantum ens et eius passiones."
P3 = "1. Explicata ratione obiecti dicendum est de passionibus entis in communi et in particulari."
P4 = "2. Ratio dubitandi est quia ut aliqua sit vera proprietas quatuor conditiones requirit."


def two_sections(s1, s2):
    m = manifest(en=None)
    sec = m["works"][0]["sections"][0]
    sec2 = json.loads(json.dumps(sec))
    sec["section_key"], sec["texts"][0]["content"] = "s1", s1
    sec2["section_key"], sec2["texts"][0]["content"] = "s2", s2
    sec2["title"] = "Utrum ens habeat passiones"
    m["works"][0]["sections"].append(sec2)
    return m


def test_duplicates_catch_a_section_that_carries_its_neighbour():
    good = two_sections(f"{P1}\n\n{P2}", f"{P3}\n\n{P4}")
    assert pf.gate_duplicates(good) == []
    bad = two_sections(f"{P1}\n\n{P2}", f"{P1}\n\n{P2}\n\n{P3}\n\n{P4}")
    found = pf.gate_duplicates(bad)
    assert len(found) == 2 and "repeats s1 block 1" in found[0]


def test_source_order_passes_the_source_and_fails_each_defect():
    flow = ["DISPUTATIO III", P1, P2, "SECTIO II Utrum ens habeat passiones", "Solvuntur argumenta", P3, P4]
    assert pf.gate_source_order(two_sections(f"{P1}\n\n{P2}", f"### Solvuntur argumenta\n\n{P3}\n\n{P4}"), flow) == []
    dropped = pf.gate_source_order(two_sections(f"{P1}\n\n{P2}", f"{P3}\n\n{P4}"), flow)
    assert dropped == ["source paragraph 5 missing before s2 block 1: 'Solvuntur argumenta'"]
    dup = pf.gate_source_order(two_sections(f"{P1}\n\n{P2}", f"{P1}\n\n{P2}\n\n{P3}\n\n{P4}"), flow)
    assert any("repeats source paragraph 2" in f for f in dup)
    swapped = pf.gate_source_order(two_sections(f"{P1}\n\n{P2}", f"{P4}\n\n{P3}"), flow)
    assert any("out of order" in f for f in swapped)
    missing = pf.gate_source_order(two_sections(P1, f"### Solvuntur argumenta\n\n{P3}\n\n{P4}"), flow)
    assert missing == [f"source paragraph 3 missing before s2 block 2: {P2[:70]!r}"]
    foreign = pf.gate_source_order(two_sections(f"{P1}\n\n{P2}", "Hoc non est in fonte neque in libro ullo."), flow)
    assert any("not in the source" in f for f in foreign)


def test_source_order_checks_an_edit_batch_text_by_text():
    flow = [P1, P2, P3, P4]
    edit = {"works": [{"slug": "w", "import_mode": "edit", "operations": [
        {"op": "put_text", "section_id": 1, "language": "la", "content": P1},
        {"op": "put_text", "section_id": 3, "language": "la", "content": f"{P4}"}]}]}
    assert pf.gate_source_order(edit, flow) == []
    edit["works"][0]["operations"][1]["content"] = f"{P3}\n\n{P1}"
    assert any("repeats source paragraph 1" in f for f in pf.gate_source_order(edit, flow))
    edit["works"][0]["operations"][1]["content"] = f"{P2}\n\n{P4}"
    assert pf.gate_source_order(edit, flow) == [f"source paragraph 3 missing before section-3 block 2: {P3[:70]!r}"]


def test_source_order_tolerates_a_reading_corrected_in_the_opening_words():
    flow = [P1, P2]
    fixed = P2.replace("Secundo arguitur", "Secundo arguitur etiam")
    assert pf.gate_source_order(two_sections(P1, fixed), flow) == []


def test_source_order_runs_from_the_work_dir(tmp_path):
    wd, path = make_work(tmp_path, two_sections(f"{P1}\n\n{P2}", f"{P1}\n\n{P3}\n\n{P4}"))
    (wd / "source-flow").mkdir()
    (wd / "source-flow" / "01-d03.txt").write_text("\n".join([P1, P2, P3, P4]))
    rep = pf.run(path, work_dir=wd)
    assert not rep["gates"]["source-order"]["passed"]
    assert not rep["gates"]["duplicates"]["passed"]


def test_residue_finds_an_italic_numeral():
    assert pf.RESIDUE["italic numeral"].search("1*. Ratio dubitandi pro utraque parte*.— Ex dictis")
    assert pf.RESIDUE["italic numeral"].search("*27.* Ad argumenta")
    assert not pf.RESIDUE["italic numeral"].search("1. *Ratio dubitandi*.— Ex dictis")


def test_residue_finds_a_space_before_punctuation_in_latin_only():
    rx = pf.SPACE_BEFORE
    assert rx.search("sine causa ; tum") and rx.search("de Trinit , c. 4")
    assert rx.search("q. 18^[Cf. Problems.] , inquit")
    assert not rx.search("sine causa; tum « ; » ( , )")
    m = two_sections("Sine causa ; tum etiam quia.", "Ita est.")
    assert any("space before punctuation" in f for f in pf.gate_residue(m))
    m["works"][0]["sections"][0]["texts"][0]["language"] = "fr"
    assert pf.gate_residue(m) == []


def test_source_order_checks_companion_batches_as_one(tmp_path):
    flow = [P1, "DISPUTATIO III", P2, P3, P4]
    main = two_sections(P1, f"{P3}\n\n{P4}")
    main["works"][0]["sections"].insert(1, {"section_key": "d3", "section_type": "disputatio",
                                            "title": "De passionibus entis", "texts": []})
    append = manifest(en=None)
    sec = append["works"][0]["sections"][0]
    sec["section_key"], sec["texts"][0]["content"] = "d3", P2
    assert pf.gate_source_order(main, flow)            # P2 missing on its own
    assert pf.gate_source_order(pf.with_companions(main, [append]), flow) == []
    assert pf.gate_source_order(pf.with_companions(append, [main]), flow) == []
    wd, path = make_work(tmp_path, main)
    (wd / "source-flow").mkdir()
    (wd / "source-flow" / "01-d03.txt").write_text("\n".join(flow))
    other = wd / "manifests" / "append.json"
    other.write_text(json.dumps(append))
    rep = pf.run(path, work_dir=wd, companions=[other])
    assert rep["gates"]["source-order"]["passed"] and "append.json" in rep["companions"]


def test_facsimile_gate_finds_a_step_back_and_a_gap():
    def row(path, seq, page, off):
        return {"filename": f"pg-{page}.jpg", "section_path": path, "sequence": seq,
                "page_label": f"p. {page}", "text_offset": off}
    good = {"works": [{"facsimile": [row("d/s1", 0, 2, 0), row("d/s1", 1, 3, 900),
                                     row("d/s2", 0, 3, 0), row("d/s2", 1, 4, 700)]}]}
    assert pf.gate_facsimile(good) == []
    bad = {"works": [{"facsimile": [row("d/s1", 0, 2, 0), row("d/s1", 1, 4, 300), row("d/s1", 2, 7, 200),
                                    row("d/s2", 0, 5, 0)]}]}
    found = pf.gate_facsimile(bad)
    assert "d/s1 p. 4: no row for p. 3" in found
    assert "d/s1 p. 7: offset 200 before the previous page's 300" in found
    assert "d/s1 p. 7: no row for p. 5-6" in found
    assert "d/s2 p. 5: page 5 after page 7 in reading order" in found
    two_vols = {"works": [{"facsimile": [row("d/s1", 0, 708, 0), row("d/s2", 0, 709, 0),
                                         dict(row("d/s3", 0, 7, 0), page_label="t. II, p. 1"),
                                         dict(row("d/s3", 1, 8, 500), page_label="t. II, p. 2")]}]}
    assert pf.gate_facsimile(two_vols) == []
    late = {"works": [{"facsimile": [row("d/s1", 0, 2, 0), row("d/s2", 0, 3, 50)]}]}
    assert pf.gate_facsimile(late) == ["d/s2 p. 3: the section's first page starts at offset 50: its opening is on no page"]


def test_facsimile_gate_leaves_blank_leaves_out(tmp_path):
    """A blank page is no page of the work: its row is refused, and the gap it
    leaves is not (Billot 1907: pp. 2 and 8 shadowed pp. 1 and 7 in the reader)."""
    def row(path, seq, leaf, page, off):
        return {"filename": f"pg-{leaf:03d}.jpg", "section_path": path, "sequence": seq,
                "page_label": f"p. {page}", "text_offset": off}
    (tmp_path / "edition").mkdir()
    for leaf, text in [(183, "DE IMMUTABILITATE"), (184, "<!-- notes: blank -->\n"), (185, "Prooemium")]:
        (tmp_path / "edition" / f"pg-{leaf:03d}.md").write_text(text)
    blank = pf.blank_leaves(tmp_path)
    assert blank == {"pg-184"}
    # a verso with only an owner's mark, in a layer the assembly dropped, is blank too
    (tmp_path / "edition/pg-186.md").write_text("<<<MARKS>>>\nex libris\n<<<END MARKS>>>\n")
    assert "pg-186" not in pf.blank_leaves(tmp_path)
    (tmp_path / "assembled").mkdir()
    (tmp_path / "assembled/ASSEMBLY.json").write_text('{"drop_layers": ["MARKS"]}')
    assert pf.blank_leaves(tmp_path) == {"pg-184", "pg-186"}
    (tmp_path / "edition/pg-186.md").unlink()
    without = {"works": [{"facsimile": [row("d/s1", 0, 183, 1, 0), row("d/s2", 0, 185, 3, 0)]}]}
    assert pf.gate_facsimile(without, blank) == []
    assert pf.gate_facsimile(without) == ["d/s2 p. 3: no row for p. 2"]
    padded = {"works": [{"facsimile": [row("d/s1", 0, 183, 1, 0), row("d/s1", 1, 184, 2, 0),
                                       row("d/s2", 0, 185, 3, 0)]}]}
    assert pf.gate_facsimile(padded, blank) == [
        "d/s1 p. 2: pg-184.jpg is a blank leaf: leave it out of the facsimile"]


def test_title_page_gate_keeps_the_title_page_out_of_the_body():
    m = two_sections(f"{P1}\n\n{P2}", f"{P3}\n\n{P4}")
    assert pf.gate_title_page(m) == []
    m["works"][0]["sections"][0].update(section_key="titulus", title="Title page")
    assert pf.gate_title_page(m) == [
        "titulus: a title-page section. The title page is front matter, not the work's body: "
        "drop it (its edition, place and year belong in the source record)"]


def test_guillemets_gate_finds_a_repetition_mark():
    m = two_sections(f"{P1}\n\nAit: « Prima linea,\n\n« secunda ».", f"{P3}\n\n{P4}")
    assert pf.gate_guillemets(m) == []
    m = two_sections(f"{P1}\n\nAit: « Prima linea, « secunda ».", f"{P3}\n\n{P4}")
    [f] = pf.gate_guillemets(m)
    assert f.startswith("s1 [la]: unbalanced guillemets (line 3)")


def test_facsimile_start_gate_finds_a_section_filed_a_leaf_early():
    m = two_sections(f"{P1}\n\n{P2}", f"{P3}\n\n{P4}")
    def rows(first):
        return [{"filename": "pg-1.jpg", "section_path": "d/s1", "sequence": 0, "page_label": "p. 1", "text_offset": 0},
                {"filename": first, "section_path": "d/s2", "sequence": 0, "page_label": "p. 2", "text_offset": 0},
                {"filename": "pg-3.jpg", "section_path": "d/s2", "sequence": 1, "page_label": "p. 3", "text_offset": 90}]
    # the print's OCR: long s read as f, a column per key, a stray running head
    ocr = {"pg-1-c1.jpg": P1.replace("s", "f"), "pg-1-c2.jpg": P2,
           "pg-2-c1.jpg": "12 Difput. III", "pg-2-c2.jpg": "SECTIO II Utrum ens habeat paffiones " + P3,
           "pg-3-c1.jpg": P4, "pg-3-c2.jpg": "Tertio arguitur quod nihil horum probat intentum."}
    m["works"][0]["facsimile"] = rows("pg-2.jpg")
    assert pf.gate_facsimile_start(m, ocr) == []
    m["works"][0]["facsimile"] = rows("pg-1.jpg")
    found = pf.gate_facsimile_start(m, ocr)
    assert len(found) == 1 and found[0].startswith("d/s2: opening not found on its first leaf pg-1.jpg")
    assert pf.gate_facsimile_start(m, None) and pf.gate_facsimile_start({"works": [{}]}, None) == []
    # bilingual: the probe is the source language's text, whatever order the texts come in
    m["works"][0]["facsimile"] = rows("pg-2.jpg")
    for sec in m["works"][0]["sections"]:
        sec["texts"].append(text("en", "Whether being has properties, and how they are known to us by reason", "translation"))
    assert pf.gate_facsimile_start(m, ocr, "la") == []


def test_edit_batch_put_text_is_gated():
    def edit(content, expected_text_id=7, **extra):
        return {"title": "X", "summary": "Corrections.", "works": [{"slug": "w", "import_mode": "edit",
                "operations": [{"op": "put_text", "section_id": 12, "language": "la",
                                "content": content, "expected_text_id": expected_text_id, **extra}]}]}
    assert list(lg.manifest_texts(edit(LA))) == [("section-12", "la", LA)]
    # a replacement inherits provenance; an added language must declare it
    assert pf.gate_metadata(edit(LA)) == []
    assert pf.gate_metadata(edit(LA, expected_text_id=None)) == [
        "section-12 [la]: missing source_key, role, license_code, rights_basis"]
    assert pf.gate_residue(edit("Primum ⟦?⟧ argumentum."))


def test_parity_counts_the_print_apparatus_against_the_live_source():
    la = "1. Verba I Cor., 13.^[[haec autem] Vide supra.]"
    en = "1. The words of 1 Cor. 12.^[Editor's note: The print reads 13.]^[\\[*haec autem*\\] See above.]"
    m = {"works": [{"slug": "w", "sections": [{"section_key": "q1", "texts": [{"language": "en", "content": en}]}]}]}
    live = {"works": [{"slug": "w", "sections": [{"section_key": "q1", "texts": [{"language": "la", "content": la}]}]}]}
    assert pf.gate_parity(m) == []  # nothing to pair with
    assert pf.gate_parity(m, [live]) == []
    dropped = json.loads(json.dumps(m).replace("^[\\\\[*haec autem*\\\\] See above.]", ""))
    assert pf.gate_parity(dropped, [live]) == ["q1: footnotes differ: en=0, la=1"]


def test_translation_avoid_finds_a_banned_rendering_in_any_block(tmp_path):
    m = manifest(en="The first argument is this.^[1. Arist.]\n\nIt would be no Inconvenience to say so.")
    wd, path = make_work(tmp_path, m)
    (wd / "translation-avoid.tsv").write_text("# calibration\nno inconvenience\tnullum inconveniens: nothing unfitting\n")
    rep = pf.run(path, work_dir=wd)
    assert rep["gates"]["translation-avoid"]["findings"] == [
        "q1 en block 1: « no inconvenience » (nullum inconveniens: nothing unfitting)"]
    assert pf.gate_translation_avoid(manifest(), pf.read_avoid(wd / "translation-avoid.tsv")) == []


def test_metadata_holds_slugs_and_paths_to_the_platform_patterns():
    m = manifest()
    m["works"][0]["sections"][0].update({"slug": "cap2_5_s1", "section_key": "cap2_5_s1"})
    m["works"][0]["facsimile"] = [{"filename": "pg-1.jpg", "section_path": "pars_altera/cap2_5_s1"}]
    found = [f for f in pf.gate_metadata(m) if "is not" in f]
    assert found == ["cap2_5_s1 slug 'cap2_5_s1' is not ^[a-z0-9-]+$",
                     "batch section_path 'pars_altera/cap2_5_s1' is not ^[a-z0-9-]+(/[a-z0-9-]+)*$"]
    m["works"][0]["sections"][0]["slug"] = "caput-2-5-paragraphus-1"
    m["works"][0]["facsimile"][0]["section_path"] = "pars-altera/caput-2-5-paragraphus-1"
    assert [f for f in pf.gate_metadata(m) if "is not" in f] == []


def test_metadata_holds_titles_to_the_platform_length():
    m = manifest()
    m["works"][0]["sections"][0]["title"] = "§ 2. — " + "Quod Deus est auctor " * 30
    assert [f for f in pf.gate_metadata(m) if "over the platform" in f] == [
        "q1 title is 637 characters, over the platform's 500"]


def test_metadata_wants_the_year_of_a_public_domain_edition():
    # Billot 1907, batch 784: the platform warned "uses public_domain_edition without publication_year".
    m = manifest()
    m["sources"] = [{"source_key": "billot-1907-la", "rights_basis": "public_domain_edition"},
                    {"source_key": "billot-1907-en", "rights_basis": "own_contribution"}]
    assert [f for f in pf.gate_metadata(m) if f.startswith("source ")] == [
        "source billot-1907-la: public_domain_edition without publication_year (the year of the edition transcribed)"]
    m["sources"][0]["publication_year"] = 1907
    assert [f for f in pf.gate_metadata(m) if f.startswith("source ")] == []
