"""Staging refuses before sending what preflight, the licence or the library would refuse."""
import hashlib
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from typer.testing import CliRunner

from exscriptor import batch_status, preflight, submit

OURS = {"source_key": "x-en", "rights_basis": "own_contribution", "license_code": "CC-BY-4.0",
        "license_url": "https://creativecommons.org/licenses/by/4.0/",
        "attribution_text": "English translation by ScholaThomistica (scholathomistica.com)"}


@pytest.fixture
def server(monkeypatch):
    """A local platform: records each request, answers with ``reply``."""
    seen, reply = [], {"id": 7, "status": "pending", "validation_report": {"warnings": []}}

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _answer(self, body: dict):
            data = json.dumps(body).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):
            n = int(self.headers["Content-Length"])
            seen.append((self.path, self.headers["Authorization"], json.loads(self.rfile.read(n))))
            self._answer(reply)

        def do_GET(self):
            seen.append((self.path, self.headers["Authorization"], None))
            self._answer({"status": "approved", "review_note": "ok"})

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setenv("SCHOLA_API_URL", f"http://127.0.0.1:{srv.server_port}")
    monkeypatch.setenv("SCHOLA_IMPORT_TOKEN", "stci_test")
    monkeypatch.setattr(submit, "existing_authors", lambda authors, api: [])
    yield seen, reply
    srv.shutdown()


def staged_manifest(tmp_path, sources=(OURS,), passed=True):
    work = tmp_path / "w"
    (work / "manifests").mkdir(parents=True)
    path = work / "manifests" / "w-v1.json"
    m = {"batch_slug": "w-v1", "sources": list(sources),
         "works": [{"import_mode": "append_texts", "sections": [{"texts": [{"language": "en"}]}]}]}
    path.write_text(json.dumps(m))
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    preflight.report_path(path).write_text(json.dumps({"sha256": sha, "passed": passed, "gates": {}}))
    return path


def run(path, *args):
    return CliRunner().invoke(submit.app, [str(path), *args])


def test_a_passing_batch_is_sent_with_the_key_and_recorded(server, tmp_path):
    seen, _ = server
    path = staged_manifest(tmp_path)
    r = run(path, "--supersedes-batch-id", "6")
    assert r.exit_code == 0, r.output
    (route, auth, body), = seen
    assert route == "/api/corpus-imports" and auth == "Bearer stci_test"
    assert body["manifest"]["batch_slug"] == "w-v1" and body["supersedes_batch_id"] == 6
    line = json.loads((tmp_path / "w" / "staged.jsonl").read_text())
    assert line["batch_id"] == 7 and line["manifest"] == "w-v1.json"
    assert "stci_test" not in r.output


def test_nothing_is_sent_without_a_matching_preflight(server, tmp_path):
    seen, _ = server
    path = staged_manifest(tmp_path)
    path.write_text(path.read_text() + " ")  # changed after preflight
    r = run(path)
    assert r.exit_code != 0 and "changed after preflight" in r.output and seen == []


def test_our_own_text_under_cc0_is_refused_before_sending(server, tmp_path):
    seen, _ = server
    path = staged_manifest(tmp_path, sources=[{**OURS, "license_code": "CC0-1.0"}])
    r = run(path)
    assert r.exit_code != 0 and "if we made this text it is CC-BY-4.0" in r.output and seen == []


def test_a_warning_is_a_defect(server, tmp_path):
    _, reply = server
    reply["validation_report"] = {"warnings": ["author merged by name"]}
    r = run(staged_manifest(tmp_path))
    assert r.exit_code == 2 and "author merged by name" in r.output


def test_batch_status_requires_what_the_platform_says(server, tmp_path):
    seen, _ = server
    run(staged_manifest(tmp_path))
    work = tmp_path / "w"
    assert batch_status.report(work, None, "approved")["ok"] is True
    assert batch_status.report(work, None, "rejected")["ok"] is False
    assert seen[-1][0] == "/api/corpus-imports/7"
    assert batch_status.report(tmp_path / "none", None, None)["ok"] is False


def test_no_preflight_report_at_all_is_refused(server, tmp_path):
    seen, _ = server
    path = staged_manifest(tmp_path)
    preflight.report_path(path).unlink()
    r = run(path)
    assert r.exit_code != 0 and "no preflight report" in r.output and seen == []


def test_an_unreadable_library_warns_and_the_batch_still_goes(server, tmp_path, monkeypatch):
    seen, _ = server

    def down(authors, api):
        raise OSError("connection refused")

    monkeypatch.setattr(submit, "existing_authors", down)
    r = run(staged_manifest(tmp_path))
    assert r.exit_code == 0 and "could not check the declared authors" in r.output and len(seen) == 1


def test_batch_status_reports_an_unreachable_platform_without_crashing(tmp_path, monkeypatch):
    run_dir = tmp_path / "w"
    run_dir.mkdir()
    (run_dir / "staged.jsonl").write_text('{"batch_id": 9, "manifest": "m.json", "status": "pending"}\n')
    monkeypatch.setenv("SCHOLA_IMPORT_TOKEN", "stci_test")
    monkeypatch.setenv("SCHOLA_API_URL", "http://127.0.0.1:9")
    out = batch_status.report(run_dir, None, "approved")
    assert out["ok"] is False and out["batches"][0]["status"].startswith("unreachable")
    gone = batch_status.report(run_dir, None, None, fetch=lambda api, token, b: {"status": "http-404"})
    assert gone["ok"] is False


def test_an_edit_batch_keeps_the_licence_of_what_it_corrects():
    from exscriptor import licence
    cc0 = {"source_key": "fix", "license_code": "CC0-1.0", "rights_basis": "own_contribution"}
    assert licence.manifest_problems({"sources": [cc0], "works": [{"import_mode": "edit"}]}) == []
    assert licence.manifest_problems({"sources": [cc0], "works": [{"import_mode": "append_texts"}]})
