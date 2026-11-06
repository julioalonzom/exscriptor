from collections import Counter

from exscriptor.longs import align, classify, fold

LEX = Counter({fold(w): n for w, n in {
    "sit": 64000, "fit": 9000, "fiunt": 1800, "infusionem": 198, "sine": 14000, "fine": 3800,
    "insinuauit": 41, "perfusus": 18}.items()})


def test_both_directions_and_kinds():
    # Soto 1550's real failures: ſ written for f, and f for ſ
    assert classify("ſiunt", LEX)[:2] == ("oov", "fiunt")
    assert classify("inſuſionem", LEX)[:2] == ("oov", "infuſionem")
    assert classify("infinuauit", LEX)[:2] == ("oov", "inſinuauit")
    assert classify("fit", LEX)[:2] == ("dominated", "ſit")
    assert classify("fine", LEX)[:2] == ("pair", "ſine")


def test_quiet_cases():
    assert classify("ſit", LEX) is None          # page form 7x commoner: sampled, not listed
    assert classify("ſaltẽ", LEX) is None        # abbreviated: its letters are not its form
    assert classify("sed", LEX) is None          # no f or ſ


def test_align_folds_f_and_long_s():
    assert align(["quæ", "ſit", "per"], ["quæ", "fit", "per"]) == {0: 0, 1: 1, 2: 2}
