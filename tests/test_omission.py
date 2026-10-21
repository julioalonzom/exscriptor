from exscriptor.omission import missing_flags, omission_runs, runs

WITNESS = (
    "SUMMA THEOLOGIAE MORALIS\n"
    "Sicut specificatio sumitur a forma, ita individuatio a materia. "
    "Unde relinquitur quod principium individuationis sit materia signata."
)
# a page file: no running head (house style 2), the same body, and a note at its
# anchor rather than at the foot, which is what breaks character alignment
PAGE = (
    "Sicut specificatio sumitur a forma, ita individuatio a materia.^[1. Cf. "
    "S. Th. I, q. 3, a. 3.] Unde relinquitur quod principium individuationis "
    "sit materia signata."
)


def test_complete_page_reports_nothing():
    missing, total, found = omission_runs(PAGE, WITNESS)
    assert found == []
    # the head is the only thing absent, and it is dropped by the caller
    assert missing == 3  # SUMMA THEOLOGIAE MORALIS


def test_head_words_dropped():
    missing, _, found = omission_runs(PAGE, WITNESS,
                                      drop_words={"summa", "theologiae", "moralis"})
    assert missing == 0
    assert found == []


def test_dropped_clause_is_reported():
    cut = PAGE.replace("Unde relinquitur quod principium individuationis ", "")
    missing, total, found = omission_runs(cut, WITNESS,
                                          drop_words={"summa", "theologiae", "moralis"},
                                          lexicon={"unde", "relinquitur", "quod", "principium",
                                                   "individuationis", "sit", "materia"})
    assert missing > 0
    assert ["unde", "relinquitur", "quod", "principium", "individuationis"] in found


def test_wire_noise_is_not_an_omission():
    noisy = WITNESS.replace("Unde relinquitur", "воьсе оріонет ідоні що із")
    _, _, found = omission_runs(PAGE, noisy, drop_words={"summa", "theologiae", "moralis"},
                                lexicon={"unde", "relinquitur", "quod"})
    assert found == []


def test_count_aware():
    """A word the page has once cannot cover two witness occurrences."""
    flags = missing_flags("et", "et et")
    assert [absent for absent, _ in flags] == [False, True]


def test_runs_need_the_minimum_length():
    flags = [(False, "a"), (True, "b"), (True, "c"), (True, "d"), (False, "e"),
             (True, "f"), (True, "g"), (True, "h"), (True, "i")]
    assert runs(flags, 4) == [["f", "g", "h", "i"]]  # the b-c-d run is shorter


def test_runs_at_the_tail():
    flags = [(False, "a"), (True, "b"), (True, "c"), (True, "d"), (True, "e")]
    assert runs(flags, 4) == [["b", "c", "d", "e"]]


def test_short_run_not_reported():
    flags = [(False, "a"), (True, "b"), (True, "c"), (False, "d")]
    assert runs(flags, 4) == []
