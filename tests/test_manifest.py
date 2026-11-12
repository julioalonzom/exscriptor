import json
import subprocess
import sys
from pathlib import Path

import pytest

from exscriptor import manifest as bm

OFFLINE = "http://127.0.0.1:9"  # nothing listens: the author check warns and goes on


@pytest.fixture(autouse=True)
def no_library(monkeypatch):
    """Tests never reach production; the author check gets its own fake."""
    monkeypatch.setenv("SCHOLA_API_URL", OFFLINE)

    def offline(url):
        raise OSError("tests are offline")

    monkeypatch.setattr(bm, "fetch_json", offline)

LA_SRC = {"source_key": "ed-1639", "title": "Ed", "source_url": "https://archive.org/details/x",
          "license_code": "CC-BY-4.0", "license_url": "https://creativecommons.org/licenses/by/4.0/",
          "rights_basis": "public_domain_edition",
          "attribution_text": "Latin edition by ScholaThomistica (scholathomistica.com), from Ed 1639"}
EN_SRC = {"source_key": "x-en", "title": "EN", "source_url": "https://scholathomistica.com",
          "license_code": "CC-BY-4.0", "license_url": "https://creativecommons.org/licenses/by/4.0/",
          "rights_basis": "own_contribution",
          "attribution_text": "English translation by ScholaThomistica (scholathomistica.com)"}


def work(tmp_path, en_blocks=2):
    (tmp_path / "work.json").write_text(json.dumps({"slug": "x", "manifest": {
        "batch_slug": "x-la-en-v1", "work": {"title": "X", "slug": "x", "original_language": "la",
                                            "author_key": "a"},
        "authors": [{"author_key": "a", "name": "A"}], "sources": {"la": LA_SRC, "en": EN_SRC}}}))
    (tmp_path / "structure.json").write_text(json.dumps({"headings": {"quaestio": "^\\*\\*Q"}, "sections": [
        {"key": "pars", "type": "pars", "title": "Pars I", "title_translations": {"en": "Part One"}},
        {"key": "q1", "type": "quaestio", "title": "De Deo", "parent": "pars", "sequence": 1,
         "printed_start": 3, "printed_end": 5, "title_translations": {"en": "On God"}}]}))
    (tmp_path / "assembled").mkdir()
    (tmp_path / "assembled/q1.md").write_text("Primum.\n\nSecundum.\n")
    (tmp_path / "translation-en").mkdir()
    (tmp_path / "translation-en/q1.md").write_text("\n\n".join(["First.", "Second.", "Third."][:en_blocks]))
    return tmp_path


def test_create_with_translation(tmp_path):
    m = bm.build(work(tmp_path), "create", ["la", "en"], None)
    secs = m["works"][0]["sections"]
    assert [s["section_key"] for s in secs] == ["pars", "q1"]
    q1 = secs[1]
    assert q1["parent_key"] == "pars" and q1["title_translations"] == {"en": "On God"}
    la, en = q1["texts"]
    assert la["source_locator"] == "pp. 3-5" and la["role"] == "transcription"
    assert en["role"] == "translation" and en["attribution_text"]
    assert {s["source_key"] for s in m["sources"]} == {"ed-1639", "x-en"}


def test_refuses_block_mismatch(tmp_path):
    work(tmp_path, en_blocks=3)
    r = subprocess.run([sys.executable, "-m", "exscriptor.manifest", str(tmp_path), "--mode", "create",
                        "--languages", "la,en", "--out", str(tmp_path / "m.json")], capture_output=True, text=True)
    assert r.returncode == 1 and "blocks" in r.stdout and not (tmp_path / "m.json").exists()


