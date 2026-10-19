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


def test_lettered_list_marker_starts_a_paragraph():
    # a page that ends mid-list: the next item opens a new paragraph
    assert asm.join_kind("Ps. XXXIX. 7. sqq.", "γ) Sacerdotium Christi praedicitur") == "para"
    assert asm.join_kind("Io. X. 16.", "*b)* Hic unus pastor") == "para"
    assert asm.join_kind("et ideo", "b) nisi quod") == "para"
    # a lowercase word that merely starts with a letter is still a continuation
    assert asm.join_kind("et ideo", "bona voluntas") == "space"


def test_closing_guillemet_after_space_is_terminal():
    assert asm.join_kind("generale Concilium. »", "2°. De eadem") == "para"
    assert asm.join_kind("generale Concilium. »", "de eadem") == "space"


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


def test_footnote_closed_on_both_halves_closes_once():
    text, _, errors = asm.join_pages([
        page(1, "Corpus.^[1. Nota incipit ⟦NOTE-CONTINUES⟧]. Post."),
        page(2, "⟦CONTINUED-NOTE⟧ et finitur.]\n\nAlius."),
    ])
    assert errors == []
    assert "^[1. Nota incipit et finitur.]. Post." in text
    assert "]]" not in text


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


def test_split_honours_a_per_section_node():
    # A level that is sometimes a leaf and sometimes a container (a quaestio
    # heading straight into its first Articulus) marks itself "node": true;
    # it emits no section, and does not need its type in node_types.
    structure = {
        "headings": {"quaestio": r"^\*\*QUAESTIO\b", "articulus": r"^\*\*ARTICULUS\b"},
        "sections": [
            {"key": "q1", "type": "quaestio", "node": True},
            {"key": "q1a1", "type": "articulus", "parent": "q1"},
            {"key": "q1a2", "type": "articulus", "parent": "q1"},
            {"key": "q2", "type": "quaestio"},
        ],
    }
    text = ("**QUAESTIO I.**\n\n**ARTICULUS I.**\n\nPrimus.\n\n**ARTICULUS II.**\n\nSecundus.\n\n"
            "**QUAESTIO II.**\n\nTertius.\n")
    out, errors = asm.split_sections(text, structure)
    assert errors == []
    assert out == {"q1a1": "Primus.", "q1a2": "Secundus.", "q2": "Tertius."}


def test_split_keeps_body_glued_onto_bold_heading():
    # A page join can glue body text onto a bold heading's line
    # ("**Cap. XXII. ...** lationes ..."). The glued body must stay in
    # the section, not vanish with the heading line.
    structure = {
        "headings": {"caput": r"^\*\*Cap\. [IVXLCDM]+\."},
        "sections": [
            {"key": "c1", "type": "caput"},
            {"key": "c2", "type": "caput"},
        ],
    }
    text = "**Cap. I. De fide.** Glued corpus that must survive.\n\n**Cap. II.** Aliud.\n"
    out, errors = asm.split_sections(text, structure)
    assert errors == []
    assert out["c1"] == "Glued corpus that must survive."
    assert out["c2"] == "Aliud."


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


def test_fused_note_and_body_block_is_not_held():
    # A trailing block that fuses a margin note with body prose must stay
    # put: holding it past the next page would move body text out of order.
    text, report, errors = asm.join_pages([
        page(1, "Principium.\n\n^[1. Ad primum.] Ad primum dicitur quod non"),
        page(2, "procedit consequentia. Finis."),
    ])
    assert errors == []
    assert text == ("Principium.\n\n^[1. Ad primum.] Ad primum dicitur quod non "
                    "procedit consequentia. Finis.")
    assert not any("page-foot notes held" in r for r in report)


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


