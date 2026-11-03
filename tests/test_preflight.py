import json

import pytest

from typer.testing import CliRunner

from exscriptor import alignment as al
from exscriptor import ledger as lg
from exscriptor import preflight as pf

LA = "Primum argumentum est hoc.^[1. Arist.]\n\nSecundum sic procedit."
EN = "The first argument is this.^[1. Arist.]\n\nThe second proceeds thus."


@pytest.fixture(autouse=True)
def corpus_map(tmp_path):
    """Every work sits under the corpus spelling map (an empty one here)."""
    (tmp_path / "spelling-map.tsv").write_text("form\tedition\treason\n")



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


def test_structure_gate_finds_the_hierarchy_left_in_the_text():
    # Hurtado 1624 (pilot 3): two books' Disputatio I side by side, a subsectio glued into a
    # sectio title, another left as a bold line at the end of a paragraphus, an empty D8 shell.
    sec = lambda key, title, parent=None, text="Textus.": {
        "section_key": key, "parent_key": parent, "title": title,
        "texts": [{"language": "la", "content": text}] if text else []}
    manifest = {"works": [{"import_mode": "create", "sections": [
        sec("sum-d1", "Disputatio I. De terminis.", text=None),
        sec("sum-d1-s1", "Sectio I. Quid sint?", "sum-d1"),
        sec("log-d1", "Disputatio I. De obiecto Logicae.", text=None),
        sec("log-d1-s3", "Sectio III. Utrum? SUBSECTIO I. Sententia.", "log-d1"),
        sec("log-d1-s3-p21", "21", "log-d1-s3", "Textus.\n\n**SUBSECTIO II. Voces non sunt obiectum.**"),
        sec("log-d8", "Disp. VIII De signo", text=None),
    ]}]}
    found = pf.gate_structure(manifest)
    assert len(found) == 4
    assert any(f.startswith("log-d1: sibling of sum-d1") for f in found)
    assert any(f.startswith("log-d1-s3: one title holds two headings") for f in found)
    assert any(f.startswith("log-d1-s3-p21 [la] block 2 is a heading") for f in found)
    assert any(f.startswith("log-d8: no text") for f in found)
    # A bold thesis line is text, and a metadata batch lists sections without texts.
    manifest["works"][0]["sections"][4]["texts"][0]["content"] = "**Quod traditio regula fidei est.**\n\nTextus."
    manifest["works"][0]["import_mode"] = "update_metadata"
    assert len(pf.gate_structure(manifest)) == 2


def test_siblings_sharing_a_sequence_are_refused():
    # Hurtado 1624 (pilot 3): every sectio of the Logica's disputations had sequence 1;
    # the server refused the batch. A sequence left out is placed in list order.
    sec = lambda key, seq, parent="d1": {"section_key": key, "parent_key": parent, "title": key,
                                         "sequence": seq, "texts": [{"language": "la", "content": "Textus."}]}
    secs = [sec("s1", 1), sec("s2", 1), sec("s3", 2), sec("e1", 1, "d2"), sec("n1", None), sec("n2", None)]
    found = pf.gate_structure({"works": [{"import_mode": "create", "sections": secs}]})
    assert found == ["s2: same sequence 1 as its sibling s1: number siblings in print order "
                     "in structure.json, or leave sequence out"]


def test_an_old_print_page_without_its_long_s_is_refused(tmp_path):
    # Hurtado 1624 (pilot 3): pp. 75-105 kept the FT4 draft's normalized s.
    (tmp_path / "work.json").write_text(json.dumps(
        {"page_files": {"print": "old", "dir": "diplomatic"}, "pages": {"first": 1, "last": 3}}))
    d = tmp_path / "diplomatic"; d.mkdir()
    (d / "pg-001.md").write_text("ipſo eſt poſſit quæſtio " * 10)
    (d / "pg-002.md").write_text("ipso est possit quæstio " * 10 + "<!-- notes: ſ -->")
    (d / "pg-004.md").write_text("ipso est possit quæstio " * 10)  # outside the batch's pages
    assert [f.split(":")[0] for f in pf.gate_long_s(tmp_path)] == ["pg-002"]
    (d / "pg-001.md").write_text("ipso est possit quæstio " * 10)  # a print without ſ
    assert pf.gate_long_s(tmp_path) == []


