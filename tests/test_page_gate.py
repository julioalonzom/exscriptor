import json
import shutil

from typer.testing import CliRunner

from exscriptor import page_gate as g

PAGE = ("**QVÆSTIO XXVII.**\n\n**De proceſſione diuinarum perſonarum.**\n\n"
        "HActenus D. Thom. *de vnitate essentiæ* egit, nunc de proceſſione.\n\n"
        "<!-- notes: footnotes: 0; catchword: none; joins-next: para -->\n")


def test_repair():
    text, n = g.repair("```markdown\nvel湯excellenter *a\nb* c\n\n\n\nd\n<!-- catchword: x -->\n```")
    assert n == 1
    assert text == "vel excellenter *a*\n*b* c\n\nd\n<!-- notes: catchword: x -->\n"


def test_repair_paragraphs_and_comment():
    got, _ = g.repair("**SVMMA TEXTVS.**\n\n*PRima concluſio.*\n*Secunda concluſio.*\nfun-<!-- notes: joins-next: hyphen -->\n")
    assert got == "**SVMMA TEXTVS.**\n\n*PRima concluſio.*\n\n*Secunda concluſio.*\nfun-\n<!-- notes: joins-next: hyphen -->\n"
    assert g.repair("*Vrina eſt ſana, et*\n*neque e conuerſo*")[0] == "*Vrina eſt ſana, et*\n*neque e conuerſo*"


def test_check_passes_and_refuses():
    assert g.check(g.repair(PAGE)[0], title_after=r"QVÆSTIO [IVXL]+\.") == []
    bad = PAGE.replace("**De proceſſione diuinarum perſonarum.**", "*De proceſſione diuinarum perſonarum.*")
    assert any("not one bold line" in p for p in g.check(bad, title_after=r"QVÆSTIO [IVXL]+\."))
    assert any("joins-next" in p for p in g.check(PAGE.replace("joins-next: para", "x")))
    assert any("another script" in p for p in g.check(PAGE.replace("egit", "eg湯湯it")))
    assert any("never closed" in p for p in g.check("<<<Q26>>>\nx\n" + PAGE))
    assert g.check("<<<Q26>>>\nx\n<<<END Q26>>>\n" + PAGE) == []
    long = PAGE.replace("nunc de proceſſione.", "nunc de proceſſione" + " et alia" * 100 + ".")
    assert g.check(long, ocr_words=215) == []
    assert any("OCR layer" in p for p in g.check(long, ocr_words=900))


def test_split_words():
    assert g.split_words("ea diſtin-ctio est, non-ens", {"distinctio", "ens"}) == [
        "line 1: 'diſtin-ctio' is a word broken at a line end in the print: write it whole, 'diſtinctio'"]


def test_check_promotes_passing_pages_only(tmp_path):
    (tmp_path / "work.json").write_text(json.dumps({"page_files": {"dir": "diplomatic"}}))
    run = tmp_path / "runs" / "read"
    run.mkdir(parents=True)
    (run / "pg-001.md").write_text(PAGE)
    (run / "pg-002.md").write_text(PAGE.replace("<!-- notes: footnotes: 0; catchword: none; joins-next: para -->\n", ""))
    r = CliRunner().invoke(g.app, ["check", str(tmp_path), "--pages", "1-2", "--promote"])
    assert r.exit_code == 1, r.output
    assert (tmp_path / "diplomatic" / "pg-001.md").read_text() == PAGE
    assert not (tmp_path / "diplomatic" / "pg-002.md").exists()
    assert json.loads((run / "gate.json").read_text())["1"] == []


def test_repair_titles_and_split_words():
    got, _ = g.repair("**ARTICVLVS TERTIVS.**\n\n***Vtrum ſint quinque notiones.***\n\nea diſtin-ctio est, non-ens, fun-\n",
                      r"ARTICVLVS [^*]+", {"distinctio", "ens", "fundamentum"})
    assert got == "**ARTICVLVS TERTIVS.**\n\n**Vtrum ſint quinque notiones.**\n\nea diſtinctio est, non-ens, fun-\n"