def test_a_range_that_ends_inside_a_section_is_not_an_open_tail():
    """Reading a work wave by wave assembles a growing prefix: the last
    section then stops mid-sentence because its later pages are unread, not
    because the print stops there. The structure's printed_end tells them
    apart, so the wave check passes while the section is still incomplete."""
    structure = {
        "headings": {"caput": r"^\*\*CAPUT [IVX]+\."},
        "sections": [
            {"key": "c1", "type": "caput", "parent": None, "printed_start": 1, "printed_end": 4},
            {"key": "c2", "type": "caput", "parent": None, "printed_start": 5, "printed_end": 9},
        ],
    }
    pages = [page(1, "**CAPUT I.**\n\nPrimum capitulum"), page(2, "et medium capituli")]
    # the range stops at page 2 and the structure says c1 runs on to page 4:
    # the open tail is the range's edge, not a print defect
    part = asm.assemble(pages, structure=structure)
    assert part.errors == []
    assert part.truncated_tail == "c1"
    # the same pages, when the structure says the section ends at page 2,
    # must still end a sentence — the check is not weakened
    structure["sections"][0]["printed_end"] = 2
    closed = asm.assemble(pages, structure=structure)
    assert [e for e in closed.errors if "TAIL-TERMINAL" in e]
    assert closed.truncated_tail is None
    # a page that hands its paragraph on (joins-next: space) is the range's
    # edge even when the structure's printed_end agrees with the last page
    handoff = [page(1, "**CAPUT I.**\n\nPrimum capitulum"),
               page(2, "et medium capituli", "joins-next: space")]
    carried = asm.assemble(handoff, structure=structure)
    assert carried.errors == []
    assert carried.truncated_tail == "c1"


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


def test_marginal_tag_is_dropped_and_note_kept():
    result = asm.assemble([page(1, "Qui dicebatur Possessor.^[⟦M⟧ *Habetur in bibliotheca.*] Et Gelasius dixit.")])
    body = result.sections["assembled"]
    assert "⟦M⟧" not in body and "Habetur in bibliotheca" in body
    assert not [e for e in result.errors if "sentinel" in e]


@pytest.mark.parametrize("name", ["Thomae", "Aug."])
def test_saint_initial_continues_across_page_boundary(name):
    first = "Hanc sententiam docet S."
    second = name + " in libro citato."
    text, report, errors = asm.join_pages([page(1, first), page(2, second)])
    assert text == first + " " + second
    assert errors == []
    assert asm.join_kind(first, "**II.** Alia sententia.") == "para"
    assert asm.join_kind("Finis est.", "Thomae sententia sequitur.") == "para"


def test_drop_layers_joins_across_dropped_zone():
    text = ("symbola\n<<<PLATES>>>\nplate words\n<<<END PLATES>>>\necclesiastica antiquitatis."
            "\n\nNovus. \n<<<PLATES>>>\nx\n<<<END PLATES>>>\n\nAlter.")
    kept, report, errors = asm.drop_layers(text, ("PLATES",))
    assert errors == []
    assert "<<<" not in kept
    assert "symbola ecclesiastica antiquitatis." in kept
    assert "Novus.\n\nAlter." in kept
    assert any("joined across dropped PLATES" in r for r in report)


def test_drop_layers_hyphen_joins_across_dropped_zone():
    text = "prin-\n<<<PLATES>>>\nx\n<<<END PLATES>>>\ncipium"
    kept, _, errors = asm.drop_layers(text, ("PLATES",))
    assert errors == []
    assert kept.replace("\n", " ").strip() == "principium"


def test_join_pages_keeps_zone_markers_on_own_lines():
    pages = [page(1, "symbola"), page(2, "<<<PLATES>>>\nx\n<<<END PLATES>>>"), page(3, "ecclesiastica.")]
    text, _, errors = asm.join_pages(pages)
    assert errors == []
    assert "<<<PLATES>>>\n" in text
    kept, _, errors = asm.drop_layers(text, ("PLATES",))
    assert errors == [] and "<<<" not in kept
    assert "symbola ecclesiastica." in kept


