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
