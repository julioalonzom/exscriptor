import hashlib
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from exscriptor import upload_scans as up


def pages(tmp_path):
    d = tmp_path / "pages"
    d.mkdir()
    (d / "pg-001.jpg").write_bytes(b"first page")
    (d / "pg-002.jpg").write_bytes(b"second page")
    return d


def manifest():
    return {"works": [
        {"slug": "w", "facsimile": [
            {"filename": "pg-001.jpg", "section_path": "a", "sequence": 0},
            {"filename": "pg-002.jpg", "section_path": "a", "sequence": 1},
            {"filename": "pg-002.jpg", "section_path": "b", "sequence": 0}]},
        {"slug": "v", "mode": "edit", "operations": [
            {"op": "set_facsimile", "pages": [{"filename": "pg-001.jpg", "section_path": "c"}]}]}]}


def test_each_page_is_sent_once_and_every_row_gets_its_hash(tmp_path):
    sent = []
    m = manifest()
    result = up.upload(m, pages(tmp_path), send=lambda sha, data: sent.append((sha, data)) or {"already_staged": data == b"first page"})
    h1 = hashlib.sha256(b"first page").hexdigest()
    h2 = hashlib.sha256(b"second page").hexdigest()
    assert sorted(sent) == sorted([(h1, b"first page"), (h2, b"second page")])
    assert result == (1, 1, [])
    assert [r["sha256"] for r in up.facsimile_rows(m)] == [h1, h2, h2, h1]


def test_a_missing_render_or_a_refused_page_leaves_the_manifest_unchanged(tmp_path):
    d = pages(tmp_path)
    m = manifest()
    m["works"][0]["facsimile"].append({"filename": "pg-003.jpg", "section_path": "b", "sequence": 1})
    assert up.upload(m, d, send=lambda *_: pytest.fail("sent before every file was found"))[2] == [
        f"pg-003.jpg: no such file in {d}"]

    def refuse(sha, data):
        if data == b"second page":
            raise RuntimeError("HTTP 422: The content screen refused this image.")
        return {"already_staged": False}

    m = manifest()
    _, _, failures = up.upload(m, d, send=refuse)
    assert failures == ["pg-002.jpg: HTTP 422: The content screen refused this image."]
    assert not any("sha256" in r for r in up.facsimile_rows(m))


def test_put_scan_sends_the_key_and_reports_the_servers_reason(tmp_path):
    seen = {}

    class Handler(BaseHTTPRequestHandler):
        def do_PUT(self):
            seen["path"] = self.path
            seen["auth"] = self.headers["Authorization"]
            seen["body"] = self.rfile.read(int(self.headers["Content-Length"]))
            ok = seen["body"] == b"page"
            self.send_response(200 if ok else 422)
            self.end_headers()
            self.wfile.write(json.dumps({"already_staged": False} if ok else {"detail": "not an image"}).encode())

        def log_message(self, *_):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    api = f"http://127.0.0.1:{server.server_port}/"
    try:
        assert up.put_scan(api, "tok", "ab" * 32, b"page") == {"already_staged": False}
        assert seen == {"path": f"/api/corpus-imports/scans/{'ab' * 32}", "auth": "Bearer tok", "body": b"page"}
        with pytest.raises(RuntimeError, match="HTTP 422: not an image"):
            up.put_scan(api, "tok", "ab" * 32, b"junk")
    finally:
        server.shutdown()