def scan_join_case(tmp_path, left="Finis est.", right="Addunt tamen aliquid."):
    write(tmp_path, 1, left + "\n\n<!-- notes: joins-next: space -->")
    write(tmp_path, 2, right)
    pages = [asm.load_page(tmp_path / f"p{n:03d}.md", n)[0] for n in (1, 2)]
    decisions = {"p001->p002": {
        "join": "space", "left_sha256": pages[0].sha256,
        "right_sha256": pages[1].sha256,
        "evidence": "Scan shows flush-left continuation; the next paragraph is indented.",
    }}
    path = tmp_path / "joins.json"
    args = ["--pages", str(tmp_path / "p{n:03d}.md"), "--range", "1-2",
            "--out-dir", str(tmp_path / "out"), "--join-decisions", str(path)]
    return args, path, decisions


def test_scan_adjudicated_join_preserves_printed_paragraph(tmp_path):
    args, path, decisions = scan_join_case(tmp_path)
    path.write_text(json.dumps(decisions))
    result = CliRunner().invoke(asm.app, args)
    assert result.exit_code == 0, result.output
    assert (tmp_path / "out/assembled.md").read_text() == "Finis est. Addunt tamen aliquid.\n"
    record = json.loads((tmp_path / "out/ASSEMBLY.json").read_text())
    assert record["join_decisions"] == decisions


@pytest.mark.parametrize("field,value,reason", [
    ("left_sha256", "stale", "hash"),
    ("right_sha256", "stale", "hash"),
    ("join", "unknown", "join"),
    ("evidence", "", "evidence"),
    ("decision", None, "invalid join decision"),
])
def test_invalid_scan_join_refuses_to_write(tmp_path, field, value, reason):
    args, path, decisions = scan_join_case(tmp_path)
    if field == "decision":
        decisions["p001->p002"] = value
    else:
        decisions["p001->p002"][field] = value
    path.write_text(json.dumps(decisions))
    result = CliRunner().invoke(asm.app, args)
    assert result.exit_code == 1, result.output
    assert reason in result.output.lower()
    assert not (tmp_path / "out").exists()


def test_unadjudicated_declared_join_mismatch_refuses_in_decision_mode(tmp_path):
    args, path, _ = scan_join_case(tmp_path)
    path.write_text("{}")
    result = CliRunner().invoke(asm.app, args)
    assert result.exit_code == 1, result.output
    assert "adjudication required" in result.output
    assert not (tmp_path / "out").exists()


def test_adjudicated_continuation_holds_page_foot_notes(tmp_path):
    args, path, decisions = scan_join_case(tmp_path, "Textus.\n\n^[Nota.]", "Continuatio.")
    path.write_text(json.dumps(decisions))
    result = CliRunner().invoke(asm.app, args)
    assert result.exit_code == 0, result.output
    assert (tmp_path / "out/assembled.md").read_text() == "Textus. Continuatio.\n\n^[Nota.]\n"


@pytest.mark.parametrize("value", [None, [], "not an object"])
def test_join_decision_file_requires_object(tmp_path, value):
    args, path, _ = scan_join_case(tmp_path)
    path.write_text(json.dumps(value))
    result = CliRunner().invoke(asm.app, args)
    assert result.exit_code == 1, result.output
    assert "must be an object" in result.output
    assert not (tmp_path / "out").exists()


def test_unknown_decision_boundary_refuses(tmp_path):
    args, path, decisions = scan_join_case(tmp_path)
    decisions["p001->p003"] = decisions.pop("p001->p002")
    path.write_text(json.dumps(decisions))
    result = CliRunner().invoke(asm.app, args)
    assert result.exit_code == 1, result.output
    assert "unknown join decision boundary" in result.output
    assert not (tmp_path / "out").exists()


