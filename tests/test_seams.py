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
