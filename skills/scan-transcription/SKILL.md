---
name: scan-transcription
description: Transcribe page scans into diplomatic page files, then derive the normalized edition with exscriptor (diplomatic → expand → assemble). Use when pages must be read, a partial reading continued, or a reader chosen.
---

# Scan transcription

The diplomatic page files (`<work>/diplomatic/pg-NNN.md`, one per printed
page) are the work's source of truth. The edition, the assembled sections,
the translation and the manifest are rebuilt from them, so a fix is an edit
to a page file followed by a rebuild.

This skill reads pages. `transcription-qa` checks them afterwards, run by a
different agent.

## Workflow

Start when `reconnaissance` is finished: `SCOUT.md`, `work.json`,
`structure.json`, `FORMATTING.md`, the mark inventory (a print with marks)
and `TRANSCRIBE_INSTRUCTIONS.md` exist, and `work.json` names the reader.

1. **Scope.** For a live work, read where its text stops
   (`../reference/api.md`, the outline) and find the next section in
   `structure.json`. Read the page after the boundary: a division ends at a
   sentence, not at a page. Done when the first and last page of the range
   are named and the range joins the approved text seamlessly.
2. **Renders.** `pdftoppm -jpeg -r 200` with zero-padded names, so
   `pg-010` sorts after `pg-009`. Split a two-page spread at its detected
   gutter (it drifts between ~45% and ~55% of the width). ~1200×1650 px per
   page is enough. Keep the renders: they are `page_files.scans` and, later,
   the facsimile. Done when `ls pages/` lists exactly the range, checked
   before any run, above all a paid one.