def test_adjudicated_hyphen_continuation_holds_page_foot_notes(tmp_path):
    args, path, decisions = scan_join_case(tmp_path, "Textus in-\n\n^[Nota.]", "cipit.")
    left = tmp_path / "p001.md"
    left.write_text(left.read_text().replace("joins-next: space", "joins-next: hyphen"))
    decisions["p001->p002"].update(join="hyphen", left_sha256=asm.load_page(left, 1)[0].sha256)
    path.write_text(json.dumps(decisions))
    result = CliRunner().invoke(asm.app, args)
    assert result.exit_code == 0, result.output
    assert (tmp_path / "out/assembled.md").read_text() == "Textus incipit.\n\n^[Nota.]\n"


@pytest.mark.parametrize('rubric', ['Summa rei.', '*Summa rei.*'])
def test_paragraph_rubric_becomes_italic_run_in_after_numeral(rubric):
    result = asm.assemble([page(1, f'**12.** Corpus^[⟦M⟧⟦R⟧ {rubric}] est.^[7. Nota.]')])
    assert result.errors == []
    assert result.sections['assembled'] == '**12.** *Summa rei*.— Corpus est.^[1. Nota.]'


def test_rubric_on_later_page_moves_to_joined_paragraph_start():
    result = asm.assemble([page(1, 'Corpus incipit et'),
                           page(2, 'sequitur^[⟦M⟧⟦R⟧ Summa] usque ad finem.')])
    assert result.errors == []
    assert result.sections['assembled'] == '*Summa*.— Corpus incipit et sequitur usque ad finem.'


def test_rubric_moves_after_section_splitting_and_preserves_other_notes():
    result = asm.assemble([page(1, '**CAPUT I.** Corpus^[⟦M⟧⟦R⟧ Summa.] est.^[⟦M⟧ Aug. lib. 1.]^[9. Nota.]')],
                          structure={'headings': {'cap': r'^\*\*CAPUT'},
                                     'sections': [{'key': 'c1', 'type': 'cap'}]})
    assert result.errors == []
    assert result.sections['c1'] == '*Summa*.— Corpus est.^[Aug. lib. 1.]^[1. Nota.]'


@pytest.mark.parametrize('body', [
    'Corpus^[⟦M⟧⟦R⟧ ] est.',
    "Corpus^[⟦M⟧⟦R⟧ Summa^[Editor's note: sic.]] est.",
    'Corpus^[⟦M⟧⟦R⟧ Summa est.',
    'Corpus^[⟦M⟧⟦R⟧ *Summa] est.',
    'Corpus^[⟦M⟧ Citation ⟦R⟧ Summa] est.',
    'Corpus^[1. Nota^[⟦M⟧⟦R⟧ Summa]] est.',
])
def test_ambiguous_or_malformed_rubric_refuses(body):
    result = asm.assemble([page(1, body)])
    assert any('rubric' in error for error in result.errors)


def test_rubric_preserves_roman_paragraph_numeral():
    result = asm.assemble([page(1, '**XII.** Corpus^[⟦M⟧⟦R⟧ Summa.] est.')])
    assert result.errors == []
    assert result.sections['assembled'] == '**XII.** *Summa*.— Corpus est.'


@pytest.mark.parametrize('numbered', [True, False])
def test_rubrics_preserve_footnote_sequence_across_sections(numbered):
    result = asm.assemble([page(1, '**CAPUT I.**\n\nCorpus^[⟦M⟧⟦R⟧ Summa] est.^[8. Editor\'s note: sic.]'
                                  '\n\n**CAPUT II.**\n\nAliud^[⟦M⟧⟦R⟧ Alia] est.^[9. Editor\'s note: sic.]')],
                          structure={'headings': {'cap': r'^\*\*CAPUT'},
                                     'sections': [{'key': 'c1', 'type': 'cap'}, {'key': 'c2', 'type': 'cap'}]},
                          numbered_author_notes=numbered)
    assert result.errors == []
    assert result.sections == {'c1': "*Summa*.— Corpus est.^[1. Editor's note: sic.]",
                               'c2': "*Alia*.— Aliud est.^[2. Editor's note: sic.]"}


