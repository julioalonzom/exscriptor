"""Skills are linked from the checkout whose code runs; a stale copy is caught."""
from exscriptor import skills


def fake_checkout(tmp_path):
    src = tmp_path / "repo" / "skills"
    for name in ("corpus-import", "translation"):
        (src / name).mkdir(parents=True)
        (src / name / "SKILL.md").write_text(f"---\nname: {name}\n---\n")
    (src / "reference").mkdir()
    (src / "README.md").write_text("x")
    return src


def test_link_then_check(tmp_path):
    src, dest = fake_checkout(tmp_path), tmp_path / "agent"
    assert skills.problems(dest, src) == [f"{dest / n} is missing" for n in ("corpus-import", "reference", "translation")]
    assert skills.link(dest, src) == []
    assert skills.problems(dest, src) == []
    assert (dest / "translation").resolve() == (src / "translation").resolve()
    assert not (dest / "README.md").exists()


def test_a_link_elsewhere_is_repointed_but_a_copy_is_refused(tmp_path):
    src, dest = fake_checkout(tmp_path), tmp_path / "agent"
    dest.mkdir()
    old = tmp_path / "old" / "translation"
    old.mkdir(parents=True)
    (dest / "translation").symlink_to(old)
    (dest / "corpus-import").mkdir()
    assert any("not" in p for p in skills.problems(dest, src))
    refused = skills.link(dest, src)
    assert len(refused) == 1 and "corpus-import" in refused[0]
    assert (dest / "translation").resolve() == (src / "translation").resolve()
    assert skills.problems(dest, src) == [f"{dest / 'corpus-import'} is a copy, not a link: it shadows {src / 'corpus-import'}"]


def test_the_source_is_this_checkout():
    assert (skills.source() / "corpus-import" / "SKILL.md").is_file()