3. **Read.** Dispatch the reader (below) with the brief, one page per read
   request. Every reader writes each page file the moment the page is
   finished and skips a page file that already exists, so a dead batch is
   re-dispatched, not rebuilt; the brief states both halves of that rule.
   Each subagent also writes `tmp/reads/<batch>.md`: the first and last ~8
   words of each page, and its flags.

   **Check each wave before dispatching the next:**
   - every page within a word-count band of its OCR layer (a short page
     has lost text: re-render and re-read it);
   - no loops (an 8-gram repeated far above the page's own count);
   - the wave assembled into scratch:

     ```bash
     python3 -m exscriptor.assemble --pages '<work>/diplomatic/pg-{n:03d}.md' \
         --range <first>-<last read> --structure <work>/structure.json --out-dir <work>/tmp/wave
     ```

     It lists markup defects (unbalanced italics, a reference mark written
     twice: `*[*1]`), seams (a paragraph cut at a page break) and note
     continuations. Collation ignores markup, so these surface nowhere else
     before preflight.

   A slip one reader makes twice goes into the brief for the next wave.
   Done when every page of the range has a page file and the scratch
   assembly reports only `⟦…?⟧` residue, the reader's own flags, which QA
   settles.
4. **Expand.** Derive the edition:

   ```bash
   python3 -m exscriptor.expand run --pages '<work>/diplomatic/*.md' \
       --out-dir <work>/edition --record <work>/expansions.tsv \
       --lexicon <lexicon>.json --decisions <work>/decisions.tsv \
       --allow-file <work>/orthography-allow.txt \
       [--table <work>/abbreviations.tsv] [--keep-uv] [--paragraphs <work>/paragraphs.json]
   ```

   - `--table` when `work.json` `page_files.print` is `old` (the print has
     abbreviation marks).
   - `--keep-uv` when `work.json` says `"uv": "as-printed"`: the print's u/v
     already follows the house rule, as most 19th–20th-century prints do.
     Otherwise the lexicon decides u/v per word, and an exception is a row
     in `decisions.tsv`.
   - The lexicon: `python3 -m exscriptor.lexicon build '<texts>' --out
     <lexicon>.json` over adjudicated Latin, best the published corpus
     (`../reference/api.md`), always **without the work being read**, whose
     misreads would otherwise become vocabulary.

   What the run cannot decide lands in `pending.tsv`, long-s doubts in
   `long-s.tsv`. The editor pass answers both in `decisions.tsv`
   (`transcription-qa`, "The editor pass"), and `expand` runs again. A
   row's token matches case-sensitively: `Sacrif` needs its own row beside
   `sacrif`. The order the run applies its rules in, and why:
   `../reference/house-style.md`, "Normalization". Done when both files are
   empty; `python3 -m exscriptor.status <work>` refuses to go further
   before.
5. **QA-1**: `transcription-qa`, by a different agent. Every fix to a page
   file is followed by `expand` again.
6. **Assemble** the edition with the shared assembler:

   ```bash
   python3 -m exscriptor.assemble --pages '<work>/edition/pg-{n:03d}.md' \
       --range 17-85 --structure <work>/structure.json --out-dir <work>/assembled \
       [--drop-layer THOMAS] [--seam-duplets]
   ```

   It joins seams, fuses continued notes, numbers notes continuously, splits
   by the section tree, and refuses on any seam, note-continuation,
   structure or residue defect; the fix for each is in the page file, then
   `expand`. Done when it exits 0.
7. Hand over to `translation`, or to `corpus-import` for a Latin-only batch.

## The reader

`work.json` (`"reader"`) names it; reconnaissance chose it on two or three
hand-adjudicated sample pages. The run keeps that reader to the end; a
stall is fixed with fewer agents, backoff and skip-if-exists.

- **Vision subagents in your own harness**, the default: batches of ~8
  pages per subagent against `TRANSCRIBE_INSTRUCTIONS.md`. Keep each vision
  prompt to one short question: on one scouting run every failure was a
  timeout that tracked prompt *length*, not image size (seven words
  answered in 4 s where twelve words, the same minute, timed out).
- **A page-reading model you run yourself** (a fine-tuned small vision
  model, such as the house's public lector model on Hugging Face, `lector-4b-v1`): its errors are fluent rather than garbled (low-resolution
  misreadings, long s written as s), and it can skip a passage at a heading
  or a column foot. Collate its draft against the scan's text layer for
  omissions, then a text-only cleanup corrects the draft *to the print*,
  normalizing nothing. A page it flags as looped or truncated goes to
  another reader.
- **A paid batch vision API**, when the person paying has authorized that
  route for this job after reconnaissance quoted pages × price
  (`../README.md`, "Money"). A key in the environment is not
  authorization, and neither is a funded balance or the size of the run.
  `exscriptor.gemini_batch_run` submits only with an explicit `--model`. If credits run out mid-run, stop and report.
- **The OCR layer** is always the independent witness (QA's coverage
  screen). On a modern print with a clean layer it can be the reader, with
  the same text-only cleanup (`references/lessons.md`, "The OCR-only
  workflow").

The two readers of a page are independent: different vendors or
architectures. Two readers of one family, or a run guided by its own
earlier draft, share their errors.

Before dispatching a vision reader, run `pdffonts`. Real font names (not a
single synthetic `GlyphLessFont`) mean italics and bold are exact data in
the PDF: read them from PyMuPDF span fonts. A layer can be exact on
typography and corrupt on the words.

## Why witnesses, and why two layers

The dangerous failures are fluent, and structure beats instruction:
`transcription-qa`, "Why it works this way". For reading in particular:

- **A five-page benchmark does not predict sixty pages.** It measures
  per-word accuracy; the failures above are per-page events. Benchmark to
  choose a reader, then screen every page.
- **Readers copy; `expand` normalizes.** Asked to transcribe and normalize
  at once, a reader makes more mistakes (stating "j → i" in the prompt
  measurably lowered accuracy), and a normalized reading is unverifiable:
  with the print's record gone, nothing can tell a house rule from a
  misreading. So normalization lives in `expand` and `decisions.tsv` only.

## Formatting fidelity

Italics mark lemmas, terms and titles; bold marks headings. A transcription
with the right words and the wrong devices is unfinished.

1. The work's `FORMATTING.md` defines the mapping; the reader applies it.
2. The page's notes record the device decisions taken on that page.
3. QA audits formatting per occurrence before staging. An edition can
   alternate a device from one occurrence to the next, so neither a
   neighbouring page nor a count settles it (`references/lessons.md`,
   "Worked method").

## Text the edition prints but you do not publish

A commentary edition usually prints the commented text too; publish only
the commentator (with a `commented_locus`). The failure republishes someone
else's text under this author's name, and no spelling screen flags it.
Exclude **structurally**: find the edition's layout invariant (for
instance, everything above the anchor heading is the commented text),
transcribe that zone inside a layer (`diplomatic-transcription` §1), and
let `assemble --drop-layer` drop it and report what it removed. A marker
the reader emits is no evidence: one page emitted the omission marker and
then transcribed the excluded text anyway. A leading span one reading has
and the other lacks is the signature. The edition's own words inside a
dropped zone (its verdict line on an article) are kept with `--keep REGEX`.

## Subagent budget

Start with 3 subagents; when one dies or throttles, drop to 2, then 1 with
backoff, and raise again only after a batch survives. Within a usage
window, dispatch the next wave at about half the last successful width.
Parallel agents get disjoint page ranges. A subagent's background jobs die
with its session, so bulk mechanical work (rendering, OCR) runs in the
parent.

## References

- `references/lessons.md`: the OCR-only workflow, the formatting-audit
  worked method, provider lessons, known catches, delegation lessons,
  scaling a pilot to a whole work. Load the section you need.
- The work's README: read it before starting or resuming; record what you
  learn there.
