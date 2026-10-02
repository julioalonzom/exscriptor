import json

import pytest

from exscriptor import render


def test_existing_render_is_found_and_offset_applies(tmp_path):
    (tmp_path / "pages").mkdir()
    (tmp_path / "pages" / "pg-034.png").write_bytes(b"png")
    (tmp_path / "work.json").write_text(json.dumps({"pages": {"pdf_offset": 6}}))
    assert render.page_image(tmp_path, 34).name == "pg-034.png"
    assert render.pdf_page(tmp_path, 34) == 40


def test_no_render_and_no_source_is_an_error(tmp_path):
    (tmp_path / "work.json").write_text("{}")
    with pytest.raises(FileNotFoundError):
        render.page_image(tmp_path, 1)
