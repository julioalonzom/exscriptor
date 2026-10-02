import json
import sys

from typer.testing import CliRunner

from exscriptor import incidents as inc
from exscriptor import replay

PAGE = "Utrum Deus sit. Ad primum sic proceditur. Videtur quod Deus non sit, quia si unum contrariorum fuerit infinitum."


def test_distance_is_zero_for_identical_text_and_counts_edits():
    assert replay.distance("a b c", "a b c")["cer"] == 0
    d = replay.distance("Deus est bonus", "Deus eft bonus")
    assert d["char_edits"] == 1 and d["word_edits"] == 1
    assert replay.distance("Deus est", "Deus")["word_edits"] == 1


def test_span_scores_only_the_site():
    cand = PAGE.replace("Utrum", "Vtrum").replace("infinitum", "infinitam")  # errors outside and inside
    whole = replay.score_span(PAGE, cand)
    site = replay.score_span(PAGE, cand, start="Videtur quod", end="infinitum.")
    assert whole["char_edits"] == 2
    assert site["char_edits"] == 1
    clean_site = replay.score_span(PAGE, PAGE.replace("Utrum", "Vtrum"), start="Videtur quod", end="infinitum.")
    assert clean_site["char_edits"] == 0


def test_span_survives_insertions_before_it():
    cand = "HEADER JUNK " + PAGE
    assert replay.score_span(PAGE, cand, start="Ad primum", end="proceditur.")["char_edits"] == 0


def test_letters_mode_ignores_punctuation_and_case():
    assert replay.score_span("Deus, est.", "deus est", mode="letters")["cer"] == 0


def _work(tmp_path):
    w = tmp_path / "works" / "w"
    (w / "transcription").mkdir(parents=True)
    (w / "pages").mkdir()
    (w / "work.json").write_text(json.dumps({"track": "modern"}))
    for n in (1, 2, 3):
        (w / "transcription" / f"pg-{n:03d}.md").write_text(PAGE)
        (w / "pages" / f"pg-{n:03d}.jpg").write_bytes(b"jpg")
    return w


def test_sentinels_and_from_incidents(tmp_path):
    w = _work(tmp_path)
    s = replay.sentinels([w], 2, tmp_path)
    assert len(s) == 2 and all(f["role"] == "sentinel" for f in s)
    assert s[0]["expected"]["path"].startswith("works/w/transcription/")
    p = tmp_path / "papercuts.jsonl"
    inc.add(p, {"kind": "overturn", "what": "reader misread infinitum", "repro": {
        "work": "works/w", "page": 1, "expected": {"path": "works/w/transcription/pg-001.md",
                                                     "start": "Videtur", "end": "infinitum."}}})
    inc.add(p, {"kind": "gate-failure", "what": "stray asterisk", "repro": {"bad": "bad.md"}})
    fx = replay.from_incidents(inc.read(p))
    assert [f["kind"] for f in fx] == ["reading", "gate"]


def test_run_and_compare_verify_an_improvement(tmp_path):
    w = _work(tmp_path)
    fixtures = [
        {"id": "t1", "role": "target", "work": "works/w", "page": 1,
         "expected": {"path": "works/w/transcription/pg-001.md", "start": "Videtur", "end": "infinitum."}},
        {"id": "s1", "role": "sentinel", "work": "works/w", "page": 2,
         "expected": {"path": "works/w/transcription/pg-002.md"}},
    ]
    bad = tmp_path / "bad.txt"
    bad.write_text(PAGE.replace("infinitum", "infinitam"))
    good = tmp_path / "good.txt"
    good.write_text(PAGE)
    res = tmp_path / "r.jsonl"
    py = sys.executable
    # the "old" reader misreads; the "new" reader does not
    replay.run(fixtures, f"{py} -c 'import shutil,sys; shutil.copy(\"{bad}\", sys.argv[1])' {{out}}",
               "old", 2, res, tmp_path)
    replay.run(fixtures, f"cat {good}", "new", 2, res, tmp_path)
    v = replay.compare(replay.read_jsonl(res), "old", "new")
    assert v["verified"], v["reasons"]
    assert v["targets"]["mean_delta"] < 0
    # rerun is resumable: nothing left to do
    assert replay.run(fixtures, "false", "new", 2, res, tmp_path) == []
    # and the reverse change is refused
    assert not replay.compare(replay.read_jsonl(res), "new", "old")["verified"]


def test_sentinel_regression_blocks(tmp_path):
    rows = [
        {"fixture": "t", "role": "target", "label": "old", "sample": 0, "cer": 0.10},
        {"fixture": "t", "role": "target", "label": "new", "sample": 0, "cer": 0.02},
        {"fixture": "s", "role": "sentinel", "label": "old", "sample": 0, "cer": 0.01},
        {"fixture": "s", "role": "sentinel", "label": "new", "sample": 0, "cer": 0.05},
    ]
    v = replay.compare(rows, "old", "new")
    assert not v["verified"] and any("sentinel" in r for r in v["reasons"])


def test_gate_verification(tmp_path):
    (tmp_path / "bad.md").write_text("text with * stray")
    clean = tmp_path / "clean"
    clean.mkdir()
    (clean / "a.md").write_text("clean text")
    fx = [{"id": "g", "kind": "gate", "bad": "bad.md"}]
    cmd = "! grep -q '\\*' {file}"
    v = replay.gate(fx, cmd, ["clean/*.md"], tmp_path)
    assert v["verified"] and v["caught"] == 1
    (clean / "b.md").write_text("a * here")
    assert not replay.gate(fx, cmd, ["clean/*.md"], tmp_path)["verified"]


def test_cli_compare_exit_code(tmp_path):
    res = tmp_path / "r.jsonl"
    res.write_text("".join(json.dumps(r) + "\n" for r in [
        {"fixture": "t", "role": "target", "label": "old", "sample": 0, "cer": 0.1},
        {"fixture": "t", "role": "target", "label": "new", "sample": 0, "cer": 0.0}]))
    assert CliRunner().invoke(replay.app, ["compare", str(res)]).exit_code == 0
    assert CliRunner().invoke(replay.app, ["compare", str(res), "--base", "new", "--cand", "old"]).exit_code == 1
