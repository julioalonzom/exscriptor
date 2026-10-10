import json

from typer.testing import CliRunner

from exscriptor import ledger as lg


def row(**kw):
    base = {"id": "r1", "unit": "q1", "category": "misreading", "quoted": "voluntaci",
            "issue": "not a word", "verdict": "open"}
    base.update(kw)
    return lg.normalize(base)


def test_validate_requires_evidence_once_decided_and_known_vocabulary():
    assert lg.validate([row()]) == []
    errs = lg.validate([row(verdict="corrected", final="voluntati")])
    assert any("rung" in e for e in errs) and any("evidence" in e for e in errs)
    assert lg.validate([row(category="spelling")])
    assert lg.validate([row(), row()])  # duplicate id


def test_legacy_spellings_accepted():
    r = row(category="latin-dubious", verdict="retained-as-printed")
    assert (r["category"], r["verdict"]) == ("misreading", "retained")


def test_triage_finds_rows_whose_text_is_gone():
    rows = [row(id="a", quoted="voluntaci"), row(id="b", quoted="intellectus")]
    stale = lg.triage(rows, {"q1": "intellectus et voluntati"})
    assert [r["id"] for r in stale] == ["a"]


def decided(**kw):
    return row(verdict="corrected", final="voluntati", rung="scan", evidence="p. 12 reads voluntati", **kw)


def test_check_proves_the_fix_in_every_layer():
    layers = {"pages": {"q1": "et voluntati"}, "manifest@la": {"q1": "et voluntaci"}}
    problems = lg.check([decided()], layers)
    assert len(problems) == 1 and "manifest@la" in problems[0]
    assert lg.check([decided()], {"pages": {"q1": "et voluntati"}}) == []
    assert lg.check([row()], {}) and "still open" in lg.check([row()], {})[0]


def test_check_editorial_note_needs_the_note_and_skips_other_languages():
    r = row(verdict="editorial-note", final="voluntati", rung="context", evidence="print damaged")
    assert lg.check([r], {"m@la": {"q1": "voluntati"}})
    assert lg.check([r], {"m@la": {"q1": "voluntati^[3. Editor's note: the print reads voluntaci.]"}}) == []
    en = row(id="e", layer="en", verdict="corrected", final="will", rung="context", evidence="x", quoted="wil")
    assert lg.check([en], {"pages": {"q1": "nothing"}, "m@la": {"q1": "nothing"}}) == []


def test_cli_check_against_manifest(tmp_path):
    led = tmp_path / "ledger.jsonl"
    lg.save([decided()], led)
    m = {"works": [{"sections": [{"section_key": "q1", "texts": [
        {"language": "la", "content": "et voluntati"}, {"language": "en", "content": "and will"}]}]}]}
    (tmp_path / "m.json").write_text(json.dumps(m))
    r = CliRunner().invoke(lg.app, ["check", str(led), "--layer", f"manifest@la={tmp_path / 'm.json'}"])
    assert r.exit_code == 0, r.output
    r = CliRunner().invoke(lg.app, ["summary", str(led)])
    assert '"corrected": 1' in r.output


def test_a_unit_names_its_section_not_a_longer_one():
    from exscriptor.ledger import unit_matches
    assert unit_matches("q12-a3", "q12-a3")
    assert unit_matches("q12-a3", "summa-theologiae-prima-pars/q12-a3")
    assert not unit_matches("q12-a1", "q12-a10")
    assert not unit_matches("q1", "q11")
    assert unit_matches("pg-050..056", "pg-050")


def test_a_row_for_another_work_is_out_of_scope(tmp_path):
    from exscriptor import preflight as pf
    m = {"works": [{"slug": "commentary", "sections": [
        {"section_key": "q12-a3", "texts": [{"language": "la", "content": "Aliud."}]}]}]}
    row = {"id": "x", "unit": "q12-a3", "work": "text", "layer": "la", "category": "misreading",
           "quoted": "per se\n\nvisibile", "issue": "split", "verdict": "corrected",
           "final": "per se visibile", "rung": "scan", "evidence": "PDF 138",
           "raised_by": "a", "decided_by": "b"}
    p = tmp_path / "l.jsonl"
    p.write_text(json.dumps(row) + "\n")
    assert pf.gate_ledger(m, [p]) == []
    row["work"] = "commentary"
    p.write_text(json.dumps(row) + "\n")
    assert pf.gate_ledger(m, [p])


def test_a_row_may_name_its_section_by_the_live_slug(tmp_path):
    from exscriptor import preflight as pf
    m = {"works": [{"slug": "text", "sections": [
        {"slug": "quaestio-12-articulus-3", "section_key": "q12-a3",
         "texts": [{"language": "la", "content": "sicut per se visibile."}]}]}]}
    row = {"id": "x", "unit": "quaestio-12-articulus-3", "work": "text", "layer": "la",
           "category": "structure", "quoted": "per se\n\nvisibile", "issue": "split",
           "verdict": "corrected", "final": "per se visibile, sed", "rung": "scan",
           "evidence": "PDF 138", "raised_by": "a", "decided_by": "b"}
    p = tmp_path / "l.jsonl"
    p.write_text(json.dumps(row) + "\n")
    assert any("final reading not in" in x for x in pf.gate_ledger(m, [p]))


def test_a_section_row_is_found_in_its_page_layer():
    # pages are keyed by page; the row names its section and its page
    r = decided(unit="thesis-25", pg="pg-487")
    assert lg.check([r], {"pages": {"pg-487": "et voluntati"}}) == []
    assert lg.check([r], {"pages": {"pg-488": "et voluntati"}})