def test_a_hapax_one_letter_from_a_common_form_is_a_likely_misreading():
    # Hurtado 1624 (pilot 3): "neguit" and "secudum" were triaged away as names.
    from collections import Counter
    from exscriptor import lexicon
    lex = Counter({"nequit": 900, "secundum": 5000, "summulistae": 0})
    found = lexicon.oov(["Neguit Deus. secudum illud. Summulistae dicunt. Summulistae negant."], lex)
    assert lexicon.near_misses(found, lex) == [("neguit", "nequit"), ("secudum", "secundum")]


def test_a_misreading_is_waived_only_by_a_blind_read_of_the_form(tmp_path):
    # Hurtado 1624 (pilot 3, p3-007): 54 waivers said "checked on the scan";
    # the print had perficere, Abſtractio, mediat where they claimed otherwise.
    wd, path = make_work(tmp_path, manifest(la="Intellectum persicere dicunt. Abstratio est duplex.", en=None))
    lex = tmp_path / "lex.json"
    lex.write_text(json.dumps({"files": [], "forms": {"perficere": 900, "abstractio": 600, "est": 9, "dicunt": 9,
                                                      "intellectum": 9, "duplex": 9}}))
    finding = {f.split(":")[0]: f for f in pf.run(path, work_dir=wd, lexicon_path=lex)["gates"]["misreadings"]["findings"]}
    (wd / "preflight-waivers.json").write_text(json.dumps([
        {"gate": "misreadings", "finding": finding["persicere"], "reason": "checked on the scan, a genuine form"},
        {"gate": "misreadings", "finding": finding["abstratio"], "reason": "blind read: Abſtratio; the print's form"}]))
    gate = pf.run(path, work_dir=wd, lexicon_path=lex)["gates"]["misreadings"]
    assert set(gate["findings"]) == {finding["persicere"], finding["abstratio"]} and len(gate["waived"]) == 0
    (wd / "preflight-waivers.json").write_text(json.dumps([
        {"gate": "misreadings", "finding": finding["abstratio"], "reason": "blind read: Abſtractio"}]))
    assert finding["abstratio"] in pf.run(path, work_dir=wd, lexicon_path=lex)["gates"]["misreadings"]["findings"]


def test_a_misreading_waiver_holds_only_when_the_site_reader_read_the_form():
    from exscriptor.preflight import misreading_waived, reads_as
    readings = {"testimonnio": ["teſtimomnio"], "constantur": ["cõſtantur,"], "tubae": ["tu-bæ"]}
    # Hurtado p3-010: a quoted read the reader never gave.
    assert not misreading_waived("testimonnio", "blind read: testimonnio", readings)
    assert misreading_waived("constantur", "blind read: cóſtantur", readings)
    assert misreading_waived("tubae", "blind read: tubae", readings)
    assert not misreading_waived("amatu", "blind read: amatu; BSB OCR witness reads it", readings)
    assert reads_as("cóſtantur", "constantur") and reads_as("Reſpondet", "respondet")
    assert not reads_as("Reſpondet", "responder")


def test_an_escalated_reading_needs_its_editors_note():
    from exscriptor.preflight import escalations_without_note
    row = {"id": "x", "unit": "pg-097", "verdict": "corrected", "escalate": True, "final": "in vno ſolo conſiſtit"}
    bare = {"pg-097": "excluſio omnium, & in vno ſolo conſiſtit. Hæc de"}
    noted = {"pg-097": "excluſio omnium, & in vno ſolo conſiſtit^[Editor's note: the print reads conſiſti; read conſiſtit.]. Hæc"}
    assert escalations_without_note([row], bare, {})
    assert not escalations_without_note([row], noted, {})
    assert not escalations_without_note([dict(row, escalate=False)], bare, {})


def test_every_site_reading_lands_in_the_text_or_its_note(tmp_path):
    from exscriptor.preflight import unreconciled_sites
    p = tmp_path / "readings.jsonl"
    rows = [{"id": "m46", "unit": "pg-097", "edition": "consisti", "found": True, "word": "ſiſti."},
            {"id": "m05", "unit": "pg-009", "edition": "testimonnio", "found": True, "word": "teſtimomnio"},
            {"id": "m30", "unit": "pg-058", "edition": "idemq", "found": True, "word": "idemq;"},
            {"id": "m34", "unit": "pg-071", "edition": "paper", "found": False, "word": ""}]
    p.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows))
    text = ("quo testimonio^[Editor's note: the print reads teſtimomnio; read testimonio.] idemque dixerim, "
            "in uno solo consistit^[Editor's note: the printed word is cut by the line break.]")
    out = unreconciled_sites(p, [text])
    assert len(out) == 1 and out[0].startswith("site m46")