def test_two_works_in_one_batch(tmp_path):
    (tmp_path / "work.json").write_text(json.dumps({"slug": "t5", "manifest": {
        "batch_slug": "t5-q50-v1", "sources": {"la": LA_SRC, "en": EN_SRC},
        "works": [
            {"id": "thomas", "languages": ["la"], "work": {"title": "Summa", "slug": "summa"}},
            {"id": "caietanus", "languages": ["la", "en"], "work": {"title": "In Summam", "slug": "caiet"}}]}}))
    (tmp_path / "structure.json").write_text(json.dumps({"sections": [
        {"key": "thomas-q50", "work": "thomas", "type": "quaestio", "title": "De angelis", "sequence": 500,
         "live_path": None},
        {"key": "thomas-q50a1", "work": "thomas", "type": "articulus", "title": "Utrum", "parent": "thomas-q50",
         "sequence": 1, "source_locator": "Q. L, art. 1", "canonical_locus": "pars.I/quaestio.50/articulus.1"},
        {"key": "caietanus-q50", "work": "caietanus", "type": "quaestio", "title": "De angelis", "sequence": 500,
         "title_translations": {"en": "On angels"}},
        {"key": "caietanus-q50a1", "work": "caietanus", "type": "articulus", "title": "Utrum",
         "parent": "caietanus-q50", "sequence": 1, "source_locator": "Q. L, art. 1",
         "title_translations": {"en": "Whether"},
         "commented_locus": "summa-theologiae:pars.I/quaestio.50/articulus.1"}]}))
    (tmp_path / "assembled").mkdir()
    (tmp_path / "assembled/thomas-q50a1.md").write_text("Videtur.\n\nSed contra.\n")
    (tmp_path / "assembled/caietanus-q50a1.md").write_text("Titulus clarus.\n")
    (tmp_path / "translation-en").mkdir()
    (tmp_path / "translation-en/caietanus-q50a1.md").write_text("The title is clear.\n")
    m = bm.build(tmp_path, "append_sections", ["la"], None)
    t, c = m["works"]
    assert [s["section_key"] for s in t["sections"]] == ["thomas-q50", "thomas-q50a1"]
    assert [x["language"] for x in t["sections"][1]["texts"]] == ["la"]
    assert t["sections"][1]["texts"][0]["source_locator"] == "Q. L, art. 1"
    assert [x["language"] for x in c["sections"][1]["texts"]] == ["la", "en"]
    assert c["sections"][0]["texts"] == [] and set(c) <= bm.APPEND_WORK_KEYS | {"import_mode", "sections"}
    assert {s["source_key"] for s in m["sources"]} == {"ed-1639", "x-en"}


def test_section_key_overrides_the_file_key(tmp_path):
    (tmp_path / "work.json").write_text(json.dumps({"slug": "t5", "manifest": {
        "batch_slug": "t5-v1", "sources": {"la": LA_SRC},
        "works": [{"id": "thomas", "languages": ["la"], "work": {"title": "Summa", "slug": "summa"}}]}}))
    (tmp_path / "structure.json").write_text(json.dumps({"sections": [
        {"key": "thomas-q50", "section_key": "q50", "work": "thomas", "type": "quaestio",
         "title": "De angelis", "sequence": 500},
        {"key": "thomas-q50a1", "section_key": "q50-a1", "work": "thomas", "type": "articulus",
         "title": "Utrum", "parent": "thomas-q50", "sequence": 1, "source_locator": "Q. L, art. 1"}]}))
    (tmp_path / "assembled").mkdir()
    (tmp_path / "assembled/thomas-q50a1.md").write_text("Videtur.\n")
    m = bm.build(tmp_path, "append_sections", ["la"], None)
    secs = m["works"][0]["sections"]
    assert [(s["section_key"], s["parent_key"]) for s in secs] == [("q50", None), ("q50-a1", "q50")]
    assert secs[1]["texts"][0]["content"] == "Videtur."


