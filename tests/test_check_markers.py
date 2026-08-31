from exscriptor.check_markers import check_page

ZONED = """<<<THOMAS>>>
text [*1] and [*2]
<<<THOMAS-MARGINALIA>>>
*1 a note
*2 another
<<<THOMAS-APPARATUS>>>
1) apparatus
"""


def test_clean_page():
    assert check_page(ZONED, "pg-001") == []


def test_missing_marginalia():
    bad = ZONED.replace("*2 another\n", "")
    issues = check_page(bad, "pg-002")
    assert any("has no marginalia line" in i for i in issues)
