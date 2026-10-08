import json

import pytest
from typer.testing import CliRunner

from exscriptor import assemble as asm


def page(n, body, notes=None):
    text = body + (f"\n\n<!-- notes: {notes} -->" if notes else "")
    return asm.Page(f"p{n:03d}", n, None, asm.ANY_COMMENT.sub("", text).strip(),
                    [notes] if notes else [], (asm.JOINS.search(notes).group(1)
                                                if notes and asm.JOINS.search(notes) else None))


def test_join_kinds():
    assert asm.join_kind("dupli-", "citer est.") == "hyphen"
    assert asm.join_kind("et modo tetigimus,", "Proprium est materiae.") == "space"
    assert asm.join_kind("Finis est.", "sed contra.") == "space"
    assert asm.join_kind("Finis est.", "Sed contra.") == "para"
    assert asm.join_kind("cum praecisione", "**QUAESTIO II.**") == "para"
    assert asm.join_kind("ut dicitur^[3. Arist.]", "Sed contra.") == "space"


def test_bold_lowercase_page_continuation_joins_as_same_paragraph():
    first = "**Quod bona Dei voluntas per malas hominum voluntates impletur, " \
            "ut in passione Christi contigit, ubi quiddam factum est quod Deus**"
    second = "**bona et Iudaei mala voluntate voluerunt; voluerunt tamen et " \
             "aliquid quod Deus non voluit.**"
    text, _, errors = asm.join_pages([page(1, first), page(2, second)])
    assert text == first + " " + second
    assert errors == []
    assert asm.seams.seam_violations(text) == []
    assert asm.join_kind("Textus.", "**CAPUT II.**") == "para"


def test_hyphen_across_emphasis_and_declared_join_reported():
    text, report, errors = asm.join_pages([
        page(1, "Hoc est testimo-*", "joins-next: para"),
        page(2, "*nio verum. Finis."),
    ])
    assert text == "Hoc est testimonio verum. Finis."
    assert errors == []
    assert any("declared para, joined as hyphen" in r for r in report)


def test_footnote_continuation_fused_anywhere_on_next_page():
    text, report, errors = asm.join_pages([
        page(1, "Corpus primum.^[1. Nota incipit ⟦NOTE-CONTINUES⟧]"),
        page(2, "Sequitur textus.\n\n⟦CONTINUED-NOTE⟧ et finitur.\n\nAlius."),
    ])
    assert "^[1. Nota incipit et finitur.]" in text
    assert "⟦" not in text and errors == []
    assert text.count("\n\n") == 2  # 'Corpus..' / 'Sequitur..' / 'Alius.'


def test_hyphenated_footnote_continuation_removes_print_linebreak():
    text, _, errors = asm.join_pages([
        page(1, "^[1. *Theologia* ‘Scho-⟦NOTE-CONTINUES⟧]"),
        page(2, "⟦CONTINUED-NOTE⟧larium’]."),
    ])
    assert errors == []
    assert "^[1. *Theologia* ‘Scholarium’].]" in text


def test_unmatched_sentinels_are_errors():
    _, _, errors = asm.join_pages([page(1, "Nota ⟦NOTE-CONTINUES⟧]."), page(2, "Alia.")])
    assert errors
    _, _, errors = asm.join_pages([page(1, "Textus."), page(2, "⟦CONTINUED-NOTE⟧ x.")])
    assert errors


def test_seam_duplet_dropped_but_common_words_kept():
    text, report, _ = asm.join_pages([page(1, "post primam cari."), page(2, "cari. Nam materia.")],
                                     duplets=True)
    assert text.count("cari") == 1 and report
    text, _, _ = asm.join_pages([page(1, "dicit quod"), page(2, "quod est.")], duplets=True)
    assert text.count("quod") == 2


def test_drop_layers_hoists_edition_words():
    text = "Commentarium.\n<<<THOMAS>>>\nArticulus textus. Conclusio affirmativa.\n<<<END THOMAS>>>\nSequitur."
    kept, report, errors = asm.drop_layers(text, ("THOMAS",), (r"Conclusio\b[^.\n]*\.",))
    assert errors == []
    assert "Articulus textus" not in kept
    assert "Conclusio affirmativa." in kept
    assert kept.index("Conclusio") < kept.index("Sequitur")


STRUCTURE = {
    "headings": {"quaestio": r"^\*\*QUAESTIO\b", "articulus": r"^\*\*ARTICULUS\b"},
    "title_line": True,
    "pre": "prooemium",
    "sections": [
        {"key": "prooemium", "type": "prooemium"},
        {"key": "q1", "type": "quaestio"},
        {"key": "q1a1", "type": "articulus"},
        {"key": "q1a2", "type": "articulus"},
    ],
}


