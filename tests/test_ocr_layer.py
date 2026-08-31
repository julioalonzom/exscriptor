from editionist.ocr_layer import words


def test_words():
    assert words("Verbum, caro! Æterna") == ["Verbum", "caro", "Æterna"]
