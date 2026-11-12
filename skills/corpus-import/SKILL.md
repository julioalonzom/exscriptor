---
name: corpus-import
description: Stage a batch on Schola Thomistica. Build the manifest, preflight it, send its scans, and submit it with your agent key for an editor's approval. Use when a finished transcription or translation is ready to stage, a staged batch needs a revision, or a submission timed out.
---

# Corpus import

Your agent creates and submits pending batches. Another editor publishes
them; nobody approves their own batch, and the key can never write the
corpus directly. The key's owner answers for what is staged. The person who
actually transcribed or translated the text is credited, whoever's key
staged it.

The contract: `../reference/api.md` (endpoints, modes, every `edit`
operation, licences, commentary works) and
`../reference/manifest-schema.json` (unknown fields are refused). For
policy, the editorial handbook at https://scholathomistica.com/handbook has
the last word.

## The key

A magister creates an agent key at
https://scholathomistica.com/admin/agent-submissions ("Agent tools"). Keep
it (it begins `stci_`) in `SCHOLA_IMPORT_TOKEN`, with
`SCHOLA_API_URL=https://api.scholathomistica.com`. It goes only into the
`Authorization` header to that origin: never printed, logged, committed or
sent elsewhere. Use no other credential.

## The modes

| You want to… | `mode` | key |
|---|---|---|
| put a new work on the site | `create` | Magister |
| add sections to a live work, after the existing ones | `append_sections` | Magister |
| add a language a live section does not have yet | `append_texts` | Magister |
| attach or replace a live work's page scans | `attach_facsimile` | Magister |
| change anything that exists: correct text, insert front matter, move, retype, retitle, loci, relations, work fields | `edit` | Custos |

A magister who needs an `edit` reports it to the Custos with the section
id, the exact old and new text and the evidence.

**Staging is a full dry run.** The server applies the batch to production
inside a transaction and rolls it back, so every error approval would raise
comes back now and the batch is refused. A staged batch passes approval
unless production changes in between.

## What may be staged

- **Public-domain or clearly open-licensed text**, with its provenance.
  Licences: `../reference/api.md`, "Licences". Text we made from a
  public-domain print is `CC-BY-4.0`; a third party's keeps its own licence.
- **Finished text only** (`../README.md`, "Staged means finished"): every
  reading settled, every ledger row closed, no placeholder. The approver
  clicks; they do not proofread. A printed conjecture is the edition's
  apparatus and stays as its note, `^[word?]`.

## Workflow

1. **Read production**, for a batch on a live work:

   ```bash
   python3 -m exscriptor.snapshot <slug> --out <work>/tmp/live.json
   ```

   The whole tree with ids, parents, types, loci, relations and every
   current text. Stored sources come from
   `GET /api/corpus-imports/works/{slug}/guard-context`. Ids change when
   other batches are approved, so read right before building. Done when
   the snapshot is from today and the new sections match its
   `section_type` and titling.

2. **Build** with the builder; a hand-written manifest skips its checks.

   ```bash
   python3 -m exscriptor.manifest <work> --mode create --languages la,en --out <work>/manifests/<stem>-v1.json
   ```

   It reads `work.json`'s `manifest` block, `structure.json`,
   `assembled/` and `translation-<lang>/` (`--help` has the contract and
   the modes), emits one section per node with `parent_key` chains, and
   refuses on a missing text or title, a block-count mismatch, a licence
   slip or an author the library already holds. A translation of a live
   work is `python3 -m exscriptor.append_texts` (`translation`). Done when
   it writes the file.

3. **Check** what the builder cannot ("Checking a manifest"). Done when
   every item there holds.

4. **Send the scans**, for a batch with a facsimile:

   ```bash
   python3 -m exscriptor.upload_scans <work>/manifests/<stem>.json
   ```

   It sends each render the rows name (from `<work>/pages`, or `--pages`)
   and writes its `sha256` into the row; the pages stay private until
   approval. A rebuild drops the hashes, so this runs after the last
   rebuild. Done when every facsimile row has a `sha256`.

5. **Preflight** the exact file:

   ```bash
   python3 -m exscriptor.preflight <work>/manifests/<stem>.json --lexicon <lexicon>.json
   ```

   It writes `<stem>.preflight.json`, bound to the file's sha256. A
   genuinely acceptable finding is waived per finding, with its reason, in
   `<work>/preflight-waivers.json`. Then compare a few random sections word
   by word with the page images: misreads that form valid Latin and broken
   nested italics have passed every gate. Done when the report says passed
   and the file is unchanged since.

6. **Submit:**

   ```bash
   python3 -m exscriptor.submit <work>/manifests/<stem>.json [--supersedes-batch-id <id>]
   ```

   It sends only a file with a passing preflight report for its exact
   bytes, and records the batch in `<work>/staged.jsonl`. Exit 2 means
   staged with a warning: a warning is a defect, so stage a revision. A 400
   carries the staging report: fix the source and rebuild. After a timeout,
   send the same file again: same owner, slug and payload is a retry, not a
   second batch. Done when the batch is pending without a warning.

7. **Report** the batch id, slug, status, the counts in
   `validation_report.works`, and what you verified. Done when nothing in
   the report asks the approver to check content.

After approval, `python3 -m exscriptor.batch_status <work> --require approved`
exits 0. Draw lessons from approved batches only.

## Checking a manifest

- **Sources:** each has a URL, licence, rights basis and attribution, with
  real evidence; a temporary signed scan URL is no provenance. A live
  source is named by its `source_key` and left undeclared, or copied byte
  for byte from guard-context: a reused key with any field different is
  refused. A new source gets a fresh key.
- **Authors:** an existing author by `author_slug`; a new one in `authors`
  with supported birth and death years. An author you cannot establish
  goes to the human.
- **The hierarchy is the printed contents'**, as a flat section list with
  `parent_key` (inside the manifest) or `parent_path` (a live parent).
  Sections follow list order after the existing ones.
- **Cross-work citations are links**: `[[display|canonical-key:locus]]`
  after reading the target's `canonical_key` and outline, for loci that
  resolve; plain text for unkeyed or absent works. A citation governed by
  another author's name (`Caietan. in hoc art.`) is that author's
  reference, not a link to the commented work.
- **Commentary works**: a fully qualified `commented_locus` and a
  `commentary_on` relation in every batch, the commentator's words only
  (`../reference/api.md`, "Commentary works").
- **Footnotes** are inline `^[…]` and never nested; an editor's note about
  a footnote goes at its end in plain brackets. Counts match across
  languages, in order, the one extra allowed being a note that begins
  "Editor's note"; count `^[` starts.
- **Translations** have passed `paragraph-alignment`: equal block counts do
  not prove alignment.
- **Titles:** every section has a nonblank `title_translations[lang]` for
  each language staged; `show_section_label: false` where the title only
  restates the type ("Prologus").
- **One job, one `create`:** a work digitized and translated in one job
  goes up with both languages. The append that completes a work may carry
  `update_work {expected, set}` with a Custos key; otherwise tell the
  Custos.

## Revisions and order

- **A pending batch is corrected by a revision:** the next version in the
  slug (`-v2`) and file name, and `--supersedes-batch-id`. Same work slugs,
  same owner; approving the tip rejects its pending ancestors. A slug is
  spent even by a refused batch.
- **Two pending batches on one work** are approved in dependency order: a
  Latin correction before the translation built on it. A translation
  follows the corrected Latin, never a defective live one.
- **Each screen runs before staging:** a defect found while the batch is
  pending costs a round trip through the approver.
- **A print artifact or machine note** goes with its whole line.
