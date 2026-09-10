from exscriptor.edition_rules import (
    expand_ligatures, drop_closing_markers, VERBATIM_BLOCKS,
    AUTHOR_ZONE, COMMENTATOR_ZONE,
)


def test_ligatures():
    assert expand_ligatures("æterna œconomia") == "aeterna oeconomia"
    assert expand_ligatures("Ægyptus") == "Aegyptus"


def test_ligatures_in_all_caps_tokens():
    """An all-caps token takes AE/OE, not Ae/Oe.

    The one-letter-case mismatch is not cosmetic: the value is a display
    heading, a section title and a manifest key, and `QUAeSTIO III.` is a
    form nothing downstream matches.
    """
    assert expand_ligatures("QUÆSTIO III.") == "QUAESTIO III."
    assert expand_ligatures("THEOLOGIÆ") == "THEOLOGIAE"
    assert expand_ligatures("DUBIUM UNICUM. DE CŒLO") == "DUBIUM UNICUM. DE COELO"
    # mixed case inside one token keeps the soft form
    assert expand_ligatures("Præfatio") == "Praefatio"
    # a lower-case ligature inside an all-caps token still uppercases
    assert expand_ligatures("QUæSTIO") == "QUAESTIO"
    # idempotent
    for src in ("QUÆSTIO III.", "æterna", "Ægyptus"):
        assert expand_ligatures(expand_ligatures(src)) == expand_ligatures(src)


def test_closing_markers_dropped():
    text = "<<<AUTHOR>>>\nbody\n<</Author>>>\n"
    assert "<</" not in drop_closing_markers(text)
    assert "body" in drop_closing_markers(text)


def test_zone_names():
    assert AUTHOR_ZONE == "AUTHOR"
    assert COMMENTATOR_ZONE == "COMMENTATOR"
    assert f"{AUTHOR_ZONE}-MARGINALIA" in VERBATIM_BLOCKS