def test_split_by_structure_round_trips():
    text = ("Prooemium textus.\n\n**QUAESTIO I.**\n\n**De Deo.**\n\nIntroductio.\n\n"
            "**ARTICULUS I.**\n\nPrimus.\n\n**ARTICULUS II.**\n\nSecundus.\n")
    out, errors = asm.split_sections(text, STRUCTURE)
    assert errors == []
    assert out == {"prooemium": "Prooemium textus.", "q1": "Introductio.",
                   "q1a1": "Primus.", "q1a2": "Secundus."}


def test_split_refuses_a_skipped_heading():
    text = "Pre.\n\n**QUAESTIO I.**\n\nA.\n\n**ARTICULUS I.**\n\nB.\n\n**QUAESTIO II.**\n\nC.\n"
    _, errors = asm.split_sections(text, STRUCTURE)
    assert errors  # QUAESTIO II has no entry left


def test_invariants_catch_residue_and_seams():
    errs = asm.invariants("s", "Textus ⟦?⟧ est.\n\nsed continuatio.")
    assert any("sentinel" in e for e in errs) and any("LOWER-START" in e for e in errs)


def test_renumber_footnotes_one_pass():
    assert asm.renumber_footnotes("a^[7. x] b^[Editor's note: y] c^[2. z]") == \
        "a^[1. x] b^[2. Editor's note: y] c^[3. z]"


def write(tmp_path, n, body):
    (tmp_path / f"p{n:03d}.md").write_text(body, encoding="utf-8")


def test_cli_refuses_missing_page_and_writes_on_success(tmp_path):
    write(tmp_path, 1, "Prooemium textus.\n\n**QUAESTIO I.**\n\n**De Deo.**\n\nIntroductio,")
    write(tmp_path, 3, "et finis.\n")
    (tmp_path / "s.json").write_text(json.dumps(STRUCTURE))
    args = ["--pages", str(tmp_path / "p{n:03d}.md"), "--structure", str(tmp_path / "s.json"),
            "--out-dir", str(tmp_path / "out")]
    r = CliRunner().invoke(asm.app, args + ["--range", "1-3"])
    assert r.exit_code == 1 and "missing page 2" in r.output
    write(tmp_path, 2, "argumentum longum<!-- notes: joins-next: space -->\n")
    r = CliRunner().invoke(asm.app, args + ["--range", "1-3"])
    assert r.exit_code == 0, r.output
    assert (tmp_path / "out/q1.md").read_text() == "Introductio, argumentum longum et finis.\n"
    rec = json.loads((tmp_path / "out/ASSEMBLY.json").read_text())
    assert [p["name"] for p in rec["pages"]] == ["p001", "p002", "p003"]


def test_sentence_may_end_inside_emphasis():
    from exscriptor import seams
    assert seams.seam_violations("*Datum Salmanticae, Anno Domini 1585.*") == []


def test_apparatus_blocks_are_not_prose_seams():
    from exscriptor import seams
    text = "Body sentence.\n\n^[6. *omnis usus* trp. OP.]\n\nNext sentence."
    assert seams.seam_violations(text) == []
    assert seams.paragraph_boundary_findings(text) == []


def test_page_foot_notes_wait_for_the_continued_paragraph():
    text, report, errors = asm.join_pages([
        page(1, "Primum caput. Dicit autem quod non\n\n^[1. Aug., *De Trin.*]\n\n^[2. Ps. 1, 1.]"),
        page(2, "erunt dii alii. Finis.\n\n**2.** Alia res."),
    ])
    assert errors == []
    assert text == ("Primum caput. Dicit autem quod non erunt dii alii. Finis."
                    "\n\n^[1. Aug., *De Trin.*]\n\n^[2. Ps. 1, 1.]\n\n**2.** Alia res.")
    assert any("page-foot notes held" in r for r in report)


def test_page_foot_notes_stay_put_when_the_next_page_starts_a_paragraph():
    text, _, errors = asm.join_pages([
        page(1, "Primum caput finitur.\n\n^[1. Aug.]"),
        page(2, "Sed contra est."),
    ])
    assert errors == []
    assert text == "Primum caput finitur.\n\n^[1. Aug.]\n\nSed contra est."


