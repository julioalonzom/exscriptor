"""The snapshot is the live outline with every section's current texts."""
import json
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer

from exscriptor import snapshot


def test_texts_are_fetched_for_every_section_forty_at_a_time(tmp_path, monkeypatch):
    kids = [{"id": i, "slug": f"q{i}", "children": []} for i in range(2, 47)]  # 45 leaves
    outline = {"slug": "w", "sections": [{"id": 1, "slug": "pars", "children": kids}]}
    asked = []

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            url = urllib.parse.urlparse(self.path)
            if url.path == "/api/works/w/outline":
                body = outline
            else:
                ids = [int(x) for x in urllib.parse.parse_qs(url.query)["section_ids"]]
                asked.append(len(ids))
                body = {"sections": [{"id": i, "texts": {"la": {"id": 100 + i, "content": f"Textus {i}."}}}
                                     for i in ids if i != 1]}
            data = json.dumps(body).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(data)

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        work = snapshot.snapshot("w", f"http://127.0.0.1:{srv.server_port}")
    finally:
        srv.shutdown()
    assert asked == [40, 6]  # 40: the platform's MAX_SECTION_TEXT_IDS (routers/works.py)
    parent = work["sections"][0]
    assert parent["texts"] == {}
    assert parent["children"][44]["texts"]["la"]["content"] == "Textus 46."


def test_an_unreadable_outline_is_a_refusal():
    import pytest
    with pytest.raises(SystemExit, match="REFUSED: http://127.0.0.1:9/api/works/w/outline"):
        snapshot.snapshot("w", "http://127.0.0.1:9")
