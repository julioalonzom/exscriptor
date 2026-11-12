---
name: translation
description: Translate scholastic Latin into a faithful, paragraph-aligned text (English by default), from a verified local assembly or from the live text, with the translator as the Latin's second reader. Use when a work or a live work's sections need a translation, or an existing draft must be brought up to rebuilt Latin.
---

# Translation

Produce the best scholarly translation you can: precise, faithful to the
argument and to the register of the source, with exactly one target block
for each blank-line-delimited Latin block, and full prose in every block. A
summary, a "concise rendering" or a `[Block N: …]` placeholder is a failed
block, whatever the size of the run. Nobody retranslates after you: the
editor who approves does not proofread (`../README.md`, "Staged means
finished").

## Before you start

- Read the work's README and `corpus-import`.
- **The Latin is fixed while you translate.** A doubt about it goes to the
  ledger (step 4). If the live Latin diverges from the print, its correction
  goes first: a magister reports it to the Custos (`corpus-import`, "The
  modes"), `transcription-qa` adjudicates the reading, and the translation
  follows the corrected text.
- **Existing translations are comparators**, not ground truth. A
  translation's rights are verified on their own, apart from the source
  edition's.
- **The translators are subagents on your own harness's model.** An API
  route runs only when the person paying authorized it for this job, and
  names its model explicitly.

## Which Latin

- **From scratch** (nothing live): the verified local assembly in
  `<work>/assembled/`. Latin and translation stage together in one `create`.
- **Translate-only** (the Latin is live): snapshot it,
  `python3 -m exscriptor.snapshot <slug> --out <work>/live.json`, because
  imports may have re-split blocks. Translate from the snapshot, one
  `<section_id>.md` per section, and take a fresh snapshot right before
  building; re-translate any section whose Latin changed. The batch is
  `python3 -m exscriptor.append_texts` (`--help`).
- **Correcting a live translation** is an `edit` (Custos): `append_texts`
  adds a language and cannot replace one.

## Workflow

1. **Glossary.** Extract the work's terminology pairs, the ones a translator
   will collapse (immanence vs passage verbs, for instance; the printed
   index helps). For a new author, pilot one ordinary section and one hard
   section first, complete blocks only. Done when the glossary is a file the
   briefs quote.

2. **Partition** into units for independent subagents: ≤80 blocks / ≤50k
   characters per unit, file writes ≤10KB per task. `inflight.json` lists
   assigned units, each to one worker, and every wave has a unique tag.
   Where a stale draft of the same text exists, run a fix-pass instead:
   workers see the Latin and the draft and edit the draft in place, gated
   identically; a block whose count no longer matches is translated fresh.
   Done when every unit is assigned once.

3. **Brief.** Children know only the brief, so it carries the whole
   contract, verbatim:
   - count the Latin blocks first, translate one for one, and check the
     counts match before writing;
   - `^[…]` stays at its exact position, its prose translated, its leading
     number and citation abbreviations kept; `[[display|target]]` is carried
     verbatim with only the display text translated;
   - Greek stays; argument markers are translated (*Prob.*→*Proof*,
     *Resp.*→*I answer*, *nego*→*I deny*) with the source's italics;
   - the glossary's terms; the source's breaks, headings, bold, italics,
     lists and numbering exactly; grammatically needed words supplied
     without brackets;
   - skip a unit whose output file exists, reporting its counts; write the
     file in one go, then report the source and target counts.

4. **Second reader of the Latin.** The translator reads every word and
   ledgers what looks wrong, leaving the Latin as it is: a garbled word,
   missing text, a printer's error, impossible grammar, a dittography, a
   spelling needing normalization, a passage hard to translate. Each worker
   writes a ledger fragment in the `exscriptor.ledger` schema (`unit`,
   `block`, `quoted`, `issue`, `proposed`, `raised_by`, and `category`:
   misreading / omission / addition / transposition for the Latin,
   normalization for spelling, translation for a hard passage). Done when
   the orchestrator has merged every fragment into `<work>/ledger.jsonl`
   and checked that the row counts add up.

5. **Gates on every landed file**, after each wave:
   `python3 -m exscriptor.status <work>` checks block, footnote and link
   parity of every translation against its Latin. Also check: no empty
   block, no embedded block break, exact section coverage. Re-read the
   files and recompute the counts yourself: a "completed" report is not
   evidence. Re-dispatch a truncated unit with full overwrite. Done when
   every landed unit passes, before the next wave starts.

6. **Fidelity check.** After each wave, read a few blocks against their
   Latin for omission, paraphrase and lost emphasis. A wave that loses
   fidelity halves the next wave's units: unit-for-unit discipline degrades
   before the prose does. Done when the sample reads faithfully.

7. **Revision, always.** A second translator, a different agent from the
   drafter and as strong as the strongest available, revises every block
   against its Latin per `references/revise-brief.md`, logging each change
   in `translation-<lang>/revision-log.md`. Drafts that read well still
   misparse hard Latin: on one commentary the revision changed 298 places
   in 19 articles, some reversing the sense. Done when every block has been
   revised.

8. **Adjudication**: `transcription-qa`, QA-2. Done when every row is
   closed and every block whose Latin changed is re-translated.

9. **Titles.** Translate each section's fixed Latin title, slug-aligned and
   checked by count (An→Whether, Utrum→Whether, Quid sit→What … is,
   De→On; the print's key terms keep their capitals). **Case follows the
   print:** `De simplicitate Dei` → `On the simplicity of God`, in sentence
   case; an all-capitals heading stays in capitals. `append_texts` carries
   only the language being added. Done when every included section and
   parent has a title.

10. **Alignment**, for every batch with a translation:

    ```bash
    python3 -m exscriptor.alignment screen <manifest> --target en --report <work>/alignment/<stem>.json [--source live.json]
    python3 -m exscriptor.alignment show <manifest> --report <work>/alignment/<stem>.json
    python3 -m exscriptor.alignment dispose <manifest> --report <work>/alignment/<stem>.json --dispositions <read>.json
    ```

    Method: `paragraph-alignment`. Done when every flagged pair has a
    disposition.

11. **Stage** through `corpus-import`.

## Footnotes, citations, quotation marks

The house style's "Rules that replace judgement"
(`../reference/house-style.md`) hold for translations too: capital numerals
in citations, a block ending on a note keeps the Latin's stop, an editor's
conjecture as the target-language word with « ? », a term under discussion
in italics ("the term *X*").

- **Quotation marks are the target language's** (house style rule 9).
  English: “…” with ‘…’ inside; Spanish keeps « ». `python3 -m
  exscriptor.house quotes '<work>/translation-en/*.md'` converts a file
  that still has « », and preflight refuses « » in English.
- **Every target `^[…]` matches a source footnote at the same anchor**;
  count `^[` starts, since inner brackets break naive patterns. The one
  extra allowed is a note that begins `Editor's note`.
- **Notes never nest.** A source footnote's closing « [Editor's note: …] »
  is translated in place as the same bracketed tail, and an editor's note
  you add about a footnote goes there too.
- **Only page-bottom notes are footnotes.** A citation hoisted into `^[…]`
  is a Latin defect: it goes to the ledger, and the translation follows the
  corrected Latin.
- **Links are made in the Latin first; translations inherit them.** Carry
  `[[display|canonical-key:locus]]` verbatim, translating only the display
  text. Latin without links gets its citations of live works linked before
  translating (`corpus-import`, "Checking a manifest").

## Subagent budget

Start with 3 subagents; drop to 2, then 1 with backoff, when one dies or
throttles; raise again only after a wave survives (up to about 6, with
larger units) and only while the gates and the fidelity check pass. A worker
can take ~90k Latin characters / ~140 blocks; bundle small units so no slot
goes to a 35-character unit. A large run takes more waves, not an API.

If the subagents fail entirely, the parent translates under the same
contract.

## Pitfalls

- **A brief is fixed once a child reads it.** Re-planning that rewrites
  `briefs/batchNN.md` silently changes a running child's assignment: each
  wave writes new files under its own tag.
- **Join part files with a blank-line guard**; rejoin a mid-block resplit
  with a single `\n`, so block counts survive.
- **The Latin file is the count.** Where a brief's count disagrees with the
  Latin file, translate the file as it stands and ledger the discrepancy as
  a structure row.

## References

- `references/revise-brief.md`: the revision pass.
- `references/rubric.md`: what a good translation is.
- `references/manual-translation-pitfalls.md`: when the parent translates.
