"""Requests verify certificates on any Python and carry a User-Agent the edge accepts."""
import ssl
import urllib.request

import pytest

from exscriptor import http


@pytest.fixture(autouse=True)
def fresh_context():
    http.ssl_context.cache_clear()
    yield
    http.ssl_context.cache_clear()


def test_the_default_store_verifies_hostnames_and_certificates():
    ctx = http.ssl_context()
    assert ctx.verify_mode == ssl.CERT_REQUIRED and ctx.check_hostname


def test_an_empty_default_store_falls_back_to_the_first_bundle_found(monkeypatch, tmp_path):
    present = tmp_path / "present.pem"
    later = tmp_path / "later.pem"
    present.write_text("")
    later.write_text("")
    monkeypatch.setattr(http, "SYSTEM_BUNDLES", (str(tmp_path / "absent.pem"), str(present), str(later)))
    asked = []

    def fake(cafile=None, **kw):
        asked.append(cafile)
        return ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)

    monkeypatch.setattr(http.ssl, "create_default_context", fake)
    ctx = http.ssl_context()
    assert asked == [None, str(present)]
    assert ctx.verify_mode == ssl.CERT_REQUIRED and ctx.check_hostname


def test_the_context_is_built_once(monkeypatch):
    calls = []
    real = ssl.create_default_context
    monkeypatch.setattr(http.ssl, "create_default_context", lambda **kw: calls.append(kw) or real(**kw))
    assert http.ssl_context() is http.ssl_context()
    assert len(calls) <= 2


def test_every_request_names_the_library(monkeypatch):
    seen = {}

    def fake_urlopen(request, timeout, context):
        seen["agent"] = request.get_header("User-agent")
        seen["context"] = context

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    http.urlopen("https://example.org/")
    assert seen["agent"].startswith("exscriptor/") and "Python-urllib" not in seen["agent"]
    assert isinstance(seen["context"], ssl.SSLContext)
    http.urlopen(urllib.request.Request("https://example.org/", headers={"User-Agent": "mine"}))
    assert seen["agent"] == "mine"
