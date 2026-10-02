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
