from exscriptor.script_screen import screen_files, suspicious


def test_cyrillic_lookalikes_are_high():
    hits = suspicious("quia radic\u0435 jam explicata, et \u0430liter")
    assert len(hits["high"]) == 2
    assert not hits["low"]


def test_greek_quotation_is_low_not_high():
    hits = suspicious("ut habet \u03bb\u03cc\u03b3\u03bf\u03c2 Arist.")
    assert hits["high"] == []
    assert hits["low"]


def test_comment_layer_excluded_by_default():
    assert suspicious("recte dicitur <!-- notes: \u0435 -->")["high"] == []
    assert suspicious("recte dicitur <!-- notes: \u0435 -->", strip_comments=False)["high"]


def test_clean_latin():
    assert suspicious("recte dicitur, prout in se est.") == {"high": [], "low": []}


def test_fullwidth_is_high():
    assert suspicious("DIC\uFF34O")["high"]


def test_screen_files_and_context(tmp_path):
    f = tmp_path / "p001.md"
    f.write_text("radic\u0435 jam explicata\n")
    report = screen_files([f])
    assert len(report) == 1
    assert report[0]["high"][0]["count"] == 1
    assert "radic" in report[0]["high"][0]["contexts"][0]


def test_math_brackets_are_not_lookalikes():
    # a pipeline may legitimately use ⟦ ⟧ as its own flag markers
    assert suspicious("verbum \u27e6dubium?\u27e7 recte") == {"high": [], "low": []}
