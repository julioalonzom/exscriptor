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
- **Second witness** — reads the scanned PDF's own OCR text layer as an
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
ex-check-markers --runs runs/my-edition --pages 1-120
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
ex-batch-raw       dump the full JSON of one batch (errors included)
ex-poll-batch      poll a batch by id, print status until done
ex-witness         parse a digital witness into per-chapter reference texts
ex-check-markers   zone-marker / marginalia balance screen
```

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

## Status

Beta. The API may still move; early adopters' friction is welcome input.

## License

Apache-2.0
