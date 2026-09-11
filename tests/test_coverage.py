from exscriptor.coverage import coverage, coverage_detail, parse_pages, witness_text

WITNESS = "Nam sicut specificatio sumitur a forma, ita individuatio a materia."


def test_identical_scores_full():
    assert coverage(WITNESS, WITNESS) > 0.999


def test_omission_fails():
    assert coverage("Nam sicut specificatio sumitur a forma.", WITNESS) < 0.75


def test_fabrication_fails():
    padded = WITNESS + (
        " Unde haec objectio non destruit conclusionem nostram, ideo in praesenti "
        "consulto omittimus, ut ex dictis constat omnino."
    )
    assert coverage(padded, WITNESS) < 0.90


def test_empty_is_zero():
    assert coverage("", WITNESS) == 0.0


def test_accent_case_punct_insensitive():
    noisy = "NAM sícut specificátio, sumitur: a forma, ita individuátio a matériá."
    assert coverage(noisy, WITNESS) > 0.9


def test_long_s_insensitive():
    assert coverage("ſpecificatio ſumitur", "specificatio sumitur") > 0.95


def test_detail_directions():
    score, recall, precision = coverage_detail(WITNESS, WITNESS)
    assert all(v > 0.999 for v in (score, recall, precision))
    score, recall, precision = coverage_detail("Nam sicut", WITNESS)
    assert recall < 0.2 and precision > 0.99


def test_witness_key_shapes():
    assert witness_text({"pg-12.jpg": "x"}, 12, ["pg-{page}.jpg"]) == "x"
    assert witness_text({"pg-012.jpg": "x"}, 12, ["pg-{page03}.jpg"]) == "x"
    assert witness_text({"12": {"left": "a", "right": "b"}}, 12, ["{page}"]) == "a b"
    assert witness_text({"12": {"text": "a"}}, 12, ["{page}"]) == "a"
    assert witness_text({}, 12, ["{page}"]) is None


def test_parse_pages():
    assert parse_pages("1-3,7") == [1, 2, 3, 7]
