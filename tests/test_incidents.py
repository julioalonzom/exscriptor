import pytest

from exscriptor import incidents as inc


def test_add_assigns_id_and_signature(tmp_path):
    p = tmp_path / "papercuts.jsonl"
    r = inc.add(p, {"kind": "gate-failure", "what": "preflight: 3 stray asterisks in q12", "stage": "preflight"})
    assert r["id"].startswith("pc-") and r["status"] == "open"
    assert r["signature"] == "gate-failure|preflight|preflight: N stray asterisks in qN"
    r2 = inc.add(p, {"kind": "human", "what": "x"})
    assert r2["id"] != r["id"]


def test_auto_incidents_merge_on_signature(tmp_path):
    p = tmp_path / "papercuts.jsonl"
    inc.add(p, {"kind": "blocked-call", "what": "write to works/w/edition/pg-001.md", "source": "auto"})
    r = inc.add(p, {"kind": "blocked-call", "what": "write to works/w/edition/pg-007.md", "source": "auto"})
    assert r["count"] == 2 and len(inc.read(p)) == 1
    inc.add(p, {"kind": "blocked-call", "what": "write to works/w/edition/pg-009.md", "source": "human"})
    assert len(inc.read(p)) == 2


def test_closing_needs_a_cause_and_a_target():
    row = {"id": "a", "ts": "t", "kind": "human", "what": "x", "status": "promoted"}
    assert "closed without a cause (why)" in inc.problems(row)
    assert "promoted without a fix target" in inc.problems(row)
    row.update(why="y", fix="skill:schola-translate")
    assert inc.problems(row) == []
    row["fix"] = "somewhere"
    assert inc.problems(row)


def test_invalid_rows_are_refused(tmp_path):
    with pytest.raises(ValueError):
        inc.add(tmp_path / "p.jsonl", {"kind": "nonsense", "what": "x"})


def test_cluster_ranks_cross_work_patterns_first(tmp_path):
    a, b = tmp_path / "a" / "papercuts.jsonl", tmp_path / "b" / "papercuts.jsonl"
    for p in (a, b):
        inc.add(p, {"kind": "gate-failure", "stage": "preflight", "what": "stray asterisk on pg-12"})
    inc.add(a, {"kind": "human", "what": "slow"})
    inc.add(a, {"kind": "human", "what": "slow"})
    cl = inc.cluster(inc.read(a) + inc.read(b))
    assert cl[0]["works"] == ["a", "b"] and cl[0]["count"] == 2
    assert cl[1]["count"] == 2 and cl[1]["works"] == ["a"]
