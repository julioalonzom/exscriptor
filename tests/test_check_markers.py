import os

from exscriptor.check_markers import check_page

ZONED = """<<<AUTHOR>>>
text [*1] and [*2]
<<<AUTHOR-MARGINALIA>>>
*1 a note
*2 another
<<<AUTHOR-APPARATUS>>>
1) apparatus
"""


def test_clean_page():
    assert check_page(ZONED, "pg-001") == []


def test_missing_marginalia():
    bad = ZONED.replace("*2 another\n", "")
    issues = check_page(bad, "pg-002")
    assert any("has no marginalia line" in i for i in issues)


from exscriptor.check_markers import comment_issues


def test_balanced_comment_layer_is_clean():
    assert comment_issues("body text\n\n<!-- notes: marginals: x | flags: none -->\n", "p1") == []


def test_unterminated_comment_is_flagged():
    issues = comment_issues("body text\n\n<!-- notes: marginals: x | band geometry: y\n", "p491")
    assert any("unbalanced HTML comment" in i for i in issues)
    assert any("leaked into the body" in i for i in issues)


def test_leaked_note_vocabulary_is_flagged():
    issues = comment_issues("body text | marginals (dropped): none\n", "p2")
    assert any("vocabulary" in i for i in issues)
