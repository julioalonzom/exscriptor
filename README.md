# Exscriptor

Python library + CLI for digitizing scanned scholarly texts — getting a
printed edition off the page and into clean, structured, verifiable text,
with AI agents doing the reading.

The stable interface is plain Python imports and CLI commands, so it works
with any agent harness (or a human at a terminal).

## What it does

- **VLM transcription at scale** — submits page images to the Gemini Batch
  API (images inline, 15 pages per batch, resumable) and harvests the
  transcriptions into per-page files. Re-running submits only missing
  pages.
- **Second witness** — reads a second OCR pass over the page images
  (the PDF's embedded text layer via `ocr_layer`, or a fresh run from any
  engine producing `{filename: text}` JSON — e.g. macOS Vision) as an
  independent check on the transcription: it flags where the two disagree,
  so a human or agent knows where to look harder at the page image.
- **Witness collation** — if a digital edition of the same work exists,
  parses it into per-chapter reference text and collates word-level
  differences and length ratios against the transcription. Used to
  *adjudicate*, never to *source*: nothing is copied from a witness into
  the output.
- **Deterministic cleanup** — ligature expansion and small-capital
  flattening applied in code rather than asked for in a prompt (deterministic
  substitutions belong in code, where they always happen, not in a prompt,
  where they sometimes happen).
- **Structure screens** — checks that footnote/apparatus markers on a page
  balance against their corresponding notes, so broken pairings surface
  before assembly, not after.
- **Edition-orthography screen** — fails a normalized text that still
  carries the print's letterforms: unexpanded abbreviation marks (`nõ`,
  `ꝓ`, `⁊`), long s, ligatures, `&`, consonantal `j`, print accents,
  vowel-value `V` in capitals. Screens manifest section titles too.
- **Corpus lexicon** — builds a form-frequency lexicon from *your own*
  adjudicated texts, lists out-of-vocabulary forms (misreads that are not
  words), and decides nasal-bar expansions (`tamẽ` → *tamen*, not *tamem*)
  by the lexicon instead of a positional rule.
- **Diplomatic → edition** (`expand`) — derives the normalized edition
  pages from a diplomatic transcription of any print: the edition's own
  abbreviation table, safe built-in rules, lexicon-decided nasal bars and
  u/v (`--keep-uv` for a print whose u/v already follows the house rule),
  words hyphenated across a page break decided on the joined word, a
  long-s doubt report (empty for a print without long s), and an
  `expansions.tsv` that records every change (reproducible, and a training
  pair per row). Anything undecidable waits in `pending.tsv` and
  `long-s.tsv` until the editor answers it in `decisions.tsv`.
- **One assembler** (`assemble`) — page files to section texts: seam joins,
  footnote continuations, dropped layers, structure split with a round-trip
  check, and per-section invariants; it refuses rather than warns.
- **Defects ledger** (`ledger`) — one JSONL schema for every doubt, its
  verdict and evidence; `check` proves each correction is present in every
  text layer.
- **Paragraph alignment** (`alignment`) — flags the source/translation pairs
  that must be read (ratio outliers, each section's last pair, a seeded
  sample), records the reading, and refuses text that changed after it.
- **Preflight** (`preflight`) — every pre-staging gate on the exact manifest,
  with a report bound to the file's sha256 that a submit step can require.
- **Computed status** (`status`) — a work's stage derived from its files,
  with the next step named.
- **Guard** (`guard`) — the work-dir contract as a policy a harness enforces
  before a tool call runs: no hand edits to derived files, no reading
  secrets, no paid route without a grant, writes confined to a territory.
  Includes a Claude Code `PreToolUse` hook.
- **Incidents** (`incidents`) — papercuts as data: each friction a run hits,
  its cause, where the fix belongs, and a pointer to where the right answer
  already lives; clustered across works.
- **Replay** (`replay`) — cheap verification of a proposed rule: re-run only
  the units it should fix (targets) and a fixed spread of finished pages
  (sentinels), scored deterministically against the adjudicated text.
- **Page images** (`render`) — the image of page N, found or rendered from
  the source PDF.
- **Credential resolution** — reads API keys from env vars or a `.env`
  file. No hardcoded paths, nothing read at import time.

## Install

```
pip install git+https://github.com/julioalonzom/exscriptor.git
```

## Quick start

Transcribe a run of pages from a directory of JPEGs (one `pg-NNN.jpg` per
page) using a prompt file you supply:

