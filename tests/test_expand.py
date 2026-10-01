from collections import Counter

from typer.testing import CliRunner

from exscriptor import expand as ex
from exscriptor import lexicon as lx

LEX = Counter({"non": 274477, "nom": 280, "tamen": 41400, "voluntas": 900, "vel": 30000, "uel": 3,
               "universalis": 500, "quod": 90000, "pravorum": 46, "sed": 50000, "sit": 40000,
               "fit": 9000, "concursum": 50, "numquam": 999, "nunquam": 2507, "praecisam": 3,
               "obiectum": 800, "aeternus": 300, "et": 900000,
       "voluit": 5000, "volvit": 40, "ut": 80000, "vt": 2})


def run(text, **kw):
    kw.setdefault("rules", [])
    kw.setdefault("decisions", [])
    kw.setdefault("lexicon", LEX)
    return ex.expand_text(text, "p001", **kw)


def test_builtin_and_lexicon_decisions():
    r = run("Nõ uel prauorum & æternus, tamẽ obiectũ ſed &c. QVOD")
    assert r.text == "Non vel pravorum et aeternus, tamen obiectum sed etc. QUOD"
    methods = Counter(m for _, _, m, _ in r.changes)
    assert methods["lexicon"] >= 5 and methods["rule"] >= 3
    assert r.pending == []


def test_marks_without_a_decision_stay_and_are_pending():
    r = run("ꝓcisam nũquam tõpus")
    assert r.text == "ꝓcisam nũquam tõpus"
    assert [(t, s) for t, _, s, _ in r.pending] == [("ꝓcisam", "other-marks"), ("nũquam", "variant"),
                                                     ("tõpus", "none")]


def test_table_rules_and_editor_decisions_win():
    rules = [ex.Rule("ꝓ", "pro", "literal"), ex.Rule(r"^(.*)q;$", r"\1que", "regex",
                                                    __import__("re").compile(r"^(.*)q;$"))]
    dec = [ex.Decision("p001", "ꝓcisam", "1", "praecisam", "scan", "p. 4: p-bar, not p-loop")]
    r = run("ꝓcisam ꝓcisam ꝓ", rules=rules, decisions=dec)
    # 2nd occurrence: the table yields a non-word, so it waits for the editor
    assert r.text == "praecisam ꝓcisam ꝓ"
    assert [(t, s) for t, _, s, _ in r.pending] == [("ꝓcisam", "rule-oov"), ("ꝓ", "rule-oov")]


def test_prefer_breaks_a_variant_by_the_editions_habit():
    r = run("nũquam", prefer=Counter({"numquam": 4}))
    assert r.text == "numquam"


def test_comments_copied_untouched():
    r = run("nõ <!-- notes: nõ as printed -->")
    assert r.text == "non <!-- notes: nõ as printed -->"


def test_long_s_report():
    rows = ex.long_s_report(["fed fit"], LEX)
    assert ("fed", 1, "sed", 50000, "misread") in rows
    assert ("fit", 1, "sit", 40000, "context") in rows


def test_cli_writes_edition_and_record_and_blocks_on_pending(tmp_path):
    (tmp_path / "dip").mkdir()
    (tmp_path / "dip/p001.md").write_text("Nõ uel tõpus.\n")
    lexf = tmp_path / "lex.json"
    lx.save(LEX, lexf, 1)
    args = ["--pages", str(tmp_path / "dip/*.md"), "--out-dir", str(tmp_path / "ed"),
            "--record", str(tmp_path / "expansions.tsv"), "--lexicon", str(lexf)]
    r = CliRunner().invoke(ex.app, ["run"] + args)
    assert r.exit_code == 1 and "pending" in r.output
    (tmp_path / "decisions.tsv").write_text("page\ttoken\toccurrence\tedition\tmethod\tevidence\n"
                                            "p001\ttõpus\t1\ttempus\tscan\tp. 1 line 3: e with bar\n")
    r = CliRunner().invoke(ex.app, ["run"] + args + ["--decisions", str(tmp_path / "decisions.tsv")])
    assert r.exit_code == 0, r.output
    assert (tmp_path / "ed/p001.md").read_text() == "Non vel tempus.\n"
    assert "tõpus\ttempus\tscan" in (tmp_path / "expansions.tsv").read_text()


def test_accents_and_capital_v():
    r = run("Quòd à verò SVMMARIVM QVAESTIO XIV aër")
    assert r.text == "Quod a vero SUMMARIUM QUAESTIO XIV aër"


def test_allowed_tokens_kept_verbatim():
    assert run("Peñà cùm", keep={"Peñà"}).text == "Peñà cum"


def test_medial_v_is_never_varied():
    assert run("volvit voluit vt uoluit").text == "volvit voluit ut voluit"


def test_small_caps_v_and_vowel_u_fallback():
    assert run("Qvibvs vbiqve concursiua QVibus").text == "Quibus ubique concursiva QUibus"


def test_brief_lists_each_mark_with_code_points(tmp_path):
    table = tmp_path / "abbreviations.tsv"
    table.write_text("pattern\texpansion\tkind\tnote\tglyph\n"
                     "ꝓ\tpro\tliteral\tp with loop through the descender, p. 12\t\n"
                     "^(.*)q;$\t\\1que\tregex\tsemicolon after q at a word's end\tq;\n")
    out = CliRunner().invoke(ex.app, ["brief", str(table)]).output
    assert "`ꝓ` (U+A753) -- p with loop" in out
    assert "`q;`" in out and "ſ (U+017F)" in out


def test_non_letter_marks_expand_in_running_text():
    r = run("Deus ⁊ homo <!-- notes: ⁊ seen -->", rules=[ex.Rule("÷", "est", "literal")])
    assert r.text == "Deus et homo <!-- notes: ⁊ seen -->"
    assert run("id ÷ verum", rules=[ex.Rule("÷", "est", "literal")]).text == "id est verum"