def test_numeral_anchored_note_stays_before_run_in_rubric():
    result = asm.assemble([page(1, '**12.**^[8. Nota.] Corpus^[⟦M⟧⟦R⟧ Summa.] est.')])
    assert result.errors == []
    assert result.sections['assembled'] == '**12.**^[1. Nota.] *Summa*.— Corpus est.'


def test_editorial_note_cannot_be_a_rubric():
    result = asm.assemble([page(1, "Corpus^[⟦M⟧⟦R⟧ Editor's note: Summa.] est.")])
    assert any('rubric' in error for error in result.errors)


@pytest.mark.parametrize('second', ['Summa.', 'Alia ratio.'])
def test_multiple_rubrics_preserve_each_summary_in_print_order(second):
    result = asm.assemble([page(1, f'**12.** Corpus^[⟦M⟧⟦R⟧ Summa.] est^[⟦M⟧⟦R⟧ {second}].^[7. Nota.]')])
    assert result.errors == []
    assert result.sections['assembled'] == f'**12.** *Summa*.— *{second[:-1]}*.— Corpus est.^[1. Nota.]'


def test_complementary_rubrics_on_joined_pages_stay_in_print_order():
    result = asm.assemble([page(1, '**III.** Corpus^[⟦M⟧⟦R⟧ Prima ratio.] incipit et'),
                           page(2, 'sequitur^[⟦M⟧⟦R⟧ Secunda ratio.] usque ad finem.')])
    assert result.errors == []
    assert result.sections['assembled'] == '**III.** *Prima ratio*.— *Secunda ratio*.— Corpus incipit et sequitur usque ad finem.'


def test_explicit_editor_note_travels_with_rubric_not_with_body_anchor():
    result = asm.assemble([page(1, "**II.** Corpus^[⟦M⟧⟦R⟧ S. Aug. doctrina H. S. Prospero commendata.]^[⟦R-NOTE⟧ Editor's note: the print has H. before S. Prospero.] est.^[7. Nota.]")])
    assert result.errors == []
    assert result.sections['assembled'] == "**II.** *S. Aug. doctrina H. S. Prospero commendata*^[1. Editor's note: the print has H. before S. Prospero.].— Corpus est.^[2. Nota.]"


def test_each_rubric_keeps_its_own_explicit_editor_note_in_order():
    result = asm.assemble([page(1, "Corpus^[⟦M⟧⟦R⟧ Prima.]^[⟦R-NOTE⟧ 8. Editor's note: primum.] et^[⟦M⟧⟦R⟧ Secunda.]^[⟦R-NOTE⟧ Editor's note: secundum.] finis.")])
    assert result.errors == []
    assert result.sections['assembled'] == "*Prima*^[1. Editor's note: primum.].— *Secunda*^[2. Editor's note: secundum.].— Corpus et finis."


def test_adjacent_editor_note_without_attachment_marker_keeps_body_anchor():
    result = asm.assemble([page(1, "Corpus^[⟦M⟧⟦R⟧ Summa.]^[Editor's note: corpus.] est.")])
    assert result.errors == []
    assert result.sections['assembled'] == "*Summa*.— Corpus^[1. Editor's note: corpus.] est."


@pytest.mark.parametrize('body', [
    "Corpus^[⟦R-NOTE⟧ Editor's note: sic.] est.",
    "Corpus^[⟦M⟧⟦R⟧ Summa.] ^[⟦R-NOTE⟧ Editor's note: sic.] est.",
    "Corpus^[⟦M⟧⟦R⟧ Summa.]^[⟦R-NOTE⟧ Citation.] est.",
    "Corpus^[⟦M⟧⟦R⟧ Summa.]^[⟦R-NOTE⟧ Editor's note: sic. est.",
])
def test_misplaced_or_malformed_rubric_attachment_refuses(body):
    result = asm.assemble([page(1, body)])
    assert any('rubric' in error for error in result.errors)