def test_page_foot_notes_hold_across_a_hyphen():
    text, _, _ = asm.join_pages([
        page(1, "dupli-\n\n^[1. Aug.]"),
        page(2, "citer est.\n\nAlia."),
    ])
    assert text == "dupliciter est.\n\n^[1. Aug.]\n\nAlia."


def test_opens_comment_declaration_is_harvested(tmp_path):
    p = tmp_path / "p1.md"
    p.write_text("Texto.\n\n<!-- opens: x; joins-next: space -->\n<!-- formatting: ok -->\n", encoding="utf-8")
    pg, problems = asm.load_page(p, 1)
    assert problems == [] and pg.declared == "space" and pg.body == "Texto."


def test_implicit_first_child_takes_the_text_after_its_parents_heading():
    structure = {
        "headings": {"distinctio": r"^\*\*DISTINCTIO\b", "caput": r"^\*\*Cap\."},
        "implicit_first": {"distinctio": "caput"},
        "sections": [
            {"key": "d1", "type": "distinctio", "parent": None},
            {"key": "d1c1", "type": "caput", "parent": "d1"},
            {"key": "d1c2", "type": "caput", "parent": "d1"},
            {"key": "d2", "type": "distinctio", "parent": None},
            {"key": "d2c1", "type": "caput", "parent": "d2"},
        ],
    }
    text = ("**DISTINCTIO I**\n\nPrimum caput.\n\n**Cap. 2 (5).**\n\nSecundum caput.\n\n"
            "**DISTINCTIO II**\n\n**Cap. 1 (6).**\n\nTertium caput.")
    out, errors = asm.split_sections(text, structure)
    assert errors == []
    assert out == {"d1c1": "Primum caput.", "d1c2": "Secundum caput.", "d2c1": "Tertium caput."}


def test_node_types_may_have_no_text_of_their_own():
    structure = {
        "headings": {"liber": r"^# LIBER\b", "caput": r"^\*\*Cap\."},
        "node_types": ["liber"],
        "sections": [
            {"key": "l1", "type": "liber", "parent": None},
            {"key": "l1c1", "type": "caput", "parent": "l1"},
            {"key": "l2", "type": "liber", "parent": None},
            {"key": "l2c1", "type": "caput", "parent": "l2"},
        ],
    }
    text = "# LIBER I\n\n**Cap. 1.**\n\nPrimum.\n\n# LIBER II\n\n**Cap. 1.**\n\nSecundum."
    out, errors = asm.split_sections(text, structure)
    assert errors == [] and out == {"l1c1": "Primum.", "l2c1": "Secundum."}
    structure.pop("node_types")
    out, _ = asm.split_sections(text, structure)
    assert out["l1"] == ""  # undeclared: the empty node survives and invariants() reports it


def test_multiple_italic_page_foot_notes_preserve_new_paragraph():
    text, report, errors = asm.join_pages([
        page(1, "Complete paragraph.\n\n^[1. *Aug. XIV.*]\n\n^[2. *Aug. XV.*]", "joins-next: para"),
        page(2, "New paragraph."),
    ])
    assert not errors
    assert text.endswith("^[2. *Aug. XV.*]\n\nNew paragraph.")
    assert not any("declared para, joined as space" in r for r in report)


def test_terminal_stop_inside_italics_preserves_page_paragraph():
    text, report, errors = asm.join_pages([
        page(1, "*Complete quotation.*", "joins-next: para"),
        page(2, "*An italic heading.*\n\nNew paragraph."),
    ])
    assert not errors
    assert text.startswith("*Complete quotation.*\n\n*An italic heading.*")
    assert not any("declared para, joined as space" in r for r in report)


def test_unnumbered_author_citations_keep_book_numbers():
    text = "a^[1. Reg. 23.] b^[4. Reg. 13.] c^[1. Cor. 4.] d^[35. Editor's note: typo.]"
    assert asm.renumber_footnotes(text, numbered_author_notes=False) == (
        "a^[1. Reg. 23.] b^[4. Reg. 13.] c^[1. Cor. 4.] d^[1. Editor's note: typo.]"
    )


def test_assembly_preserves_unnumbered_author_citations(tmp_path):
    write(tmp_path, 1, "Textus^[1. Reg. 23.] est.^[7. Editor's note: typo.]\n")
    page, errors = asm.load_page(tmp_path / "p001.md", 1)
    assert not errors
    result = asm.assemble([page], numbered_author_notes=False)
    assert not result.errors
    assert result.sections["assembled"] == "Textus^[1. Reg. 23.] est.^[1. Editor's note: typo.]"
