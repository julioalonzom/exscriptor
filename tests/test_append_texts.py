"""A translation of a live work: every missing section, its titles, the Latin's structure."""
import hashlib
import json

import pytest
from typer.testing import CliRunner

from exscriptor import append_texts as at

CREDIT = "English translation by ScholaThomistica (scholathomistica.com)"
WORK = {"slug": "x", "title": "X", "sections": [
    {"id": 1, "title": "Pars", "slug": "pars", "section_type": "pars", "texts": {}, "children": [
        {"id": 2, "title": "Q1", "slug": "q1", "section_type": "quaestio",
         "texts": {"la": {"content": "*Primum* est.\n\nSecundum ^[nota]."}}},
        {"id": 3, "title": "Q2", "slug": "q2", "section_type": "quaestio",
         "texts": {"la": {"content": "Iam."}, "en": {"content": "Already."}}}]}]}


def review(source, target):
    digest = hashlib.sha256((source + "\0" + target).encode()).hexdigest()
    return {"1#1": {"sha256": digest, "note": "One printed title is continuous across the page break."}}


def test_review_is_bound_to_exact_pair_and_only_italic_signature():
    source, target = "*A* and *B*", "*A and B*"
    errors = ["markdown_block:1:signatures differ"]
    f = at.filter_reviewed_format_errors
    assert f(1, [source], [target], errors, review(source, target)) == []
    assert f(1, [source], [target + " changed"], errors, review(source, target)) == errors
    assert f(1, [source], [target + " ^[note]"], errors, review(source, target + " ^[note]")) == errors
    assert f(1, [source], [target], errors, {}) == errors
    assert f(1, [source], ["**A and B**"], errors, review(source, "**A and B**")) == errors
    assert f(1, [source], [target], ["block_count:0!=1"], review(source, target)) == ["block_count:0!=1"]


def run(tmp_path, texts, titles=None, *extra):
    snap, tdir = tmp_path / "work.json", tmp_path / "en"
    snap.write_text(json.dumps(WORK))
    tdir.mkdir(exist_ok=True)
    for sid, text in texts.items():
        (tdir / f"{sid}.md").write_text(text)
    (tmp_path / "titles.json").write_text(json.dumps({"titles": titles or {"1": "Part", "2": "Question 1"}}))
    out = tmp_path / "m.json"
    r = CliRunner().invoke(at.app, [str(snap), str(tdir), "--title-translations", str(tmp_path / "titles.json"),
                                    "--source-key", "x-en", "--source-url", "https://scholathomistica.com/x",
                                    "--batch-slug", "x-en-v1", "--title", "X (en)", "--attribution", CREDIT,
                                    "--out", str(out), *extra])
    return r, out


def test_only_the_untranslated_sections_and_their_parents_go(tmp_path):
    r, out = run(tmp_path, {2: "*First* is.\n\nSecond ^[note]."})
    assert r.exit_code == 0, r.output
    m = json.loads(out.read_text())
    secs = m["works"][0]["sections"]
    assert [s["section_key"] for s in secs] == ["section-1", "section-2"]
    assert secs[0]["texts"] == [] and secs[1]["parent_key"] == "section-1"
    assert secs[1]["texts"][0]["source_locator"] == "pars / q1"
    assert m["sources"][0]["license_code"] == "CC-BY-4.0"


@pytest.mark.parametrize("texts, titles, why", [
    ({}, None, "missing=[2]"),
    ({2: "*First* is.\n\nSecond ^[note].", 3: "Again."}, None, "unexpected=[3]"),
    ({2: "*First* is."}, None, "block_count:1!=2"),
    ({2: "First is.\n\nSecond ^[note]."}, None, "markdown_block:1"),
    ({2: "*First* is.\n\nSecond ^[note]."}, {"2": "Question 1"}, "title translation for section 1"),
])
def test_refuses_and_writes_nothing(tmp_path, texts, titles, why):
    r, out = run(tmp_path, texts, titles)
    assert r.exit_code != 0 and why in str(r.exception) + r.output and not out.exists()