def test_refuses_missing_translation_titles_including_parent(tmp_path, capsys):
    import pytest
    work(tmp_path)
    p = tmp_path / 'structure.json'
    structure = json.loads(p.read_text())
    structure['sections'][0]['title_translations'] = {'en': 'Part One'}
    structure['sections'][1]['title_translations'] = {'en': '   '}
    p.write_text(json.dumps(structure))
    with pytest.raises(SystemExit):
        bm.build(tmp_path, 'create', ['la', 'en'], None)
    assert "q1: missing nonblank title_translations['en']" in capsys.readouterr().out
    structure['sections'][1]['title_translations'] = {'en': 'On God'}
    structure['sections'][0].pop('title_translations')
    p.write_text(json.dumps(structure))
    with pytest.raises(SystemExit):
        bm.build(tmp_path, 'create', ['la', 'en'], None)

    assert "pars: missing nonblank title_translations['en']" in capsys.readouterr().out


def test_source_only_does_not_require_translation_titles(tmp_path):
    m = bm.build(work(tmp_path), 'create', ['la'], None)
    assert all('title_translations' not in s for s in m['works'][0]['sections'])


FACSIMILE = [{"filename": "pg-003.jpg", "section_slug": "q1", "section_path": "pars/q1",
              "sequence": 0, "page_label": "p. 3", "text_offset": 0}]


def test_create_carries_the_facsimile_in_the_batch_shape(tmp_path):
    w = work(tmp_path)
    (w / "facsimile-manifest.json").write_text(json.dumps(FACSIMILE))
    pages = bm.build(w, "create", ["la"], None)["works"][0]["facsimile"]
    assert pages == [{k: v for k, v in FACSIMILE[0].items() if k != "section_slug"}]
    assert "facsimile" not in bm.build(w, "append_sections", ["la"], None)["works"][0]


def test_append_carries_the_facsimile_only_on_request_and_when_it_covers_the_batch(tmp_path):
    import pytest
    w = work(tmp_path)
    (w / "facsimile-manifest.json").write_text(json.dumps(FACSIMILE))
    m = bm.build(w, "append_sections", ["la"], None, with_facsimile=True)
    assert m["works"][0]["facsimile"] == bm.facsimile(w)
    stale = [dict(FACSIMILE[0], section_path="pars/q0")]
    (w / "facsimile-manifest.json").write_text(json.dumps(stale))
    with pytest.raises(SystemExit):
        bm.build(w, "append_sections", ["la"], None, with_facsimile=True)
    with pytest.raises(SystemExit):
        bm.build(w, "create", ["la"], None, with_facsimile=True)


def test_attach_facsimile_carries_only_the_facsimile(tmp_path):
    w = work(tmp_path)
    (w / "facsimile-manifest.json").write_text(json.dumps(FACSIMILE))
    m = bm.build(w, "attach_facsimile", ["la"], None)
    assert m["sources"] == [] and m["works"] == [{
        "import_mode": "attach_facsimile", "slug": "x", "title": "X",
        "facsimile": bm.facsimile(w)}]


def test_attach_facsimile_on_a_legacy_work_takes_its_slug(tmp_path):
    import pytest
    w = work(tmp_path)
    (w / "facsimile-manifest.json").write_text(json.dumps(FACSIMILE))
    (w / "work.json").unlink()
    m = bm.build(w, "attach_facsimile", ["la"], None, work_slug="legacy-slug", title="Legacy")
    assert m["works"][0]["slug"] == "legacy-slug" and m["batch_slug"] == "legacy-slug-facsimile"
    with pytest.raises(SystemExit):
        bm.build(w, "attach_facsimile", ["la"], None)


def test_refuses_our_own_text_under_cc0_or_uncredited(tmp_path, capsys):
    import pytest
    w = work(tmp_path)
    cfg = json.loads((w / "work.json").read_text())
    cfg["manifest"]["sources"]["la"] = {**LA_SRC, "license_code": "public_domain", "license_url": None}
    cfg["manifest"]["sources"]["en"] = {**EN_SRC, "attribution_text": "Translation"}
    (w / "work.json").write_text(json.dumps(cfg))
    with pytest.raises(SystemExit):
        bm.build(w, "create", ["la", "en"], None)
    out = capsys.readouterr().out
    assert "source ed-1639 (public_domain_edition): if we made this text it is CC-BY-4.0" in out
    assert "source x-en (own_contribution): if we made this text, attribution_text must credit" in out
    assert "metadata.schola_license_exempt" in out


