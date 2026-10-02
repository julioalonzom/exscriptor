import json

import pytest

from exscriptor import guard
from exscriptor.guard import Call, Policy, check


@pytest.fixture
def work(tmp_path):
    w = tmp_path / "works" / "w"
    (w / "transcription").mkdir(parents=True)
    (w / "work.json").write_text("{}")
    return w


def test_page_files_are_writable_derived_files_are_not(work):
    pol = Policy()
    assert check(Call("write", path=str(work / "transcription/pg-001.md")), pol).allow
    for rel in ("edition/pg-001.md", "assembled/q1.md", "manifests/b.json", "pending.tsv",
                "assembled/ASSEMBLY.json", "manifests/b.preflight.json", "staged.jsonl"):
        v = check(Call("edit", path=str(work / rel)), pol)
        assert not v.allow and v.rule == "derived", rel


def test_derived_names_outside_a_work_dir_are_free(tmp_path):
    assert check(Call("write", path=str(tmp_path / "edition/x.md")), Policy()).allow


def test_shell_writes_to_derived_files_are_blocked_unless_a_producer(work):
    cwd = str(work)
    assert not check(Call("bash", command="echo x > edition/pg-001.md", cwd=cwd), Policy()).allow
    assert not check(Call("bash", command="sed -i '' 's/a/b/' assembled/q1.md", cwd=cwd), Policy()).allow
    assert not check(Call("bash", command="cp /tmp/x manifests/b.json", cwd=cwd), Policy()).allow
    assert check(Call("bash", command="python3 -m exscriptor.assemble . > assembled/log.txt", cwd=cwd), Policy()).allow
    pol = Policy(producers=["build_manifest.py"])
    assert check(Call("bash", command="python3 build_manifest.py > manifests/b.json", cwd=cwd), pol).allow
    assert check(Call("bash", command="ls 2>&1 | head", cwd=cwd), Policy()).allow


def test_secrets_are_never_read(tmp_path):
    pol = Policy(secret_files=[".env", "~/code/platform/backend/.env"])
    cwd = str(tmp_path)
    assert not check(Call("read", path=".env", cwd=cwd), pol).allow
    assert not check(Call("bash", command="cat .env", cwd=cwd), pol).allow
    assert not check(Call("bash", command="source ~/code/platform/backend/.env && run", cwd=cwd), pol).allow
    assert check(Call("bash", command="cat README.md", cwd=cwd), pol).allow


def test_forbidden_roots(tmp_path):
    root = tmp_path / "platform"
    pol = Policy(forbidden_roots=[str(root)])
    assert not check(Call("write", path=str(root / "a.py")), pol).allow
    assert not check(Call("bash", command="git commit -m x", cwd=str(root)), pol).allow
    assert check(Call("bash", command="git status", cwd=str(root)), pol).allow
    assert check(Call("read", path=str(root / "a.py")), pol).allow


def test_paid_commands_need_a_grant(tmp_path):
    pol = Policy(paid_commands=[r"gemini_batch_run"])
    c = Call("bash", command="python3 -m exscriptor.gemini_batch_run submit --model m", cwd=str(tmp_path))
    v = check(c, pol)
    assert not v.allow and v.rule == "paid"
    assert check(c, pol, {"paid"}).allow


def test_territory_confines_writes(work):
    pol = Policy(territory=[str(work / "transcription/pg-01[0-9].md")])
    assert check(Call("write", path=str(work / "transcription/pg-012.md")), pol).allow
    v = check(Call("write", path=str(work / "transcription/pg-020.md")), pol)
    assert not v.allow and v.rule == "territory"


def test_cli_and_claude_hook(work, tmp_path, capsys, monkeypatch):
    from typer.testing import CliRunner
    r = CliRunner().invoke(guard.app, ["check", "--tool", "write", "--path", str(work / "edition/pg-1.md")])
    assert r.exit_code == 1 and json.loads(r.stdout)["rule"] == "derived"
    hook = {"tool_name": "Write", "tool_input": {"file_path": str(work / "edition/pg-1.md")}, "cwd": str(work)}
    r = CliRunner().invoke(guard.app, ["claude-hook"], input=json.dumps(hook))
    assert r.exit_code == 2
    hook["tool_input"]["file_path"] = str(work / "transcription/pg-1.md")
    assert CliRunner().invoke(guard.app, ["claude-hook"], input=json.dumps(hook)).exit_code == 0