def test_a_word_cut_at_a_page_end_is_one_reading():
    # a hyphen split across pages, and a footnote split across pages
    pages = {"pg-127": "ministrum ad exem-\n\n<!-- notes -->\n",
             "pg-128": "\n\nplum ipsius Domini",
             "pg-485": "quod partem alteram hae-\n\n<!-- notes: joins-next: hyphen -->\n",
             "pg-486": "\n\nreseos, quoniam iam",
             }
    def reading(unit, pg, final):
        return {**decided(unit=unit, pg=pg), "final": final}
    assert lg.check([reading("thesis-25", "pg-485", "haereseos")], {"pages": pages}) == []
    assert lg.check([reading("thesis-8", "pg-127", "exemplum")], {"pages": pages}) == []
    notes = {"pg-486": "Ubicumque comme-⟦NOTE-CONTINUES⟧]. Aut asserat",
             "pg-487": "⟦CONTINUED-NOTE⟧moravi Ecclesiam"}
    assert lg.check([reading("thesis-25", "pg-486", "commemoravi")], {"pages": notes}) == []
    assert lg.check([reading("thesis-25", "pg-485", "haereseoz")], {"pages": pages})


def test_a_page_comment_naming_the_old_reading_is_not_the_text():
    page = "et voluntati\n\n<!-- notes: print reads voluntaci -->\n"
    assert lg.check([decided()], {"pages": {"q1": page}}) == []


def test_an_editor_note_closing_a_footnote_counts():
    page = "de Immaculata, sed illud sic^[2. Hebrew cut at page foot. Editor's note: the print reads Numen.]"
    r = {**decided(unit="q1"), "verdict": "editorial-note", "final": "sic"}
    assert lg.check([r], {"pages": {"q1": page}}) == []
    assert lg.check([r], {"pages": {"q1": "sic"}})



def test_metadata_proof_is_explicit_and_bound_to_one_page():
    pages = {"pg-001": "voluntati<!-- notes: joins-next: hyphen -->",
             "pg-002": "<!-- notes: catchword: exemplum -->"}
    r = {**decided(unit="pg-001"), "final": "joins-next: hyphen"}
    assert lg.check([r], {"pages": pages})
    r["proof_target"] = "page_metadata"
    assert lg.check([r], {"pages": pages}) == []
    r["final"] = "catchword: exemplum"
    assert lg.check([r], {"pages": pages})
    assert lg.check([r], {"pages": {"pg-001": "catchword: exemplum"}})
    assert lg.check([r], {"pages": {"pg-001": "<!-- catchword: exemplumque -->"}})
    r["final"] = "joins-next: hyphen"
    assert lg.check([r], {"pages": {"pg-001": "<!-- joins-next: hyphenated -->"}})
    r["unit"] = "absent"
    assert lg.check([r], {"pages": pages})


def test_page_unit_seam_inference_never_proves_comments():
    pages = {"pg-001": "exem-<!-- notes: voluntati -->",
             "pg-002": "plum<!-- notes: voluntati -->"}
    r = {**decided(unit="pg-001"), "final": "exemplum"}
    assert lg.check([r], {"pages": pages}) == []
    r["final"] = "voluntati"
    assert lg.check([r], {"pages": pages})
    r["pg"] = "pg-001"
    assert lg.check([r], {"pages": pages})


def test_proof_target_validation_rejects_mixed_comment_needles():
    for final in ("voluntati<!-- notes:", "voluntati -->"):
        r = {**decided(), "final": final}
        assert lg.validate([r])
        assert lg.check([r], {"pages": {"q1": final}})
    assert lg.validate([decided(proof_target="anything")])
    r = {**decided(proof_target="page_metadata"), "final": "voluntati"}
    assert lg.validate([r])
    r["final"] = "catchword: ſit vl-"
    assert lg.validate([r]) == []


def test_flags_open_one_row_per_reader_flag(tmp_path):
    from typer.testing import CliRunner
    from exscriptor import ledger as lg
    (tmp_path / "pg-001.md").write_text("Et ⟦dicit?⟧ quod^[⟦M⟧ *Gloss.*] ⟦mark: q with hook⟧.\n\n"
                                        "<!-- notes: uncertainties: ⟦x?⟧ -->\n")
    led = tmp_path / "ledger.jsonl"
    for _ in range(2):  # re-running adds nothing
        r = CliRunner().invoke(lg.app, ["flags", str(led), "--pages", str(tmp_path / "pg-*.md")])
        assert r.exit_code == 0, r.output
    rows = lg.load(led)
    assert [(x["quoted"], x["category"], x["proposed"]) for x in rows] == [
        ("⟦dicit?⟧", "misreading", "dicit"), ("⟦mark: q with hook⟧", "normalization", "")]
    assert lg.validate(rows) == []


def test_running_head_proof_is_exact_and_page_bound():
    r = {**decided(unit="pg-001", proof_target="page_metadata"),
         "quoted": "running-head: Diſp. VII.", "final": "running-head: Diſp. VIII."}
    pages = {"pg-001": "Corpus.<!-- notes: running-head: Diſp. VIII.; folio: 1 -->"}
    assert lg.validate([r]) == []
    assert lg.check([r], {"pages": pages}) == []
    assert lg.check([r], {"pages": {"pg-002": pages["pg-001"]}})
    assert lg.check([r], {"pages": {"pg-001": "running-head: Diſp. VIII."}})
    assert lg.check([r], {"pages": {"pg-001": "<!-- running-head: Diſp. VII. -->"}})
