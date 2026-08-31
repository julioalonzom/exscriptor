from schola_digitization.edition_rules import (
    expand_ligatures, drop_closing_markers, VERBATIM_BLOCKS,
    AUTHOR_ZONE, COMMENTATOR_ZONE,
)


def test_ligatures():
    assert expand_ligatures("æterna œconomia") == "aeterna oeconomia"
    assert expand_ligatures("Ægyptus") == "Aegyptus"


def test_closing_markers_dropped():
    text = "<<<THOMAS>>>\nbody\n<</Thomas>>>\n"
    assert "<</" not in drop_closing_markers(text)
    assert "body" in drop_closing_markers(text)


def test_zone_names():
    assert AUTHOR_ZONE == "THOMAS"
    assert COMMENTATOR_ZONE == "CAIETANUS"
    assert f"{AUTHOR_ZONE}-MARGINALIA" in VERBATIM_BLOCKS