def test_a_translations_print_reads_note_quotes_the_latins():
    from exscriptor.preflight import gate_print_reads
    def m(en):
        return {"works": [{"slug": "w", "sections": [{"key": "s1", "texts": [
            {"language": "la", "content": "testimonio^[Editor's note: the print reads teſtimomnio; read testimonio.]"},
            {"language": "en", "content": en}]}]}]}
    assert gate_print_reads(m("testimony^[1. Editor's note: the print reads teſtimomnio; read testimonio.]")) == []
    assert gate_print_reads(m("testimony^[1. Editor's note: the print reads testimonnio; read testimonio.]"))


def test_every_site_reader_run_is_reconciled_on_its_own_page(tmp_path):
    # Hurtado p3-018: a run kept in tmp/witness-lector/ was never read by the gate, and the
    # reader's spiritalis was dropped; elsewhere in the work the word would have hidden it.
    from exscriptor.preflight import site_reading_files, unreconciled_sites
    run = tmp_path / "tmp" / "witness-lector" / "gemini"
    run.mkdir(parents=True)
    (run / "jobs.json").write_text("[]")
    (run / "readings.jsonl").write_text(json.dumps(
        {"id": "w08", "unit": "pg-064", "edition": "spiritualis", "found": True, "word": "ſpirita-lis"}) + "\n")
    (tmp_path / "tmp" / "scratch").mkdir()
    (tmp_path / "tmp" / "scratch" / "readings.jsonl").write_text("not a site run\n")
    files = site_reading_files(tmp_path)
    assert files == [run / "readings.jsonl"]
    pages = {"pg-064": "substantia spiritualis completa", "pg-070": "anima spiritalis"}
    assert len(unreconciled_sites(files, list(pages.values()), pages)) == 1
    assert not unreconciled_sites(files, list(pages.values()))


