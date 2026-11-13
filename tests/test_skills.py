"""The skills' cross-references resolve, and they carry no machine paths."""
import re
from pathlib import Path

SKILLS = Path(__file__).resolve().parent.parent / "skills"
REF = re.compile(r"`((?:\.\./)?(?:reference|references|[a-z-]+/references)/[\w.-]+\.(?:md|json))`")


def test_every_skill_has_frontmatter():
    for skill in sorted(SKILLS.glob("*/SKILL.md")):
        head = skill.read_text().split("\n", 3)
        assert head[0] == "---" and head[1] == f"name: {skill.parent.name}", skill


def test_referenced_files_exist():
    for doc in sorted(SKILLS.rglob("*.md")):
        for target in REF.findall(doc.read_text()):
            assert (doc.parent / target).resolve().is_file(), f"{doc}: {target}"


def test_no_machine_paths():
    bad = re.compile(r"/Users/|~/code/|\.agents/|backend/\.env")
    for doc in sorted(SKILLS.rglob("*.md")):
        assert not bad.search(doc.read_text()), doc


def test_every_command_a_skill_cites_exists():
    src = SKILLS.parent / "src" / "exscriptor"
    for doc in sorted(SKILLS.rglob("*.md")):
        for module in re.findall(r"python3 -m exscriptor\.([a-z_]+)", doc.read_text()):
            assert (src / f"{module}.py").is_file(), f"{doc}: exscriptor.{module}"