def test_a_text_not_ours_or_a_third_partys_keeps_its_licence(tmp_path):
    w = work(tmp_path)
    cfg = json.loads((w / "work.json").read_text())
    cfg["manifest"]["sources"]["la"] = {**LA_SRC, "license_code": "public_domain", "license_url": None,
                                        "metadata": {"schola_license_exempt": "PL text taken as is"}}
    cfg["manifest"]["sources"]["en"] = {**EN_SRC, "license_code": "CC-BY-SA-4.0",
                                        "rights_basis": "open_license", "attribution_text": "Perseus"}
    (w / "work.json").write_text(json.dumps(cfg))
    m = bm.build(w, "create", ["la", "en"], None)
    assert {t["license_code"] for t in m["works"][0]["sections"][1]["texts"]} == {"public_domain", "CC-BY-SA-4.0"}


def test_a_revision_file_gets_its_own_batch_slug(tmp_path):
    w = work(tmp_path)
    slug = lambda out: (subprocess.run([sys.executable, "-m", "exscriptor.manifest", str(w), "--mode", "create",
                                        "--languages", "la,en", "--out", str(w / out)], check=True, capture_output=True),
                        json.loads((w / out).read_text())["batch_slug"])[1]
    assert slug("manifests/x-v1.json") == "x-la-en-v1"
    assert slug("manifests/x-v2.json") == "x-la-en-v2"
    cfg = json.loads((w / "work.json").read_text()); cfg["manifest"]["batch_slug"] = "billot-1907"
    (w / "work.json").write_text(json.dumps(cfg))
    assert slug("manifests/x-v3.json") == "billot-1907-v3"


def test_a_latin_title_takes_the_house_pass_its_text_took(tmp_path):
    w = work(tmp_path)
    s = json.loads((w / "structure.json").read_text())
    s["sections"][1]["title"] = "De coelo :"
    (w / "structure.json").write_text(json.dumps(s))
    m = bm.build(w, "create", ["la", "en"], None)
    assert m["works"][0]["sections"][1]["title"] == "De caelo:"


def test_create_refuses_a_work_field_the_platform_does_not_take(tmp_path, capsys):
    # Hurtado pilot 3: work.json carried `manifest_key`, retired from the create schema on
    # 2026-10-19; preflight passed and only the submit wrapper's schema check caught it.
    d = work(tmp_path)
    cfg = json.loads((d / "work.json").read_text())
    cfg["manifest"]["work"]["manifest_key"] = "x"
    (d / "work.json").write_text(json.dumps(cfg))
    try:
        bm.build(d, "create", ["la", "en"], None)
        raise AssertionError("built")
    except SystemExit:
        pass
    assert "manifest_key" in capsys.readouterr().out


def test_an_author_the_library_holds_goes_in_as_author_slug(monkeypatch):
    # Hurtado batch 853: Petrus Hurtado de Mendoza was declared anew; the library holds him.
    lib = {"/api/authors?q=": {"items": [{"id": 76, "name": "Pedro Hurtado de Mendoza",
                                          "aliases": ["Petrus Hurtado de Mendoza"]}]},
           "/api/authors/profiles": [{"id": 76, "slug": "pedro-hurtado-de-mendoza"}]}
    monkeypatch.setattr(bm, "fetch_json", lambda url: next(v for k, v in lib.items() if k in url))
    out = bm.existing_authors([{"author_key": "petrus", "name": "petrus hurtado de mendoza"}], "https://x")
    assert len(out) == 1 and "author_slug to pedro-hurtado-de-mendoza" in out[0]
    assert not bm.existing_authors([{"author_key": "n", "name": "Hurtado Novus"}], "https://x")
