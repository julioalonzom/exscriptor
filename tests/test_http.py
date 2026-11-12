"""Requests verify certificates on any Python and carry a User-Agent the edge accepts."""
import ssl
import urllib.request

from exscriptor import http


def test_an_empty_default_store_falls_back_to_a_bundle(monkeypatch):
    real, asked = ssl.create_default_context, []

    def fake(cafile=None, **kw):
        asked.append(cafile)
        return ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT) if cafile is None else real(cafile=cafile)

    monkeypatch.setattr(http.ssl, "create_default_context", fake)
    ctx = http.ssl_context()
    assert asked[0] is None and asked[-1] is not None
    assert ctx.verify_mode == ssl.CERT_REQUIRED and ctx.cert_store_stats()["x509_ca"] > 0


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
