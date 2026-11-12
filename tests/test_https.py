"""Requests verify certificates on any Python and carry a User-Agent the edge accepts."""
import ssl
import urllib.request
from pathlib import Path

import pytest

from exscriptor import https


@pytest.fixture(autouse=True)
def fresh_context():
    https.ssl_context.cache_clear()
    yield
    https.ssl_context.cache_clear()


def test_the_default_store_verifies_hostnames_and_certificates():
    ctx = https.ssl_context()
    assert ctx.verify_mode == ssl.CERT_REQUIRED and ctx.check_hostname


def test_an_empty_default_store_falls_back_to_the_first_bundle_found(monkeypatch, tmp_path):
    present = tmp_path / "present.pem"
    later = tmp_path / "later.pem"
    present.write_text("")
    later.write_text("")
    monkeypatch.setattr(https, "SYSTEM_BUNDLES", (str(tmp_path / "absent.pem"), str(present), str(later)))
    asked = []

    def fake(cafile=None, **kw):
        asked.append(cafile)
        return ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)

    monkeypatch.setattr(https.ssl, "create_default_context", fake)
    ctx = https.ssl_context()
    assert asked == [None, str(present)]
    assert ctx.verify_mode == ssl.CERT_REQUIRED and ctx.check_hostname


def test_the_context_is_built_once(monkeypatch):
    calls = []
    real = ssl.create_default_context
    monkeypatch.setattr(https.ssl, "create_default_context", lambda **kw: calls.append(kw) or real(**kw))
    first = https.ssl_context()
    built = len(calls)  # 1, or 2 where the default store is empty
    assert https.ssl_context() is first and len(calls) == built


def test_every_request_names_the_library(monkeypatch):
    seen = {}

    def fake_urlopen(request, timeout, context):
        seen["agent"] = request.get_header("User-agent")
        seen["context"] = context

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    https.urlopen("https://example.org/")
    assert seen["agent"].startswith("exscriptor/") and "Python-urllib" not in seen["agent"]
    assert isinstance(seen["context"], ssl.SSLContext)
    https.urlopen(urllib.request.Request("https://example.org/", headers={"User-Agent": "mine"}))
    assert seen["agent"] == "mine"


def test_a_bundle_that_will_not_load_is_skipped(monkeypatch, tmp_path):
    bad, good = tmp_path / "bad.pem", tmp_path / "good.pem"
    bad.write_text("")
    good.write_text("")
    monkeypatch.setattr(https, "SYSTEM_BUNDLES", (str(bad), str(good)))
    asked = []

    def fake(cafile=None, **kw):
        asked.append(cafile)
        if cafile == str(bad):
            raise ssl.SSLError("unloadable")
        return ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)

    monkeypatch.setattr(https.ssl, "create_default_context", fake)
    https.ssl_context()
    assert asked == [None, str(bad), str(good)]


def test_no_module_opens_a_url_except_through_this_one():
    src = Path(https.__file__).parent
    offenders = [p.name for p in src.glob("*.py")
                 if p.name != "https.py" and "urlopen(" in p.read_text().replace("https.urlopen(", "")]
    assert offenders == []
