---
name: corpus-import
description: Build, check and stage Schola Thomistica corpus-import manifests (new works, added sections, added translations, facsimiles) with your own scoped agent key, for an editor's approval. Use when submitting a transcription or translation batch through the corpus-import API, checking a manifest's quality, licensing and provenance, or recovering a staged batch after a timeout.
---

# Corpus import

Stage finished material through the reviewed import pipeline. Your agent
creates and submits pending batches; it can never approve, reject or write
the corpus directly. Publication is always a separate decision by another
editor: nobody approves their own batch.

Read `../reference/api.md` (the endpoints, the modes, every `edit`
operation, licences, commentary works), `../reference/manifest-schema.json`
(the exact manifest the server accepts; unknown fields are refused) and
`../reference/translation-example.json`. The editorial handbook,
https://scholathomistica.com/handbook, is the authority for policy.

The key's owner is accountable for what is staged, not automatically the
text's author. The actual human transcriber or translator is attributed
regardless of whose key staged the batch.

## The key

A magister creates an agent key at
https://scholathomistica.com/admin/agent-submissions ("Agent tools"). Keep
it in an environment variable, `SCHOLA_IMPORT_TOKEN`, with
`SCHOLA_API_URL=https://api.scholathomistica.com`. Never print, log, commit or
send it anywhere except in the `Authorization` header to that origin. Never
use any other credential (review, database, storage, deployment).

## The modes

| You want to… | `mode` | key |
|---|---|---|
| put a new work on the site | `create` | Magister |
| add sections to a live work, after the existing ones | `append_sections` | Magister |
| add a language a live section does not have yet | `append_texts` | Magister |
| attach or replace a live work's page scans | `attach_facsimile` | Magister |
| change anything that exists: correct text, insert front matter, move, retype, retitle, loci, relations, work fields | `edit` | Custos |

A magister who needs an `edit` (a correction to live text, a retitle)
reports it to the Custos with the section id, the exact old and new text and
the evidence; it is not staged as an append. `append_texts` cannot replace a
language, and a titles-only append is refused for having no texts.

**Staging is a full dry run.** The server applies the batch to production
inside a transaction and rolls it back, so every error approval would raise
comes back at staging and the batch is refused. A staged batch passes
approval unless production changes in between.

## Boundary

- **Public-domain or clearly open-licensed material only.** Licensing and
  provenance are part of the corpus, not a note.
- **Licences** (`../reference/api.md`, "Licences"): text you transcribed,
  edited or translated from a public-domain print carries `CC-BY-4.0` with
  an attribution line; a third party's text keeps its own licence. Never
  `CC0-1.0` for your own work: a published CC0 text can never be taken back.
- **No OCR noise, generated filler or guessed missing passages.** Report
  unresolved readings and agent involvement honestly.
