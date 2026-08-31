import os
import schola_digitization.credentials as cred


def test_env_var_wins(tmp_path, monkeypatch):
    f = tmp_path / "x.env"
    f.write_text("MY_KEY=from-file\n")
    monkeypatch.setenv("DIGITIZATION_ENV", str(f))
    assert cred._from_env_file("MY_KEY") == "from-file"


def test_no_hardcoded_candidates():
    assert cred._CANDIDATES == []


def test_no_filesystem_on_import(monkeypatch):
    monkeypatch.delenv("DIGITIZATION_ENV", raising=False)
    monkeypatch.delenv("SCHOLA_ENV", raising=False)
    assert cred._from_env_file("NOPE_KEY") is None
