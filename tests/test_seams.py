from exscriptor import seams


def test_emphasized_list_labels_are_not_lowercase_starts():
    # house style sets list labels in italics: "*a)* ..." is a list item, not a seam
    text = "Thesis dicit.\n\n*a)* primum punctum est.\n\n*b)* secundum punctum est."
    assert not [v for v in seams.seam_violations(text) if v[1] == "LOWER-START"]


def test_letter_marker_with_asterisks_around_the_letter_is_a_list_item():
    # Franzelin's print sets the letter alone in italics: "*a*) Nihil ..." is a list item
    text = "Thesis dicit.\n\n*a*) Nihil omnino aliud.\n\n*b*) Alii ex Patribus."
    assert not [v for v in seams.seam_violations(text) if v[1] == "LOWER-START"]


def test_superscript_ordinal_label_is_not_a_lowercase_start():
    # Franzelin's thesis lists: "1ᵐ *Testimonium*" and "3ⁱᵒ. Deus" open with a capital after the label
    text = "Thesis dicit.\n\n1ᵐ *Testimonium* citatum.\n\n3ⁱᵒ. Deus non est bonum formale."
    assert not [v for v in seams.seam_violations(text) if v[1] == "LOWER-START"]


def test_feminine_ordinal_label_is_not_a_lowercase_start():
    # Merkelbach numbers the cardinal virtues "1ª et praecipua est *prudentia*",
    # "2ª est *iustitia*" …: a number with an ordinal mark is a list label.
    text = ("Ordo est naturalis.\n\n1ª et praecipua est *prudentia*.\n\n"
            "2ª est *iustitia*.\n\n3ª est *fortitudo*.\n\n4ª est *temperantia*.")
    assert not [v for v in seams.seam_violations(text) if v[1] == "LOWER-START"]


def test_masculine_ordinal_label_is_not_a_lowercase_start():
    text = "Ordo est naturalis.\n\n1º est *prudentia*.\n\n2º est *iustitia*."
    assert not [v for v in seams.seam_violations(text) if v[1] == "LOWER-START"]


def test_latin_us_ordinal_label_with_lowercase_body_is_not_a_lowercase_start():
    # Merkelbach numbers the acts of prudence '**1ᵘˢ** est *consiliari*',
    # '**2ᵘˢ** est de inventis *iudicare*': the label is bold, and the body
    # after it begins lowercase — still a list item, not a split paragraph.
    text = ("Tres sunt actus.\n\n**1ᵘˢ** est *consiliari* seu *deliberare*.\n\n"
            "**2ᵘˢ** est de inventis *iudicare*.\n\n**3ᵘˢ** est iudicata *praecipere*.")
    assert not [v for v in seams.seam_violations(text) if v[1] == "LOWER-START"]


def test_superscript_modifier_letter_label_is_not_a_lowercase_start():
    # the same shape in the spacing-modifier block (U+02E2 'ˢ')
    text = "Tres sunt.\n\n1ˢ est *consiliari*.\n\n2ˢ est *iudicare*."
    assert not [v for v in seams.seam_violations(text) if v[1] == "LOWER-START"]


def test_emphasized_greek_letter_label_is_not_a_lowercase_start():
    # Franzelin's print italicizes the Greek label: "*β*) Consequenter" opens a list item
    text = "Thesis dicit.\n\n*β*) Consequenter probatur.\n\n*γ*) Tertium."
    assert not [v for v in seams.seam_violations(text) if v[1] == "LOWER-START"]


def test_lowercase_continuation_still_flagged():
    text = "Et ideo sequitur\n\nsed continuatio."
    assert any(v[1] == "LOWER-START" for v in seams.seam_violations(text))


def test_etc_before_a_capital_closes_the_paragraph():
    from exscriptor.seams import paragraph_boundary_findings as f
    assert not f("Sic dicit, ergo etc.\n\nTertio sic. Aliud.")
    assert f("Sic dicit, ergo etc.\n\nquod aliud est.")  # continuation stays flagged


def test_terminal_before_a_spaced_closing_guillemet_closes_the_sentence():
    # house style prints "eversivas. »": the period, a space, then the guillemet
    from exscriptor.seams import seam_violations as v
    assert not [x for x in v("Ita dicit.\n\nSed Concilium eversivas. »") if x[1] == "TAIL-TERMINAL"]
    assert [x for x in v("Ita dicit.\n\nSed Concilium eversivas »") if x[1] == "TAIL-TERMINAL"]