- **A staged batch is finished** (`../README.md`, "Staged means
  finished"). The editor who approves it clicks; they do not proofread,
  adjudicate, look anything up or fill anything in. Zero `⟦…⟧`,
  `[illegible]`, `word?` placeholders, truncated sentences, open ledger rows
  or notes for someone else. A printed conjecture is not a placeholder: it
  stays the note it is, `^[word?]`.

## Workflow

1. **Read production first** for any batch that touches a live work (next
   section). A local file or an old manifest is not evidence of what is
   live.
2. **Build the manifest with the builder**, never by hand:

   ```bash
   python3 -m exscriptor.manifest <work> --mode create --languages la,en --out <work>/manifests/<stem>-v1.json
   ```

   It reads `work.json`'s `manifest` block, `structure.json`, `assembled/`
   and `translation-<lang>/` (`--help` has the contract and the modes:
   `create`, `append_sections`, `attach_facsimile`), emits one section per
   node in order with `parent_key` chains, and refuses, writing nothing, on
   a missing text or title translation, a block-count mismatch, a licence
   slip or an author the library already holds. A translation of a live
   work is `python3 -m exscriptor.append_texts` (`translation`). For the
   builder, name a revision `<stem>-v2.json` and its batch slug follows the
   file's version; `append_texts` takes the new slug as `--batch-slug`.
3. **Check it** ("Checking a manifest").
4. **Send the page scans**, if the batch carries a facsimile:

   ```bash
   python3 -m exscriptor.upload_scans <work>/manifests/<stem>.json
   ```

   It sends each render the rows name (from `<work>/pages`, or `--pages`)
   with your key and writes its `sha256` into every row. The pages stay
   private until another editor approves the batch. Run it after the last
   rebuild: a rebuild drops the hashes.
5. **Preflight** the exact file:

   ```bash
   python3 -m exscriptor.preflight <work>/manifests/<stem>.json --lexicon <lexicon>.json
   ```

   It writes `<stem>.preflight.json`, bound to the file's sha256: residue,
   metadata, orthography (texts and titles), the spelling list, seams,
   block/footnote/link parity, alignment, the ledger, facsimile order. A
   genuinely acceptable finding is waived per finding, with a reason, in
   `<work>/preflight-waivers.json`; never per gate. Edit nothing after
   preflight. Then compare a few random sections word by word against the
   page images: that catches what no gate can (misreads that form valid
   Latin, broken nested italics).
6. **Submit** ("Submitting").
7. **Report** the batch id, slug, status, the per-work counts in
   `validation_report.works`, any warning, and what you verified (screens,
   gates, adjudication). Do not ask the approver to check content: anything
   a human would have had to decide is decided, with its evidence, in the
   work's ledger.

## Read production before touching a live work

- `GET /api/works/{slug}/outline`: the whole nested tree with ids, parents,
  sequences, types, loci and relations. (`/api/works/{slug}` lists only the
  top level.) Flatten it recursively and assert the count.
- `GET /api/works/{slug}/sections/texts?section_ids=A&section_ids=B`: text
  ids, exact content and sources (repeat the parameter, about 20 per
  request).
- `GET /api/corpus-imports/works/{slug}/guard-context`: the stored sources
  in full. Name an existing `source_key` without redeclaring it, or copy it
  byte for byte: a reused key whose metadata differs in any field is
  refused. A genuinely new source gets a fresh key.
- Match the live `section_type` and titling, not just the nesting.

Read immediately before building: ids and text ids change when other
batches are approved.

## Checking a manifest

- `schema_version`, `batch_slug`, `title`, `summary`; every text names a
  declared or existing source; source URL, licence, rights basis and
  attribution are present, with real evidence. Never a temporary signed
  scan URL as provenance.
- **One entry per work slug per manifest.**
- **Authors before `create`.** `GET /api/authors/<slug>`; name an existing
  author with `author_slug`. A new author goes in `authors` with supported
  birth and death years. Never guess an author; if unsure, ask the human.
- **The hierarchy is the printed contents'.** Never flatten what the TOC
  nests. Express it ONLY as a flat section list with `parent_key` (inside
  the manifest) or `parent_path` (a live parent): a nested `children` array
  is not part of the schema. Leave `sequence` out unless you need it: new
  sections follow list order after the existing ones.
- **Cross-work citations are linked before staging.** Convert references to
  live works into `[[display|canonical-key:locus]]` after reading the
  target's `canonical_key` and outline; emit only loci that resolve, and
  leave references to unkeyed or absent works as plain text. Guard the
  attribution: a citation governed by another author's name
  (`Caietan. in hoc art.`) is that author's reference, not a link to the
  commented work. Pending batches cannot be edited, so a missed pass means
  a reject and restage.
- **Commentary works**: a fully qualified `commented_locus` and a
  `commentary_on` relation on the commentary, repeated in every append; a
  path-only `canonical_locus` on the base. Publish only the commentator's
  words (`../reference/api.md`, "Commentary works").
- **Footnotes are inline** `^[…]`, never numbered references, and never
  nested: an editor's note about a footnote goes at its end in plain square
  brackets. Counts match across languages, in order; the one allowed extra
  is a note beginning "Editor's note". Count `^[` starts, not
  bracket-balanced matches.
- **Translations pass `paragraph-alignment` before staging.** Equal block
  counts do not prove alignment, and the platform only *warns* on a count
  mismatch. Where the source hard-wraps so that a line starts with a
  numbered citation, the translation keeps the same line start, or the
  parser folds list items and the counts diverge.
- **Every included section has a nonblank `title_translations[lang]`** for
  each language staged, parents and prologues included.
- **`show_section_label: false`** when the title only restates the type
  ("Prologus", "Liber Primus"); keep the label when the title carries real
  rubric content.
- **A work digitized and translated in one job goes up as ONE `create`**
  with both languages. `append_texts` is for a translation made after the
  Latin went live, translated from the live text.
- **The append that completes a work** may carry
  `update_work {expected, set}` (`is_complete`, the description) with a
  Custos key; otherwise tell the Custos the work is complete.

## Submitting

```bash
python3 -m exscriptor.submit <work>/manifests/<stem>.json [--supersedes-batch-id <id>]
```

It refuses, before sending, a manifest without a passing preflight report
for its exact bytes, a source of ours under the wrong licence, and a declared
author the library already holds. It records the batch (id, status, sha256)
in `<work>/staged.jsonl`, and exits 2 when the batch was staged with a
warning: a warning is a defect, so stage a revision. A 400 carries the
staging report: fix the source and rebuild, never retry blindly.

After approval, `python3 -m exscriptor.batch_status <work> --require approved`
exits 0. Draw lessons from approved batches only.

## Revisions, retries and order

- **Same owner, slug, payload and predecessor** is an idempotent retry.
  After a timeout, `GET /api/corpus-imports?batch_slug=<slug>` finds the
  batch before you resubmit.
- **A slug is consumed even by a refused or failed batch.** Build the
  version into the slug (`-v2`, `-v3`) and rename the file.
- **A pending batch cannot be edited.** Correct it with a revision:
  `"supersedes_batch_id": <id>` beside the manifest, same work slugs, same
  human owner. Only the tip is reviewable; approving it rejects the pending
  ancestors.
- Run every content screen before staging: a defect found while the batch
  is pending costs a round trip through the approver.
- Two pending batches on one work are approved in dependency order: a Latin
  correction before the translation built on it. Never re-segment a
  translation to mirror a defective live Latin.
- Only the key's owner reads a batch; a foreign id is a 404.

## Pitfalls (each shipped once)

- A flat import built from a stale note, not the live outline. Always fetch
  the outline before extending a work.
- A source re-declared with one field retyped: refused. Copy from
  guard-context.
- `parent_path` for a parent created in the same manifest: refused. Use
  `parent_key`.
- A top-level outline walk taken for the whole work (7 of 799 sections).
- A nested `children` shape silently dropped by an older schema: validate
  against the schema, then fetch the stored batch back and assert what was
  persisted.
- Print accents, ligatures or an own-line machine note left in the text:
  rejected in review. Remove an artifact's WHOLE line, never part of it.
- Valid-looking misreads and broken nested italics passed every mechanical
  gate: the word-by-word sample against the page images caught them.
