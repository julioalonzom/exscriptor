"""HTTPS requests that work on any Python and pass the platform's edge.

A python.org framework build ships without CA certificates until its
« Install Certificates » step runs, and every request then fails with
CERTIFICATE_VERIFY_FAILED. The context uses the default store when it holds
certificates, else certifi's bundle, else the system bundle. Verification is
never turned off.

Schola Thomistica's edge refuses Python's default User-Agent with a 403, so
every request names the library instead.
"""
from __future__ import annotations

import os
import ssl
import urllib.request

from exscriptor import __version__

SYSTEM_BUNDLES = ("/etc/ssl/cert.pem", "/etc/ssl/certs/ca-certificates.crt",
                  "/etc/pki/tls/certs/ca-bundle.crt")
USER_AGENT = f"exscriptor/{__version__} (+https://github.com/julioalonzom/exscriptor)"


def ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    if ctx.cert_store_stats().get("x509_ca"):
        return ctx
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        pass
    for path in SYSTEM_BUNDLES:
        if os.path.exists(path):
            return ssl.create_default_context(cafile=path)
    return ctx


def urlopen(request: urllib.request.Request | str, timeout: float = 120):
    if isinstance(request, str):
        request = urllib.request.Request(request)
    if not request.has_header("User-agent"):
        request.add_header("User-Agent", USER_AGENT)
    return urllib.request.urlopen(request, timeout=timeout, context=ssl_context())
