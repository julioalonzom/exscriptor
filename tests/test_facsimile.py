import json

from exscriptor import facsimile as fx

S1 = ("Primum argumentum est hoc, quod omnes doctores tenent.^[1. Arist.] Secundum vero "
      "ex auctoritate sumitur, et sapientiam infusam habent prophetae quos legimus in scripturis sanctis.")
S2 = "Caput alterum incipit hic et de sensu spirituali disserit per multas paginas libri nostri."


def work(tmp_path, rows, pages):
    wd = tmp_path / "w"
    (wd / "edition").mkdir(parents=True)
    for name, text in pages.items():
        (wd / "edition" / name).write_text(text)
    (wd / "facsimile-manifest.json").write_text(json.dumps(rows))
    secs = [{"slug": slug, "texts": [{"language": "la", "role": "transcription", "content": c}]}
            for slug, c in (("s1", S1), ("s2", S2))]
    return wd, {"works": [{"sections": secs, "facsimile": rows}]}


def row(fn, path, off, seq=0):
    return {"filename": fn, "section_path": path, "sequence": seq, "text_offset": off}


PAGES = {
    "pg-1.md": "Primum argumentum est hoc, quod omnes doctores tenent.^[1. Arist.] Secundum vero ex auctoritate sumitur, et sapien-",
    # the leaf begins inside « sapientiam », its note numbered per page
    "pg-2.md": "tiam infusam habent prophetae quos legimus in scripturis sanctis.\n\n**CAPUT ALTERUM**\n\nCaput alterum incipit hic",
    "pg-3.md": "**CAPUT ALTERUM**\n\nCaput alterum incipit hic et de sensu spirituali disserit per multas paginas libri nostri.",
    "pg-4.md": "",  # blank leaf
}


def test_exact_offsets_pass_and_a_mid_word_leaf_is_located_inside_the_word(tmp_path):
    start2 = S1.index("tiam infusam")
    rows = [row("pg-1.jpg", "s1", 0), row("pg-2.jpg", "s1", start2, 1), row("pg-2.jpg", "s2", 0),
            row("pg-4.jpg", "s2", None, 1)]
    wd, m = work(tmp_path, rows, PAGES)
    assert fx.gate(m, wd) == []


def test_an_early_offset_and_a_misfiled_leaf_fail_and_fix_repairs_both(tmp_path):
    start2 = S1.index("tiam infusam")
    rows = [row("pg-1.jpg", "s1", 0), row("pg-2.jpg", "s1", start2 - 12, 1),
            row("pg-3.jpg", "s1", len(S1) - 5, 2),          # holds only s2's text
            row("pg-2.jpg", "s2", 0), row("pg-3.jpg", "s2", 0, 1)]
    wd, m = work(tmp_path, rows, PAGES)
    found = fx.gate(m, wd)
    assert len(found) == 2
    assert f"offset {start2 - 12}, the leaf opens at {start2}" in found[0]
    assert "not in this section" in found[1]
    rep = fx.fix(m, wd)
    assert rep["unresolved"] == [] and len(rep["moved"]) == 1 and len(rep["dropped_misfiled"]) == 1
    fixed = json.loads((wd / "facsimile-manifest.json").read_text())
    assert [(r["filename"], r["section_path"], r["text_offset"]) for r in fixed] == [
        ("pg-1.jpg", "s1", 0), ("pg-2.jpg", "s1", start2), ("pg-2.jpg", "s2", 0), ("pg-3.jpg", "s2", 0)]
    m["works"][0]["facsimile"] = fixed
    assert fx.gate(m, wd) == []


def test_a_late_offset_past_an_inline_note_is_found(tmp_path):
    pages = {"pg-1.md": "Primum argumentum est hoc, quod omnes doctores tenent.^[1. Arist. longa nota.] Secundum vero"}
    late = S1.index("Secundum")
    wd, m = work(tmp_path, [row("pg-1.jpg", "s1", 0), row("pg-1.jpg", "s1", late, 1)], pages)
    assert fx.gate(m, wd) == ["s1 pg-1.jpg: offset %d, the leaf opens at 0" % late]