def test_a_fully_translated_work_is_refused_not_sent_empty():
    done = json.loads(json.dumps(WORK))
    done["sections"][0]["children"][0]["texts"]["en"] = {"content": "Done."}
    with pytest.raises(SystemExit, match="nothing to translate"):
        at.build(done, {}, {}, "en", {}, "x-en-v1", "X")


def test_an_editors_note_is_the_one_allowed_extra(tmp_path):
    r, out = run(tmp_path, {2: "*First* is ^[Editor's note: the print has primus.].\n\nSecond ^[note]."})
    assert r.exit_code == 0, r.output
    assert "1 Editor's note(s) in section(s) 2" in json.loads(out.read_text())["summary"]


def test_provenance_is_merged_into_the_source(tmp_path):
    (tmp_path / "meta.json").write_text(json.dumps({"base_model": "m-1"}))
    r, out = run(tmp_path, {2: "*First* is.\n\nSecond ^[note]."}, None, "--metadata", str(tmp_path / "meta.json"))
    assert r.exit_code == 0, r.output
    meta = json.loads(out.read_text())["sources"][0]["metadata"]
    assert meta["base_model"] == "m-1" and meta["canonical_latin_work_slug"] == "x"


def test_a_curly_apostrophe_editors_note_is_allowed_too(tmp_path):
    r, out = run(tmp_path, {2: "*First* is ^[Editor’s note: the print has primus.].\n\nSecond ^[note]."})
    assert r.exit_code == 0, r.output


def test_metadata_cannot_replace_provenance_or_exempt_the_licence(tmp_path):
    (tmp_path / "meta.json").write_text(json.dumps({"canonical_latin_work_slug": "other"}))
    r, out = run(tmp_path, {2: "*First* is.\n\nSecond ^[note]."}, None, "--metadata", str(tmp_path / "meta.json"))
    assert json.loads(out.read_text())["sources"][0]["metadata"]["canonical_latin_work_slug"] == "x"
    (tmp_path / "meta.json").write_text(json.dumps({"schola_license_exempt": "because"}))
    out.unlink()
    r, out = run(tmp_path, {2: "*First* is.\n\nSecond ^[note]."}, None, "--metadata", str(tmp_path / "meta.json"))
    assert r.exit_code != 0 and not out.exists()


def test_update_work_rides_on_the_batch(tmp_path):
    (tmp_path / "uw.json").write_text(json.dumps({"expected": {"is_complete": False}, "set": {"is_complete": True}}))
    r, out = run(tmp_path, {2: "*First* is.\n\nSecond ^[note]."}, None, "--update-work", str(tmp_path / "uw.json"))
    assert json.loads(out.read_text())["works"][0]["update_work"]["set"] == {"is_complete": True}


def test_a_reviewed_italic_difference_passes_the_cli_and_only_with_its_review(tmp_path):
    latin, english = "*Primum* est.", "First is."  # the print's italic ran across a page break
    r, out = run(tmp_path, {2: f"{english}\n\nSecond ^[note]."})
    assert r.exit_code != 0 and "markdown_block:1" in r.output and not out.exists()
    digest = hashlib.sha256((latin + "\0" + english).encode()).hexdigest()
    (tmp_path / "reviews.json").write_text(json.dumps(
        {"2#1": {"sha256": digest, "note": "The printed italic runs across the page break."}}))
    r, out = run(tmp_path, {2: f"{english}\n\nSecond ^[note]."}, None, "--format-reviews", str(tmp_path / "reviews.json"))
    assert r.exit_code == 0, r.output


def test_provenance_reads_as_every_live_english_source_does(tmp_path):
    # the server reuses a source_key only with identical metadata; live sources say this
    r, out = run(tmp_path, {2: "*First* is.\n\nSecond ^[note]."})
    meta = json.loads(out.read_text())["sources"][0]["metadata"]
    assert meta["paragraph_alignment"] == "one English block per Latin block"
