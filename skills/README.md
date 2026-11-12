# Skills: digitizing and translating for Schola Thomistica

These are [agent skills](https://support.claude.com/en/articles/12512176-what-are-skills):
instructions an agent loads when a task needs them. Together they take a
scanned public-domain edition to a finished batch staged on
[Schola Thomistica](https://scholathomistica.com): Latin, translation, or
both. exscriptor does the mechanical part (normalization, assembly, the
gates); the skills say when to run what, and what to judge yourself.

Policy (what is published, spelling, punctuation, notes) is the editorial
handbook, https://scholathomistica.com/handbook. `reference/house-style.md`
says how each rule is applied with exscriptor.

## Which skill for which job

| Skill | For |
|---|---|
| `reconnaissance` | measure the print before reading it: scope, the section tree, paragraph and note devices, the abbreviation inventory, the reading brief |
| `diplomatic-transcription` | the page-file contract every reader and every fix follows |
| `scan-transcription` | read the pages (diplomatic → `expand` → `assemble`); choose the reader |
| `transcription-qa` | the independent check: screens, the editor and punctuation passes, adjudication on the page, the ledger |
| `translation` | translate, with the translator as the Latin's second reader |
| `paragraph-alignment` | read source and translation in pairs; required for any batch with a translation |
| `corpus-import` | build, preflight and stage the batch with your own key |

A whole job runs them in that order: reconnaissance → scan-transcription →
transcription-qa (QA-1) → translation → transcription-qa (QA-2) →
paragraph-alignment → corpus-import. A translation of a work already live
starts at `translation`.

## Setting up

1. **Install exscriptor** (Python 3.10+):
   ```bash
   pip install git+https://github.com/julioalonzom/exscriptor.git
   ```
   Every command in the skills is `python3 -m exscriptor.<module>`; each has
   `--help`. Poppler (`pdftoppm`, `pdftotext`, `pdffonts`) renders and reads
   the scans; Tesseract is an optional extra OCR witness.
2. **Give the skills to your agent.** In Claude Code, clone this repository
   and link the skills into your skills folder (the `reference` folder goes
   with them, because the skills point to it):
   ```bash
   git clone https://github.com/julioalonzom/exscriptor.git ~/exscriptor
   mkdir -p ~/.claude/skills && ln -s ~/exscriptor/skills/* ~/.claude/skills/
   ```
   `git -C ~/exscriptor pull` then keeps the tools and the skills current
   together. Any agent that can read files and run a shell can use them the
   same way: point it at this README.
3. **Your key, to stage batches.** A magister creates an agent key at
   https://scholathomistica.com/admin/agent-submissions ("Agent tools").
   Put it in the environment, never in a file the agent commits or prints:
   ```bash
   export SCHOLA_API_URL=https://api.scholathomistica.com
   export SCHOLA_IMPORT_TOKEN=<the key>
   ```
   The key stages pending batches only. Another editor approves them; nobody
   approves their own.

A first prompt that works: *"Read ~/exscriptor/skills/README.md. Then run
reconnaissance on <the PDF or archive.org item>, for <the work and its
page range>, and stop when the brief is written so I can read SCOUT.md."*

## Rules that hold in every skill

**Staged means finished.** The editor who approves a batch does not
proofread it, adjudicate, look anything up or fill anything in. Before
staging:
- every doubtful reading is settled on the page image;
- zero `⟦…⟧`, `[illegible]`, `(?)`, placeholders or TODOs; no sentence cut
  off; no note for someone else in the text, a title or the summary;
- `python3 -m exscriptor.preflight <manifest>` passes.

A reading that cannot be settled after the evidence ladder
(`transcription-qa`, "Adjudication") takes the best reading from context
and the Latin, an inline `^[Editor's note: …]` saying what the print has,
and a ledger row with `"escalate": true`. Stage it, and list those sites in
your report. Stop and ask before staging only if they are dense (more than
about one per 5,000 words) or touch structure or titles.

**The print is the arbiter.** Its OCR layer is the second witness; Corpus
Thomisticum and other digital editions are witnesses, never sources.

**Normalization is code, not judgement.** Readers copy the print; `expand`
normalizes it; the spelling list ships with exscriptor and grows by pull
request (`../CONTRIBUTING.md`). No hand edits of spelling, ever.

**Fix the source and rebuild forward.** Fix content in the diplomatic page
files, re-run `expand` and `assemble`, rebuild the manifest. Never
re-transcribe a page to fix it, and never patch an assembled file or a
manifest: the next build reverts it.

**Money.** No paid API (a vision model, a translation model) runs unless the
person paying authorized that route for this job. A key in the environment
is not permission. The default reader is the agent's own vision.

**Subagents write files.** Results live on disk in the work's folder; the
parent harvests files, never replies. Parallel agents get disjoint pages or
sections, never shared files.

## The work folder

Everything about a job lives in its folder, so a fresh session can finish
it from the files alone:

| Path | What | Who writes it |
|---|---|---|
| `README.md` | the work, its edition, decisions, gotchas | agents, as they learn |
| `work.json` | the job: languages, pages, reader, `page_files` | reconnaissance |
| `SCOUT.md`, `structure.json`, `FORMATTING.md` | the measured print; the section tree | reconnaissance |
| `ABBREVIATIONS.md`, `abbreviations.tsv` | a print with marks: the mark inventory | reconnaissance |
| `TRANSCRIBE_INSTRUCTIONS.md` | the reading brief | reconnaissance |
| `pages/pg-NNN.jpg` | the renders | reconnaissance |
| `diplomatic/pg-NNN.md` | the reading, **source of truth** | readers; fixes by adjudicators |
| `edition/`, `expansions.tsv`, `pending.tsv`, `long-s.tsv` | derived by `exscriptor.expand run` | never by hand |
| `decisions.tsv`, `punctuation.tsv` | the editor's and the punctuation pass's answers | QA |
| `assembled/<key>.md` | sections, by `exscriptor.assemble` | never by hand |
| `ledger.jsonl` | every doubt, verdict and evidence (`exscriptor.ledger`) | critic, translators, adjudicator |
| `translation-<lang>/<key>.md` | translations, one block per Latin block | translators |
| `alignment/<stem>.json` | alignment readings | alignment reader |
| `manifests/<stem>.json`, `<stem>.preflight.json` | the batch and its gate report | your build script; `exscriptor.preflight` |
| `orthography-allow.txt`, `preflight-waivers.json` | exceptions, each with a reason | agents |
| `tmp/` | scratch: nothing durable lives only there | anyone |

`python3 -m exscriptor.status <work>` computes where a job stands from these
files and names the next step.

## Improving the skills

Friction in exscriptor is exscriptor's bug: open an issue or a pull request
on github.com/julioalonzom/exscriptor rather than working around it. A rule
a job had to settle (a convention, a form of note) belongs in the skill or
the house style, so the next agent does not have to judge it again.