```bash
ex-batch-submit \
  --pages 1-120 \
  --images /path/to/page-images \
  --out runs/my-edition \
  --jobs runs/my-edition/jobs.json \
  --prompt-file prompt.txt
```

Poll until the batches finish and write `runs/my-edition/pg-NNN.md`:

```bash
ex-batch-poll --jobs runs/my-edition/jobs.json --out runs/my-edition --wait 600
```

Check every transcribed page for unbalanced footnote/apparatus markers:

```bash
ex-check-markers runs/my-edition --pages 1-120
```

Collate a transcribed chapter against a digital witness of the same work:

```python
from exscriptor.witness import load, collate

chapters = load(3)                      # liber/chapter number your witness uses
gold = chapters[5]["text"]
report = collate(my_transcription, gold)
print(report["ratio"], report["only_ours"], report["only_gold"])
```

## Concepts

**Page files.** The unit of work is one markdown file per scanned page
(`pg-NNN.md`). Downstream tools (assembly, QA, corpus building) operate on
these; fix problems by editing them, not by re-transcribing.

**Zone markers.** A page whose print carries multiple voices (author,
commentator, apparatus, marginalia) is transcribed into named zones:

```
<<<AUTHOR>>>
...
<<<COMMENTATOR>>>
...
```

Zone names are yours to choose; the default set is `AUTHOR,COMMENTATOR`
(configure with `DIGITIZE_ZONES`). This is what lets a multi-voice print
assemble into clean per-voice streams.

**Witnesses, never sources.** The scan's OCR layer and any digital edition
of the work are witnesses: they tell you where the transcription deserves a
second look. The scanned page itself is the only source; nothing from a
witness is copied into the output.

## CLI

```
ex-batch-submit    submit pages to Gemini Batch (resumable job list)
ex-batch-poll      poll batch status and harvest finished pages
ex-batch-raw       dump the full JSON of one OpenRouter batch (errors included)
ex-poll-batch      poll an OpenRouter batch by id, print status until done
ex-witness         parse a digital witness into per-chapter reference texts
ex-check-markers   zone-marker / marginalia balance screen
ex-screen-script   foreign-script lookalike characters (Cyrillic е for e)
ex-screen-orthography  print letterforms left in a normalized edition text
ex-lexicon         build | oov | nasal — corpus lexicon, OOV screen, m/n expansion
ex-expand          run | brief — diplomatic -> edition pages; the reading brief from the mark table
ex-assemble        page files -> section texts (fails closed)
ex-seams           paragraph-seam gate (and the hash-bound boundary audit)
ex-ledger          validate | triage | check | summary — the defects ledger
ex-alignment       screen | show | check — paragraph alignment
ex-preflight       every pre-staging gate; writes <manifest>.preflight.json
ex-status          a work's stage, computed from its files
ex-guard           check | claude-hook — may this tool call run?
ex-incidents       add | list | cluster | close | validate — papercuts as data
ex-replay          sentinel | from-incidents | run | compare | gate — verify a change
ex-render          the image of page N of a work
```

The last group assumes a work directory laid out as `status` documents
(`work.json`, `diplomatic/` or `transcription/`, `edition/`, `assembled/`,
`ledger.jsonl`, `translation-<lang>/`, `manifests/`, `staged.jsonl`).

Every CLI is also `python3 -m exscriptor.<module>`, which works even where
the console scripts are not on `PATH`.

## Python

```python
from exscriptor.gemini_batch_run import submit, poll, harvest
from exscriptor.witness import load, collate
from exscriptor.ocr_layer import ocr_words
from exscriptor import edition_rules
from exscriptor.credentials import credential
```

## Configuration

Credentials (read at call time, never at import time):
`GEMINI_API_KEY`, `OPENROUTER_API_KEY`. Set them as env vars or point
`DIGITIZATION_ENV` at a `.env` file containing them.

Knobs: `DIGITIZE_ZONES` (zone names), `WITNESS_DIR` / `WITNESS_GLOB` /
`WITNESS_HEADER_REGEX` (where and how to find witness chunks).

## Policies vs. mechanisms

Exscriptor carries mechanisms. Your project carries policies: the house
formatting rules (a FORMATTING.md-style document), the per-edition
transcription prompt, and the OCR cleanup-pass instructions given to
subagents. See [docs/house-rules-and-prompts.md](docs/house-rules-and-prompts.md)
for the layout that works and what goes where.

## Status

Beta. The API may still move; early adopters' friction is welcome input.

## License

Apache-2.0
