from exscriptor.pieces import join


def test_join_continues_paragraphs_and_hyphens():
    pieces = ["<<<THOMAS>>>\nSed contra est quod\n⟨CONT⟩\n", "dicitur in li-\n⟨CONT⟩", "bro.\n\nAlia para.", "<<<CAIETANUS>>>\nTitulus."]
    assert join(pieces) == "<<<THOMAS>>>\nSed contra est quod dicitur in libro.\n\nAlia para.\n\n<<<CAIETANUS>>>\nTitulus.\n"


def test_join_merges_emphasis_split_at_a_cut():
    assert join(["*Non potuerunt.*\n⟨CONT⟩", "*Unde illi* dicit."]) == "*Non potuerunt. Unde illi* dicit.\n"
    assert join(["**AD PRIMUM**\n⟨CONT⟩", "**ERGO** dicendum"]) == "**AD PRIMUM ERGO** dicendum\n"
