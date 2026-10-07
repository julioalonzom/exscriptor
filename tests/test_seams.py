from exscriptor import seams


def test_emphasized_list_labels_are_not_lowercase_starts():
    # house style sets list labels in italics: "*a)* ..." is a list item, not a seam
    text = "Thesis dicit.\n\n*a)* primum punctum est.\n\n*b)* secundum punctum est."
    assert not [v for v in seams.seam_violations(text) if v[1] == "LOWER-START"]


def test_lowercase_continuation_still_flagged():
    text = "Et ideo sequitur\n\nsed continuatio."
    assert any(v[1] == "LOWER-START" for v in seams.seam_violations(text))
