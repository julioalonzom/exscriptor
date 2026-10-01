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
