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


from exscriptor.check_markers import markup_issues


def test_balanced_italics_are_clean():
    assert markup_issues("text *italic* more *italic* end\n", "p1") == []


def test_unbalanced_italic_flagged():
    issues = markup_issues("text *opens and never closes\n", "p663")
    assert any("unbalanced italic markers" in i for i in issues)


def test_bold_heading_markers_do_not_count_as_italics():
    assert markup_issues("**§ II.**\n\ntext *a* and *b*\n", "p2") == []


def test_forbidden_triple_asterisk_heading():
    issues = markup_issues("***Resolutio dubii, quoad secundam partem.***\n", "p729")
    assert any("forbidden heading form" in i for i in issues)


def test_canonical_bold_italic_heading_is_clean():
    assert markup_issues("**§ II. *Resolutio dubii, quoad secundam partem*.**\n", "p729") == []


def test_odd_asterisks_on_one_line_flagged():
    issues = markup_issues("text *opens and never closes\n", "p663")
    assert any("unbalanced italic markers on one line" in i for i in issues)


def test_cross_page_span_closed_at_foot_is_clean():
    # the run's convention: close at the page foot, re-open at the next head
    assert markup_issues("*Nec propterea nego ullam maximam ex sen-*\n", "p148") == []


def test_bold_italic_subtitle_heading_is_clean():
    assert markup_issues("***Diluuntur argumenta initio adducta*.**\n", "p576") == []


def test_italic_run_opening_on_a_paragraph_number_is_not_stripped():
    # page-file convention: the italic run may open on the paragraph number
    assert markup_issues("*9 Ad primam respondet P. Herice, 1. part. tract. 1.*\n", "p494") == []


def test_apparatus_keys_ignored_when_asked():
    zoned = "<<<AUTHOR>>>\ntext [*1] and [*2]\n<<<AUTHOR-MARGINALIA>>>\n*1 a note\n*2 another\n"
    assert markup_issues(zoned, "p1", apparatus_keys=True) == []


from exscriptor.check_markers import wrap_issues


def test_hard_wrapped_page_flagged():
    page = "\n\n".join([
        "Probatur primo, quia sicut aliquid est",
        "in genere causæ, ita est",
        "in genere effectus, et",
        "hoc patet ex dictis.",
    ]) + "\n"
    assert wrap_issues(page, "p474")


def test_paragraph_per_line_is_clean():
    page = ("Probatur primo, quia sicut aliquid est in genere causæ, ita est in genere effectus, et hoc patet ex dictis.\n\n"
            "Secundo arguitur contra hanc sententiam, quia repugnat perfectioni divinæ, ut supra ostensum est.\n\n"
            "Tertio, quia sequeretur Deum non esse primam causam omnium rerum, quod est absurdum.\n")
    assert wrap_issues(page, "p500") == []


def test_single_seam_break_is_tolerated():
    page = "text that continues onto\n\nmore of the same paragraph here, and then it closes.\n"
    assert wrap_issues(page, "p1") == []
