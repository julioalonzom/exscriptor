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


def test_gemini_38_reread_refuses_implicit_off_before_moving_page(tmp_path, monkeypatch):
    import pytest
    from exscriptor import gemini_batch_run
    (tmp_path / "work.json").write_text(json.dumps({"page_files": {"scans": "pages"}}))
    run = tmp_path / "runs" / "read"
    run.mkdir(parents=True)
    (run / "gate.json").write_text(json.dumps({"1": ["bad markup"]}))
    page = run / "pg-001.md"
    page.write_text("draft")
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("read")
    monkeypatch.setattr(gemini_batch_run, "call", lambda *a, **k: pytest.fail("must refuse before network"))
    with pytest.raises(ValueError, match="3.8.*low"):
        g.reread(tmp_path, prompt, "models/gemini-3.8-flash")
    assert page.read_text() == "draft"


def test_gemini_38_reread_requires_explicit_output_cap(tmp_path):
    (tmp_path / "work.json").write_text(json.dumps({"page_files": {"scans": "pages"}}))
    run = tmp_path / "runs" / "read"
    run.mkdir(parents=True)
    (run / "gate.json").write_text("{}")
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("read")
    g.reread(tmp_path, prompt, "models/gemini-3.8-flash", thinking="low")
    assert json.loads((run / "escalate.json").read_text()) == {}


def test_reread_sends_low_and_records_thinking_tokens(tmp_path, monkeypatch):
    from exscriptor import gemini_batch_run
    (tmp_path / "work.json").write_text(json.dumps({"page_files": {"scans": "pages"}}))
    images = tmp_path / "pages"
    images.mkdir()
    (images / "pg-001.jpg").write_bytes(b"jpeg")
    run = tmp_path / "runs" / "read"
    run.mkdir(parents=True)
    (run / "gate.json").write_text(json.dumps({"1": ["bad markup"]}))
    (run / "pg-001.md").write_text("draft")
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("read")
    def fake_call(path, req, **kwargs):
        assert req["generationConfig"]["thinkingConfig"] == {"thinkingLevel": "low"}
        assert req["generationConfig"]["maxOutputTokens"] == 32000
        return {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": "new"}]}}],
                "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 5, "thoughtsTokenCount": 17}}
    monkeypatch.setattr(gemini_batch_run, "call", fake_call)
    g.reread(tmp_path, prompt, "models/gemini-3.8-flash", thinking="low")
    assert json.loads((run / "usage.jsonl").read_text())["thoughts_tokens"] == 17


def test_reread_records_usage_for_unfinished_response(tmp_path, monkeypatch):
    from exscriptor import gemini_batch_run
    (tmp_path / "work.json").write_text(json.dumps({"page_files": {"scans": "pages"}}))
    images = tmp_path / "pages"
    images.mkdir()
    (images / "pg-001.jpg").write_bytes(b"jpeg")
    run = tmp_path / "runs" / "read"
    run.mkdir(parents=True)
    (run / "gate.json").write_text(json.dumps({"1": ["bad markup"]}))
    (run / "pg-001.md").write_text("draft")
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("read")
    monkeypatch.setattr(gemini_batch_run, "call", lambda *a, **k: {
        "candidates": [{"finishReason": "MAX_TOKENS"}],
        "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 5, "thoughtsTokenCount": 17}})
    g.reread(tmp_path, prompt, "models/gemini-3.8-flash", thinking="low")
    row = json.loads((run / "usage.jsonl").read_text())
    assert (row["finish"], row["thoughts_tokens"]) == ("MAX_TOKENS", 17)
    assert not (run / "pg-001.md").exists()
