import re
import shutil
import subprocess

import pytest

from exscriptor import iiif

HOCR = """<div class='ocr_page' title='x_source p; bbox 0 0 600 300'>
<span class='ocr_line' title='bbox 50 100 550 140'>
<span class='ocrx_word' title='bbox 50 100 200 140'>Dominus</span>
<span class='ocrx_word' title='bbox 220 100 330 140'>&amp;c.</span>
<span class='ocrx_word' title='bbox 350 100 550 140'>poſſedit</span>
</span></div>"""


def test_canvases_v2():
    m = {"sequences": [{"canvases": [{"width": 10, "height": 20,
          "images": [{"resource": {"@id": "x.jpg", "service": {"@id": "https://i/img_1"}}}],
          "seeAlso": {"@id": "https://o/1", "format": "text/vnd.hocr+html"}}]}]}
    assert iiif.canvases(m) == [{"image": "https://i/img_1/full/full/0/default.jpg", "hocr": "https://o/1",
                                 "width": 10, "height": 20}]


def test_hocr_words():
    assert [w for w, _ in iiif.hocr_words(HOCR)] == ["Dominus", "&c.", "poſſedit"]


def test_pdf_has_text_layer_at_canvas_numbers(tmp_path):
    pytest.importorskip("pymupdf")
    Image = pytest.importorskip("PIL.Image")
    if not shutil.which("pdftotext"):
        pytest.skip("pdftotext (poppler) not installed")
    # the image is twice the hOCR's size: boxes scale with it
    Image.new("RGB", (1200, 600), "white").save(tmp_path / "pg-002.jpg", quality=90)
    (tmp_path / "pg-002.hocr").write_text(HOCR)
    out = tmp_path / "x.pdf"
    assert iiif.build_pdf(tmp_path, out) == 2  # canvas 1 is a blank page: PDF page 2 = canvas 2
    xml = subprocess.run(["pdftotext", "-f", "2", "-l", "2", "-bbox-layout", str(out), "-"],
                         capture_output=True, text=True, check=True).stdout
    words = re.findall(r'<word xMin="([\d.]+)"[^>]*>([^<]*)</word>', xml)
    assert [w for _, w in words] == ["Dominus", "&amp;c.", "poſſedit"]
    # hOCR x=50 on a 600-px page = 100 px on the 1200-px image = 24 pt at 300 dpi
    assert abs(float(words[0][0]) - 24) < 3
