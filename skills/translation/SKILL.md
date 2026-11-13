---
name: translation
description: Translate approved scholastic Latin into a faithful, paragraph-aligned text in a requested target language (English by default), from a verified local transcription in a from-scratch job or from the live text in a translate-only job. The translator also serves as the Latin's second reader and ledgers every doubt. Alignment and staging gates follow.
---

# Translation

Produce the best scholarly translation you can: precise, faithful to the
argument and to the register of the source, with exactly one target block
for each blank-line-delimited Latin block. Full prose for every block,
always. A summary, a "concise rendering", or a `[Block N: …]` placeholder is
a failure, never a stage, whatever the size of the run. Nobody retranslates
after you: the editor who approves does not proofread (`../README.md`,
"Staged means finished").

## Required boundary

- Read the work's README and `corpus-import`.
- Translate only approved Latin. Never repair, normalize or modernize the
  Latin while translating: doubts go to the ledger.
- Existing translations are comparators, not ground truth. Verify the
  translation's rights independently of the source edition's.
- Default execution is subagents on your own harness's model. An API route
  runs only when the person paying authorized it for this job; never
  hard-code a model name.
- If the live source diverges from the print, do not translate against the
  defective text: a Latin correction goes first (`corpus-import`, "Changing a
  live work"), and adjudicating the reading is `transcription-qa`.

## Which Latin to translate

- **From scratch** (new work, nothing live): translate the verified local
  assembly in `<work>/assembled/`. Latin and
  translation stage together in one `create` batch.
- **Translate-only** (the Latin is live): save the current Latin in the work
  dir (`python3 -m exscriptor.snapshot <slug> --out <work>/live.json`),
  because imports may have re-split blocks. Translate from that snapshot, and re-pull it right
  before building the manifest; if it changed, re-translate the affected
  sections. Write one `<section_id>.md` per section and build the
  `append_texts` batch with `python3 -m exscriptor.append_texts` (`--help`).
- **Correcting an existing translation**: a reviewed text edit, never
  `append_texts` (it cannot replace).

## Workflow

1. **Glossary.** Extract the work's terminology pairs, the ones a translator
   will collapse (immanence vs passage verbs, for instance; the printed index
   helps). For a new author, run two pilots first: one ordinary section and
   one hard section, complete blocks only.
2. **Partition.** Independent subagents, partitioned by section or block
   range: units ≤80 blocks / ≤50k characters, file writes ≤10KB per task.
   Keep an `inflight.json` of assigned units; never give one unit to two
   workers, and give every wave a unique tag.
   When a prior draft translation of the same text exists (stale against a
   rebuilt Latin), prefer a fix-pass over from-scratch translation: workers
   see both the Latin and the draft and edit the draft in place, filing
   doubts as usual. A few edited blocks cost far fewer output tokens than a
   full rewrite. Gate a fix-pass identically (block counts, no markers,
   footnote parity); a block-count mismatch means the draft's structure is
   stale and that block is translated fresh.
3. **Brief.** Repeat the contract verbatim in every brief; children know
   nothing else.
   - Count the Latin blocks first; translate one-for-one; verify that the
     target count is identical before writing.
   - Keep `^[…]` at the exact position, translating its prose and keeping
     its leading number and citation abbreviations. Carry
     `[[display|target]]` links verbatim, translating only the display text.
   - Preserve Greek. Translate argument markers (*Prob.*→*Proof*,
     *Resp.*→*I answer*, *nego*→*I deny*), keeping the source's italics.
   - Keep the glossary terms. Never add or remove breaks, headings, bold,
     italics, lists or numbering. Supply grammatically needed words without
     brackets.
   - Write to disk in one go, then report the source and target counts.
4. **Second reader of the Latin.** The translator reads every word and
   ledgers what looks wrong, without editing it: a garbled word, missing
   text, a printer's error, impossible grammar, a dittography, a spelling
   needing normalization (context-dependent u/v, vowel-V, ligatures, `&`),
   or a passage hard to translate. Translate for sense, without brackets.
   Each worker writes a ledger fragment in the `exscriptor.ledger` schema:
   - `unit`, `block`, the `quoted` text, `issue`, and a `proposed` reading;
   - `category`: misreading / omission / addition / transposition for the
     Latin, normalization for spelling, translation for a hard passage;
   - `raised_by`.

   The orchestrator merges the fragments into `<work>/ledger.jsonl`
   after checking that nothing was lost.
5. **Deterministic gates** on every landed file: block count, no empty
   block, no embedded block break, footnote and link parity, completeness,
   exact section coverage. Re-read every landed file and recompute every
   count: a "completed" report is not evidence. `python3 -m
   exscriptor.status <work>` checks block, footnote and link parity of
   every landed file against its Latin; run it after each wave and fix a
   unit the moment it differs, before drift spreads. Re-dispatch truncated units
   with full overwrite.
6. **Fidelity check.** After each wave, read a few blocks against their
   Latin for omission, paraphrase and lost emphasis. If a large batch loses
   fidelity, halve the batch size: unit-for-unit discipline degrades before
   the prose does.
6b. **Revision, always.** A second translator (a different agent from the
   drafter, as strong as the strongest available) revises every block
   against its Latin, per `references/revise-brief.md`, and logs each change
   in `translation-<lang>/revision-log.md`. Drafts that read well still
   misparse hard Latin: on Cajetan qq. L–LIV the revision changed 298 places
   in 19 articles, some of them reversing the sense; the live qq. I–XLIX,
   never revised, show a slip every few blocks. A cheap draft is fine; an
   unrevised draft is not finished.
7. **Adjudication**: `transcription-qa`, QA-2. Every Latin row is
   decided on the print. The English side of the same rows is checked. Every
   block whose Latin changed is re-translated, so one reading runs through
   the whole text.
   After adjudication, collect all confirmed Latin corrections for the same
   work into one edit manifest and one approval batch. Keep each correction
   separately traceable to its section, block, scan page, and QA verdict; a
   grouped batch must still make every edit independently reviewable. Do not
   submit confirmed Latin fixes one by one. Once approved, rebuild the affected
   source text, revise the dependent translation blocks, and run translation
   QA and paragraph alignment before staging the translation.
8. **Titles.** Translate the fixed Latin section titles, one per section,
   slug-aligned and checked by count (An→Whether, Utrum→Whether, Quid
   sit→What … is, De→On; the print's key terms keep their capitals). They
   ship as `title_translations` in the batch. **Case follows the print**:
   a sentence-case Latin heading (`De simplicitate Dei`) gets sentence case
   in English (`On the simplicity of God`), never Title Case; an all-capitals
   heading stays in capitals. Provide a title for every included section and
   parent, read against the source title for meaning. For `append_texts`, include only the language
   being added in the manifest's title map; existing localized titles are
   already present in production and the API rejects them when resubmitted.
9. **Alignment**, required for every batch that carries a translation:

   ```bash
   python3 -m exscriptor.alignment screen <manifest> --target en --report <work>/alignment/<stem>.json [--source live.json]
   python3 -m exscriptor.alignment show <manifest> --report <work>/alignment/<stem>.json
   python3 -m exscriptor.alignment dispose <manifest> --report <work>/alignment/<stem>.json --dispositions <read>.json
   ```

   Read every flagged pair (ratio outliers, each section's last pair, a
   seeded sample) and record a disposition in the report. Method:
   `paragraph-alignment`.
10. **Preflight and stage** through `corpus-import`. The submit step
    refuses without a passing `python3 -m exscriptor.preflight <manifest>`.

## Footnotes and citations

The house style's "Rules that replace judgement" apply to translations too:
numerals in citations in capitals, a block ending on a note keeps the
Latin's stop, editors' conjectures as the target-language word with « ? »,
a term under discussion in italics ("the term *X*").

**Quotation marks are the target language's** (house style rule 9). English:
“…” with ‘…’ inside, never the Latin's « »; Spanish keeps « ». Write them so;
`python3 -m exscriptor.house quotes '<work>/translation-en/*.md'` converts
a file that still carries « », and preflight's `quotes` gate refuses « » in
English.

- Every target `^[…]` matches a source footnote at the same anchor. Count
  `^[` starts: inner brackets break naive regexes. An extra target footnote
  exists only as `Editor's note`.
- Inline notes never nest. The source's « [Editor's note: …] » at the end of
  a footnote is translated in place, as the same bracketed tail; an editor's
  note the translator adds about a footnote goes there too, never as `^[…]`
  inside it. Preflight refuses a nested, doubled or unclosed note.
- Only page-bottom notes are footnotes. A citation or numbered point hoisted
  into `^[…]` is a transcription defect: fix the Latin first, never mirror it
  into the translation.
- **Links are made in the Latin first; translations inherit them.** Carry
  `[[display|canonical-key:locus]]` verbatim, translating only the display
  text left of `|`; never translate, normalize or guess the target. If the
  Latin carries no links, link its citations of live works before
  translating (`corpus-import`, "Checking a manifest"), so the batch does
  not ship unlinked.

## Subagent budget

Start with 3 subagents; drop to 2, then 1 with backoff when one dies or
throttles; raise again only after a batch survives (up to about 6, with
larger batches), and only while the gates and the fidelity check pass. A worker
can take ~90k Latin characters / ~140 blocks, bundling small units so no slot
is spent on a 35-character unit. A large run is not a reason to switch to an
API: it takes more waves.

If the subagents fail entirely, the parent translates directly under the
same contract: count first, full prose per block, verify before writing,
and the Latin never edited.

## Pitfalls

- Re-planning repacks the briefs: overwriting `briefs/batchNN.md` while a
  child is reading it silently changes that child's assignment. Use unique
  wave tags, and refuse to overwrite a live brief.
- Children are leaf agents: everything they need goes in the brief.
- Skip-if-exists: a worker that finds its output file reports the existing
  counts and never overwrites.
- Join part files with a blank-line guard, never bare concatenation;
  rejoin a mid-block resplit with a single `\n` so the block counts survive.
- A brief's block count may disagree with the Latin file. Translate the file
  as it stands; never invent a block. Ledger the discrepancy as a structure
  row.
- More: `references/revise-brief.md`, `references/rubric.md`, `references/manual-translation-pitfalls.md`.