def test_a_site_sent_to_the_reader_needs_a_reading(tmp_path):
    # Hurtado p3-019: verdicts on a 'found false' read and on two deleted rows.
    from exscriptor.preflight import unread_sites
    run = tmp_path / "tmp" / "w" / "gemini3"
    run.mkdir(parents=True)
    (run / "jobs.json").write_text(json.dumps([{"name": "b/1", "ids": ["w01", "w02", "w07", "m34"], "harvested": True}]))
    rows = [{"id": "w01", "unit": "pg-006", "edition": "effectus", "found": True, "word": "affectus"},
            {"id": "w02", "unit": "pg-035", "edition": "ſecúda", "found": False, "word": ""},
            {"id": "m34", "unit": "pg-071", "edition": "paper", "found": False, "word": ""}]
    (run / "readings.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows))
    escalated = [{"unit": "pg-071", "escalate": True, "quoted": "actus a…", "proposed": "^[Editor's note: a paper repair]"}]
    out = unread_sites([run / "readings.jsonl"], escalated)
    assert [o.split(" (")[0] for o in out] == ["site w02", "site w07"]
    assert "its row deleted" in out[1]


def test_a_note_whose_reading_is_the_prints_says_nothing():
    from exscriptor.preflight import gate_print_reads
    m = {"works": [{"slug": "w", "sections": [{"key": "s1", "texts": [
        {"language": "la", "content": "ſecunda^[Editor's note: the print reads ſecunda; read secunda.] et "
                                      "quo testimonio^[Editor's note: the print reads teſtimomnio; read testimonio.]"}]}]}]}
    out = gate_print_reads(m)
    assert len(out) == 1 and "'ſecunda'" in out[0]


def test_a_site_reading_lands_on_the_readers_own_line(tmp_path):
    # Hurtado p3-022: p. 35 prints ſecunda once and ſecũda once; the worker put each reading
    # on the other's line, and the word was on the page both times.
    from exscriptor.preflight import unreconciled_sites
    p = tmp_path / "readings.jsonl"
    p.write_text(json.dumps({"id": "w02", "unit": "pg-035", "edition": "ſecúda", "found": True, "word": "ſecũda",
                             "printed_line": "prima,& ſecũda propoſitione, & negatos in t"}, ensure_ascii=False))
    def dip(a, b):
        return {"pg-035": f"Idem patet in prima, & {a} propoſitione, *Petrum non currere\n"
                          f"modos affirmatos in prima, & {b} propoſitione, & negatos in tertia"}
    swapped, right = dip("ſecũda", "ſecunda"), dip("ſecunda", "ſecũda")
    assert len(unreconciled_sites(p, list(swapped.values()), swapped, swapped)) == 1
    assert not unreconciled_sites(p, list(right.values()), right, right)
    noted = {"pg-035": swapped["pg-035"] + "^[Editor's note: the print reads ſecũda; read secunda.]"}
    assert not unreconciled_sites(p, list(noted.values()), noted, swapped)


def test_a_staged_manifest_is_not_revised_in_place(tmp_path):
    from exscriptor.preflight import gate_revision
    m = tmp_path / "manifests" / "w-v1.json"
    m.parent.mkdir()
    (tmp_path / "staged.jsonl").write_text(json.dumps({"batch_id": 848, "manifest": "w-v1.json", "sha256": "old"}) + "\n")
    assert "w-v<n+1>.json" in gate_revision(m, b"{}", tmp_path)[0]
    assert not gate_revision(m.with_name("w-v2.json"), b"{}", tmp_path)
    assert not gate_revision(tmp_path / "x.json", b"{}", tmp_path / "nowhere")


def test_a_reading_from_a_look_alike_line_settles_nothing(tmp_path):
    # Hurtado p3-021: p. 35's crop held "Idem patet in prima, & ſecunda propoſitione", a line
    # like the site's; a reading there would have matched the page and settled the wrong spot.
    from exscriptor.preflight import unreconciled_sites
    dip = {"pg-035": "Idem patet in prima, & ſecunda propoſitione, *Petrum non currere\n"
                     "modos affirmatos in prima, & ſecũda propoſitione, & negatos in tertia"}
    p = tmp_path / "readings.jsonl"
    def row(line):
        return json.dumps({"id": "w02", "unit": "pg-035", "edition": "ſecũda", "found": True, "word": "ſecunda",
                           "context": "modos affirmatos in prima, & […] propoſitione, & negatos in tertia",
                           "printed_line": line}, ensure_ascii=False)
    p.write_text(row("Idem patet in prima, & ſecunda propoſitione, Petrum"))
    out = unreconciled_sites(p, list(dip.values()), dip, dip)
    assert len(out) == 1 and "--wide w02" in out[0]
    p.write_text(row("affirmatos in prima, & ſecunda propoſitione, & negatos"))
    assert "look-alike" not in " ".join(unreconciled_sites(p, list(dip.values()), dip, dip))


def test_a_page_that_skipped_a_column_is_refused(tmp_path):
    # Soto 1550 (pilot 4), lector-4b: the model card warns it can stop at the foot of column one.
    # The BSB OCR reads long s as f; the page keeps it.
    col1 = "Deus tamen rectos facit eoſdem gratia ſua. "
    col2 = "Non autem ſatis eſt veritatem hanc libere arbitrii ſuis propriis fundamentis conſtabiliſſe. "
    wit = {"pg-060.jpg": "DE NATVRA ET GRATIA\n" + (col1 + col2).replace("ſ", "f")}
    (tmp_path / "witness.json").write_text(json.dumps(wit))
    (tmp_path / "work.json").write_text(json.dumps(
        {"page_files": {"print": "old", "dir": "diplomatic"}, "pages": {"first": 9, "last": 266},
         "witness": {"path": "witness.json", "key": "pg-{page03}.jpg", "drop_words": ["natura", "gratia"]}}))
    d = tmp_path / "diplomatic"; d.mkdir()
    (d / "pg-060.md").write_text(col1 + col2)
    assert pf.gate_omission(tmp_path) == []
    (d / "pg-060.md").write_text(col1)
    found = pf.gate_omission(tmp_path)
    assert len(found) == 1 and found[0].startswith("pg-060: 12 consecutive words")
    (tmp_path / "work.json").write_text(json.dumps({"page_files": {"print": "old"}}))  # no witness declared
    assert pf.gate_omission(tmp_path) == []


def test_structure_refuses_a_printed_navigational_index_but_keeps_substantive_index():
    entries = '\n\n'.join(f'*Topic {n}* {n + 10}' for n in range(20))
    nav = {'section_key': 'index', 'title': 'Index sententiarum', 'section_type': 'index',
           'texts': [{'language': 'la', 'content': entries}]}
    substantive = {'section_key': 'index-haereticorum', 'title': 'Index haereticorum', 'section_type': 'index',
                   'texts': [{'language': 'la', 'content': '\n\n'.join(f'Author {n}: an account of the doctrine.' for n in range(20))}]}
    manifest = {'works': [{'import_mode': 'create', 'sections': [nav, substantive]}]}
    findings = pf.gate_structure(manifest)
    assert any(f.startswith('index:') and 'navigation' in f.lower() for f in findings)
    assert not any(f.startswith('index-haereticorum:') for f in findings)


def test_structure_refuses_a_table_of_contents_section():
    sec = {'section_key': 'contents', 'title': 'Table of Contents',
           'texts': [{'language': 'en', 'content': 'Chapter one ... 1'}]}
    assert any('navigation' in x.lower() for x in pf.gate_structure({'works': [{'sections': [sec]}]}))


def test_old_print_witness_flags_unrecognized_f_long_s_disagreement(tmp_path):
    from collections import Counter
    (tmp_path / 'diplomatic').mkdir()
    (tmp_path / 'diplomatic/pg-009.md').write_text('non violentius ac periculofius\n')
    (tmp_path / 'witness.json').write_text(json.dumps({'pg-009.jpg': 'non violentius ac periculoſius'}))
    (tmp_path / 'work.json').write_text(json.dumps({'pages': {'first': 9, 'last': 9},
        'page_files': {'print': 'old', 'dir': 'diplomatic'}, 'witness': {'path': 'witness.json'}}))
    findings = pf.gate_long_s_witness(tmp_path, Counter({'periculosius': 10}))
    assert len(findings) == 1 and 'pg-009' in findings[0] and 'periculofius' in findings[0]
    (tmp_path / 'diplomatic/pg-009.md').write_text('non violentius ac periculoſius\n')
    assert pf.gate_long_s_witness(tmp_path, Counter({'periculosius': 10})) == []


def test_long_s_context_decisions_cannot_use_global_wildcards(tmp_path):
    from collections import Counter
    (tmp_path / 'work.json').write_text(json.dumps({'page_files': {'print': 'old', 'dir': 'diplomatic'}}))
    (tmp_path / 'decisions.tsv').write_text('page\ttoken\toccurrence\tedition\tmethod\tevidence\n'
        '*\tfit\t*\tfit\teditor\tcontext says it is made\n')
    found = pf.gate_long_s_decisions(tmp_path, Counter({'fit': 100, 'sit': 100}))
    assert len(found) == 1 and 'fit' in found[0] and 'wildcard' in found[0]
    (tmp_path / 'decisions.tsv').write_text('page\ttoken\toccurrence\tedition\tmethod\tevidence\n'
        'pg-009\tfit\t1\tfit\tscan\tpage 9 line 4\n')
    assert pf.gate_long_s_decisions(tmp_path, Counter({'fit': 100, 'sit': 100})) == []


def test_long_s_context_decision_cannot_hide_multiple_occurrences_on_one_page(tmp_path):
    from collections import Counter
    (tmp_path / 'diplomatic').mkdir()
    (tmp_path / 'diplomatic/pg-009.md').write_text('fit hoc. fit illud.\n')
    (tmp_path / 'work.json').write_text(json.dumps({'page_files': {'print': 'old', 'dir': 'diplomatic'}}))
    (tmp_path / 'decisions.tsv').write_text('page\ttoken\toccurrence\tedition\tmethod\tevidence\n'
        'pg-009\tfit\t*\tfit\tscan\tone line\n')
    assert any('wildcard' in f for f in pf.gate_long_s_decisions(tmp_path, Counter({'fit': 10, 'sit': 10})))


def test_contextual_wildcard_cannot_be_waived():
    finding = "decisions.tsv: wildcard 'fit' suppresses context-sensitive readings"
    assert not pf.contextual_waiver_allowed('long-s', finding)
    assert pf.contextual_waiver_allowed('long-s', 'pg-009: a different long-s finding')


def test_old_print_context_screen_requires_a_lexicon(tmp_path):
    (tmp_path / 'work.json').write_text(json.dumps({'page_files': {'print': 'old', 'dir': 'diplomatic'}}))
    assert any('--lexicon' in f for f in pf.gate_long_s_decisions(tmp_path, None))


def test_navigational_index_is_caught_even_if_ocr_makes_one_block():
    text = ' '.join(f'topic {n} {n + 20}' for n in range(40))
    section = {'section_key': 'index', 'title': 'Index rerum', 'section_type': 'index',
               'texts': [{'language': 'la', 'content': text}]}
    assert any('navigation list' in x for x in pf.gate_structure({'works': [{'sections': [section]}]}))


def test_old_print_unresolved_contextual_readings_cannot_bypass_preflight(tmp_path):
    from collections import Counter
    (tmp_path / 'diplomatic').mkdir()
    (tmp_path / 'diplomatic/pg-009.md').write_text('ſit fit.\n')
    (tmp_path / 'work.json').write_text(json.dumps({'page_files': {'print': 'old', 'dir': 'diplomatic'},
                                                   'pages': {'first': 9, 'last': 9}}))
    lex = Counter({'fit': 100, 'sit': 100})
    assert any('fit' in f and 'unresolved' in f for f in pf.gate_long_s_decisions(tmp_path, lex))
    (tmp_path / 'decisions.tsv').write_text('page\ttoken\toccurrence\tedition\tmethod\tevidence\n'
        'pg-009\tfit\t1\tfit\tscan\tpage 9 line 1\n')
    assert pf.gate_long_s_decisions(tmp_path, lex) == []


def test_long_s_global_wildcard_needs_review_even_if_f_form_is_unknown(tmp_path):
    from collections import Counter
    (tmp_path / 'work.json').write_text(json.dumps({'page_files': {'print': 'old', 'dir': 'diplomatic'}}))
    (tmp_path / 'decisions.tsv').write_text('page\ttoken\toccurrence\tedition\tmethod\tevidence\n'
        '*\tconfe\t*\tconfe\teditor\tassumed citation\n')
    assert any('wildcard' in f for f in pf.gate_long_s_decisions(tmp_path, Counter({'conse': 31})))


def test_contextual_long_s_decision_requires_scan_method(tmp_path):
    from collections import Counter
    (tmp_path / 'diplomatic').mkdir()
    (tmp_path / 'diplomatic/pg-009.md').write_text('ſit fit.\n')
    (tmp_path / 'work.json').write_text(json.dumps({'page_files': {'print': 'old', 'dir': 'diplomatic'}}))
    (tmp_path / 'decisions.tsv').write_text('page\ttoken\toccurrence\tedition\tmethod\tevidence\n'
        'pg-009\tfit\t1\tfit\teditor\tseems correct in context\n')
    assert any('scan' in f and 'method' in f for f in pf.gate_long_s_decisions(tmp_path, Counter({'fit': 100, 'sit': 100})))


def test_durable_blind_readings_require_traceable_scan_evidence(tmp_path):
    import hashlib
    p = tmp_path / 'qa-reports' / 'blind-readings.jsonl'
    p.parent.mkdir()
    crop = tmp_path / 'qa-reports' / 'site.png'
    crop.write_bytes(b'scan crop')
    sha = hashlib.sha256(crop.read_bytes()).hexdigest()
    row = {'id': 'site-1', 'unit': 'pg-001', 'edition': 'abstratio', 'word': 'Abſtratio',
           'found': True, 'reader': 'vision reader', 'crop': 'qa-reports/site.png',
           'crop_sha256': sha, 'page_sha256': 'a' * 64, 'prompt_sha256': 'b' * 64}
    p.write_text(json.dumps(row) + '\n')
    assert pf.durable_blind_readings(tmp_path) == {'abstratio': ['Abſtratio']}
    crop.write_bytes(b'changed')
    assert pf.durable_blind_readings(tmp_path) == {}


def test_site_reading_needs_word_on_recorded_line_and_not_low_confidence(tmp_path):
    p = tmp_path / 'readings.jsonl'
    rows = [
        {'found': True, 'edition': 'abdunt', 'word': 'abdunt', 'printed_line': 'alia verba sine eo', 'confidence': 'high'},
        {'found': True, 'edition': 'abeatis', 'word': 'abeatis', 'printed_line': 'ne longe abeatis', 'confidence': 'low'},
        {'found': True, 'edition': 'adducite', 'word': 'adducite', 'printed_line': 'ſoluite et adducite mihi', 'confidence': 'high'},
    ]
    p.write_text(''.join(json.dumps(r) + '\n' for r in rows))
    assert pf.site_readings(p) == {'adducite': ['adducite']}
