from exscriptor.ct_oracle import word_set, collate


def test_word_set():
    assert word_set("Verbum caro factum est.") == {"verbum", "caro", "factum", "est"}


def test_collate_reports_both_directions():
    r = collate(" vide ", "")  # ratio guards against div-by-zero
    assert r["ratio"] >= 0
    r2 = collate("alpha beta", "beta gamma")
    assert r2["only_ours"] == ["alpha"]
    assert r2["only_gold"] == ["gamma"]
