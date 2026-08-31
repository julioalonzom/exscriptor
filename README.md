# Exscriptor

Programmatic infrastructure for agent-assisted digitization of historical
scholarly texts.

`exscriptor` is a Python package + CLI carrying the pipeline
primitives proven on real digitization projects (Summa contra Gentiles,
Summa theologiae, Billuart, and others): getting a printed edition off the
page and into clean, structured, verifiable text with AI agents doing the
reading.

Built agent-native but harness-agnostic: the stable interface is plain
Python imports and CLI commands, so it works with Hermes, Claude Code,
Codex, or any future agent harness — or a human.

## The patterns it encodes

**Native Gemini Batch for VLM transcription.** OpenRouter's batch API cannot
carry inline images for Gemini models — the main reason this runner exists.
Pages go to the native Gemini Batch API as inline JPEGs (15 pages/batch,
~18MB payloads, safely under the 20MB inline limit), at roughly half the
sync price. Job state is a resumable JSON file; re-running submits only
missing pages. Pages the model refuses (RECITATION-style refusals) fall back
to OpenRouter sync.

**The scan's own OCR as a second witness.** The PDF's text layer knows no
Latin, so it never regularizes — an independent check on the VLM that flags
where to look harder at the page image, without ever being a source.

**A collation oracle that is a witness, never a source.** A reference text
(e.g. Corpus Thomisticum HTML chunks) is parsed into per-chapter gold texts
and used only for collation — word-set disagreements and length ratios tell
you where transcription deserves a second look. Nothing is ever copied from
it. Default filename pattern is SCG-shaped but fully parameterizable
(`CT_DIR`, `CT_GLOB`).

**Zone-marker page files.** Transcription lands in per-page markdown with
explicit zone markers (`<<<THOMAS>>>` etc. — named zones are yours to
choose), so multi-voice prints (author vs. commentator apparatus) assemble
into clean per-voice streams. `check_markers` screens marker balance per
page.

**Deterministic conversions in code, not prompts.** Ligature expansion and
small-capital flattening live in `edition_rules`, applied in code: stating a
deterministic substitution in a prompt costs accuracy without buying
obedience. The small-capital flattener is structural, not a word list —
Roman numerals and manuscript sigla survive, whole-emphasized heading lines
are skipped.

## Two workflows, one rule of thumb

| | VLM transcription | OCR transcription |
|---|---|---|
| Print | complex, older | newer, clean text layer |
| Engine | Gemini Batch (+ OpenRouter sync fallback) | pdftotext + cleanup pass |
| Witness | OCR layer + reference collation | OCR layer + reference collation |

Both end the same way: per-page files → assembly → QA gates → your corpus.

## CLI

```
ex-batch-submit    submit pages to native Gemini Batch (resumable)
ex-batch-poll      poll + harvest finished batches
ex-batch-raw       dump full OpenRouter batch JSON (errors included)
ex-poll-batch      poll an OpenRouter batch by id
ex-ct-oracle       parse reference chunks, per-chapter gold texts
ex-check-markers   zone-marker / marginalia balance screen
```

## Python

```python
from exscriptor.gemini_batch_run import submit, poll, harvest
from exscriptor.ct_oracle import load, collate
from exscriptor.ocr_layer import ocr_words
from exscriptor.edition_rules import clean
from exscriptor.credentials import credential
```

## Credentials

Nothing ships with hardcoded paths. Export credentials as env vars
(`GEMINI_API_KEY`, `OPENROUTER_API_KEY`, ...) or point `DIGITIZATION_ENV`
(or `SCHOLA_ENV`) at a `.env` file. Values are read at runtime only;
importing the package never touches the filesystem or network.

## Install

```
pip install exscriptor
```

## License

MIT
