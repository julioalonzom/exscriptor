"""A real job, end to end, on four public-domain pages.

The sample (tests/fixtures/sample-work) is the preface of Domingo de Soto,
De natura et gratia (Antwerp 1550): diplomatic page files as a reader wrote
them, the editor's decisions, a lexicon trimmed to the forms these pages
touch (it gives the same edition as the corpus lexicon), the scan-adjudicated
page joins (with them, any other page break whose declared and inferred join
disagree fails assembly), the English
translation and the alignment readers' notes. Every command a job runs
goes over it, as the skills give them:

    expand -> assemble -> manifest (create) -> alignment -> preflight
    append_texts (a translation of the same text, live) -> alignment -> preflight

Two things are checked. A finished batch must pass preflight: a gate or a
builder that refuses this sample refuses real work. (Its first catch: the
translate-only alignment could not pair a real snapshot's sections, #27,
while the unit test fed it a snapshot shape the API never returns.) And the
outputs must equal tests/fixtures/sample-expected,
so a change in behaviour shows as a diff in the pull request. When the change
is intended, regenerate them:

    EXSCRIPTOR_UPDATE_EXPECTED=1 python3 -m pytest tests/test_pipeline.py

The inputs and this file are guardrails (scripts/guardrail.py): loosening
what a finished batch must pass is the maintainer's call. The expected
outputs are not.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE = FIXTURES / "sample-work"
EXPECTED = FIXTURES / "sample-expected"
UPDATE = os.environ.get("EXSCRIPTOR_UPDATE_EXPECTED") == "1"
CREDIT = "English translation by ScholaThomistica (scholathomistica.com)"


def run(work: Path, *args: str) -> str:
    # No network: a proxy that refuses every connection, so a command that
    # would call the platform fails here instead of reaching production.
    env = {**os.environ, "HTTP_PROXY": "http://127.0.0.1:9", "HTTPS_PROXY": "http://127.0.0.1:9",
           "NO_PROXY": "", "SCHOLA_IMPORT_TOKEN": "", "SCHOLA_CORPUS_IMPORT_TOKEN": ""}
    r = subprocess.run([sys.executable, "-m", *args], cwd=work, env=env, capture_output=True, text=True)
    assert r.returncode == 0, f"{' '.join(args[:2])} exited {r.returncode}:\n{r.stdout}\n{r.stderr}"
    return r.stdout


def dispose(work: Path, manifest: str, report: str, *source: str) -> None:
    """The readers' notes are kept per pair; the key's hash follows the text,
    so map each note onto the pair `show` names today."""
    shown = run(work, "exscriptor.alignment", "show", manifest, "--report", report, *source)
    notes = json.loads((work / "dispositions.json").read_text(encoding="utf-8"))
    keys = re.findall(r"^=== (\S+)", shown, re.M)
    assert keys, "the screen flagged no pair to read"
    current = {k: notes[k.split("@")[0]] for k in keys}
    (work / "dispositions-now.json").write_text(json.dumps(current), encoding="utf-8")
    run(work, "exscriptor.alignment", "dispose", manifest, "--report", report,
        "--dispositions", "dispositions-now.json", *source)


def passed(work: Path, manifest: str) -> None:
    report = json.loads((work / manifest).with_suffix(".preflight.json").read_text(encoding="utf-8"))
    failed = {g: v["findings"] for g, v in report["gates"].items() if not v.get("passed")}
    assert not failed, failed


@pytest.fixture(scope="module")
def job(tmp_path_factory):
    work = tmp_path_factory.mktemp("job") / "sample-work"
    shutil.copytree(SAMPLE, work)
    run(work, "exscriptor.expand", "run", "--pages", "diplomatic/*.md", "--out-dir", "edition",
        "--record", "expansions.tsv", "--lexicon", "lexicon.json", "--decisions", "decisions.tsv",
        "--table", "abbreviations.tsv")
    for name in ("pending.tsv", "long-s.tsv"):  # the editor pass left nothing open
        path = work / name
        assert not path.exists() or len(path.read_text(encoding="utf-8").splitlines()) <= 1, path.read_text()
    run(work, "exscriptor.assemble", "--pages", "edition/pg-{n:03d}.md", "--range", "9-12",
        "--structure", "structure.json", "--out-dir", "assembled", "--join-decisions", "joins.json")

    create = "manifests/sample-v1.json"
    run(work, "exscriptor.manifest", ".", "--mode", "create", "--languages", "la,en", "--out", create)
    run(work, "exscriptor.alignment", "screen", create, "--target", "en", "--report", "alignment/create.json")
    dispose(work, create, "alignment/create.json")
    run(work, "exscriptor.preflight", create, "--lexicon", "lexicon.json", "--alignment", "alignment/create.json")

    live = "live/manifests/sample-en-v1.json"
    run(work, "exscriptor.append_texts", "live/live.json", "live/en", "--title-translations",
        "live/titles.json", "--source-key", "sample-en", "--source-url", "https://scholathomistica.com",
        "--batch-slug", "sample-en-v1", "--title", "Sample (en)", "--attribution", CREDIT, "--out", live)
    source = ("--source", "live/live.json")
    run(work, "exscriptor.alignment", "screen", live, "--target", "en", "--report", "alignment/live.json", *source)
    dispose(work, live, "alignment/live.json", *source)
    run(work, "exscriptor.preflight", live, "--work-dir", ".", "--lexicon", "lexicon.json",
        "--alignment", "alignment/live.json", *source)
    return work


def test_a_finished_create_batch_passes_preflight(job):
    passed(job, "manifests/sample-v1.json")


def test_a_finished_translation_of_a_live_work_passes_preflight(job):
    passed(job, "live/manifests/sample-en-v1.json")


OUTPUTS = ["edition/pg-009.md", "edition/pg-010.md", "edition/pg-011.md", "edition/pg-012.md",
           "assembled/liber-i.md", "assembled/liber-i-praefatio.md",
           "manifests/sample-v1.json", "live/manifests/sample-en-v1.json"]


@pytest.mark.parametrize("name", OUTPUTS)
def test_outputs_match_the_expected_files(job, name):
    got = (job / name).read_text(encoding="utf-8")
    want = EXPECTED / name
    if UPDATE:
        want.parent.mkdir(parents=True, exist_ok=True)
        want.write_text(got, encoding="utf-8")
    assert want.exists(), f"{want} is missing: regenerate with EXSCRIPTOR_UPDATE_EXPECTED=1"
    assert got == want.read_text(encoding="utf-8"), (
        f"{name} changed. If intended, regenerate with EXSCRIPTOR_UPDATE_EXPECTED=1 and commit the diff.")