def test_english_ordinal_label_is_not_a_lowercase_start():
    # Franzelin's English thesis lists: "1st *Testimony* adduced" and "*5th Testimony:*" open after a full sentence
    text = "Thesis dicit.\n\n1st *Testimony* adduced by Gonet.\n\n*5th Testimony:* « The Apostle sets forth.»"
    assert not [v for v in seams.seam_violations(text) if v[1] == "LOWER-START"]


def test_lowercase_word_without_a_leading_numeral_is_still_flagged():
    text = "Thesis dicit.\n\nst alone and continue the sentence."
    assert [v for v in seams.seam_violations(text) if v[1] == "LOWER-START"]


def test_cut_note_ending_in_comma_is_flagged():
    text = "Corpus docet.^[12. Cf. supra p. 460,]\n\nNext block starts here."
    assert any(v[1] == "NOTE-END" for v in seams.note_violations(text))


def test_complete_note_with_period_passes():
    text = "Corpus docet.^[12. Vide S. Th. 2. 2. q. 1. a. 1.]\n\nNext block."
    assert seams.note_violations(text) == []


def test_note_ending_in_greek_passes():
    text = "Dicit.^[3. recte vertitur δευτερωσις]\n\nNext."
    assert seams.note_violations(text) == []


def test_note_ending_in_hebrew_passes():
    text = "Dicit.^[4. אֱוִיל הַנָּבִיא]\n\nNext."
    assert seams.note_violations(text) == []


def test_note_with_nested_brackets_reads_to_the_close():
    text = "Elevat.^[5. Although [we are elevated] not otherwise.] Next."
    assert seams.note_violations(text) == []


def test_note_ending_inside_emphasis_passes():
    text = "Certus.^[6. Est assensus *simpliciter certus.*]\n\nNext."
    assert seams.note_violations(text) == []


def test_note_ending_in_pointed_hebrew_passes():
    text = "Dicit.^[4. אֱוִיל הַנָּבִיא מְשֻׁגָּע אִישׁ הָרוּחַ]\n\nNext."
    assert seams.note_violations(text) == []


def test_quotation_display_lines_are_not_lowercase_starts():
    # Merkelbach p. 97: the print sets the syllogism's premises as indented
    # lines each opening «, so the third premise begins lowercase mid-sentence.
    text = ("Quo posito sic efformant sibi conscientiam certam :\n\n"
            "« Quod, omnibus diligenter consideratis, non est prohibitum est licitum.\n\n"
            "« Atqui haec actio hic et nunc ponenda certo non est mihi prohibita :\n\n"
            "« certum enim est legem incertam non obligare ;\n\n"
            "« atqui, quamvis potius existimem hanc legem existere et nunc obligare, tamen id non existimo cum certitudine etiam late dicta.\n")
    assert seams.seam_violations(text) == []
    assert seams.paragraph_boundary_findings(text) == []


def test_a_quoted_word_is_still_a_lowercase_start():
    text = ("Haec quidem dicta sunt.\n\n"
            "\"novam\" rem attulit Origenes, ut aiunt.\n")
    k = [v[1] for v in seams.seam_violations(text)]
    assert "LOWER-START" in k


def test_closing_dash_keeps_sentence_terminal_but_not_an_unfinished_clause():
    for text, unfinished in [
        ('Sententia completa. —', False),
        ('Clausula nondum completa —', True),
        ('Exemplum sequitur e. g. —', True),
    ]:
        findings = seams.seam_violations(text)
        assert any(kind == 'TAIL-TERMINAL' for _, kind, _ in findings) is unfinished


def test_markdown_table_is_not_prose_at_section_end():
    text = 'Figura sequitur.\n\n| A | B |\n|---|---|\n| albus | niger |'
    assert seams.seam_violations(text) == []


def test_malformed_table_does_not_hide_incomplete_prose():
    text = 'Figura sequitur.\n\n| A | B |\nunfinished clause'
    assert seams.seam_violations(text)


def test_markdown_table_with_lowercase_cells_is_not_lowercase_prose():
    text = 'Figura sequitur.\n\n| a | b |\n|---|---|\n| c | d |\n\nConclusio sequitur.'
    assert seams.seam_violations(text) == []


def test_strict_boundary_screen_ignores_complete_table_only():
    table = '| a | b |\n|---|---|\n| c | d |'
    assert seams.paragraph_boundary_findings('Exemplum.\n\n' + table) == []
    assert seams.paragraph_boundary_findings('Exemplum.\n\n| a | b |\nunfinished')


def test_table_does_not_hide_cut_prose_before_it():
    table = '| A | B |\n|---|---|\n| x | y |'
    assert any(v[1] == 'PAIR-SEAM' for v in seams.seam_violations('The principal causes the\n\n' + table))
    assert seams.seam_violations('The figures are:\n\n' + table) == []
