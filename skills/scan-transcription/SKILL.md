---
name: scan-transcription
description: Read the page scans of a public-domain edition into diplomatic page files, after reconnaissance, and derive the normalized edition from them with exscriptor. One pipeline for every print, diplomatic → expand → assemble; only the reader varies (vision subagents, a page-reading model, a paid batch API when authorized, or the OCR layer with a text-only cleanup). Use when a work or section must be digitized from scans, a partial transcription continued, or a reader chosen. QA is transcription-qa; staging is corpus-import.
---

# Scan transcription

Turn the page scans of a public-domain edition into page files that are the
durable source of truth for the work: one Markdown file per printed page,
`<work>/diplomatic/pg-NNN.md`. Everything downstream (the edition layer,
the assembled sections, the translation, the manifest) is rebuilt from
them, so fix content by editing them, never by re-transcribing a page or
by editing a derived file.

This skill reads pages. Checking them is `transcription-qa`, which always
runs after it, by a different agent.

## Reconnaissance comes first

No body page is read before `reconnaissance` has written `SCOUT.md`,
`work.json`, `structure.json`, `FORMATTING.md`, the mark inventory (a print
with marks) and `TRANSCRIBE_INSTRUCTIONS.md`. It also benchmarks the
candidate readers on two or three sample pages adjudicated by hand.

## What this workflow defends against

Four things, each learned by shipping the mistake:

1. **The dangerous failures are the fluent ones.** A misread letter is
   cheap and obvious. What reaches production reads perfectly: an English
   summary where the reader declined the page, one junk token substituted
   for many real words, a duplicated clause, a column silently dropped, the
   commented author's text left in the commentator's. You cannot find these
   by reading the output, only by comparing it with something independent.
2. **Quality comes from independent witnesses and mechanical comparison,
   never from proofreading.** A second reader, the scan's own OCR layer and
   the page image at high resolution have different blind spots; any one
   alone has shipped an error past the other two.
3. **Structure beats instruction.** Whatever the layout guarantees (which
   zone a heading opens, where the commented text ends, that a ligature is
   two letters) is enforced in code over the text, never left to a model's
   compliance.
4. **A five-page benchmark does not predict sixty-page behaviour.** It
   measures per-word accuracy; the failures above are per-page events that
   did not occur in the sample. Benchmark to choose a reader, then screen
   every page anyway.

## One pipeline: diplomatic, then normalized

Whatever the print and whoever reads it, the work goes through two layers
that never mix:

1. **The diplomatic reading** (`diplomatic/`): what the page prints, letter
   for letter, under the page-file contract (`diplomatic-transcription`).
   Every mark as the exact Unicode character `ABBREVIATIONS.md` names, `ſ`
   as `ſ`, u/v, i/j, `&`, ligatures, accents, capitals and punctuation as
   printed; nothing expanded, corrected or normalized.
2. **The edition** (`edition/`), derived by code and never edited by hand:

   ```bash
   python3 -m exscriptor.expand run --pages '<work>/diplomatic/*.md' \
       --out-dir <work>/edition --record <work>/expansions.tsv \
       --lexicon <lexicon>.json --decisions <work>/decisions.tsv \
       --allow-file <work>/orthography-allow.txt \
       [--table <work>/abbreviations.tsv] [--keep-uv] [--paragraphs <work>/paragraphs.json]
   ```

   - `--table` when the print has abbreviation marks (`work.json`
     `page_files.print` is `old`).
   - `--keep-uv` when `work.json` says `"uv": "as-printed"`: the print's
     u/v already follows the house rule, as most 19th–20th-century prints
     do. Otherwise u/v is decided per word by the lexicon, and its
     exceptions are rows in `decisions.tsv`, never a reader's judgement.
   - The lexicon: `python3 -m exscriptor.lexicon build '<texts>' --out
     <lexicon>.json` over adjudicated Latin (the published corpus is the
     best source: `../reference/api.md`), **excluding the work under
     examination**, or its misreads become vocabulary.

   The run applies, in order: the editor's decisions, the work's mark
   table, the safe built-in rules (`&`, ligatures, consonantal j, print
   accents, long s), the lexicon's nasal bars and u/v, the corpus spelling
   list (shipped with exscriptor, each pair at the work's majority; the run
   prints the list's hash and the pairs), the stop spacing, and last the
   punctuation pass's `punctuation.tsv` when it exists. A word split across
   a page break is decided on the joined word. What stays undecided lands
   in `pending.tsv`, long-s doubts in `long-s.tsv`; the editor pass
   answers both in `decisions.tsv` (`transcription-qa`, "The editor pass")
   and the run repeats until both are empty. `python3 -m exscriptor.status
   <work>` refuses to go further before. A row's token matches
   case-sensitively: a row for `sacrif` does not cover `Sacrif`.

**Why two layers.** A reader asked to transcribe and normalize in one pass
makes more mistakes (stating "j → i" in the prompt measurably lowered
accuracy), and a normalized reading is unverifiable: with the print's
record gone, no later stage can tell a house rule from a reader's error.
The diplomatic layer is also clean training data for a page reader. So
normalization lives only in `expand` and `decisions.tsv`, never in a
reader's prompt and never in a hand edit. Order and rationale:
`../reference/house-style.md`, "Normalization".

## The reader: what draws the diplomatic draft

The reader is the only thing that varies between jobs. Reconnaissance
benchmarks candidates and records the choice in `work.json` (`"reader"`).
Never switch reader mid-run; a stall is never a reason to pivot. Fix it with
fewer agents, backoff and skip-if-exists.

- **Vision subagents in your own harness** (no extra spend; the default):
  batches of ~8 pages per subagent against the shared
  `TRANSCRIBE_INSTRUCTIONS.md`. Keep each vision prompt short and
  single-purpose: on one scouting run every failure was a timeout that
  tracked prompt *length*, not image size (a seven-word question answered
  in 4 s where a twelve-word one in the same minute timed out). One question
  per call; never a whole-page survey in one request.
- **A page-reading model you run yourself** (a fine-tuned small vision
  model, for instance): its errors are fluent rather than garbled
  (low-resolution misreadings, long s written as s), and it can skip a
  passage at a heading or a column foot. Collate its draft against the
  scan's text layer to catch omissions, then run a text-only cleanup that
  corrects the draft *to the print* (it never normalizes). A page it flags
  as looped or truncated is read again by another reader.
- **A paid batch vision API**: only when the person paying has authorized
  that route for this job, after reconnaissance quoted pages × price. A key
  in the environment is not authorization, and neither is a funded balance
  or the size of the run. `exscriptor.gemini_batch_run` refuses to submit
  without an explicit `--model`; no script here has a paid default. Read
  credentials from one environment variable; never print a value. If
  credits run out mid-run, stop and report; never re-route on your own.
- **The OCR layer** is always the independent witness (QA's coverage
  screen). On a modern print with a clean layer it can be the reader, with
  the same text-only cleanup (`references/lessons.md`, "The OCR-only
  workflow").

The two readers of a page must be independent: different vendors or
architectures. Paired readers from one family, or a draft-guided run
checked against its own draft, share their errors.

**Before dispatching a vision reader, check whether the text layer already
carries the typography.** If `pdffonts` lists real font names (not a single
synthetic `GlyphLessFont`), italics and bold are exact data in the PDF: read
them from PyMuPDF span fonts. OCR text and typography are separate
problems; the layer can be exact on devices and corrupt on the words.

Every reader's output is held to the same contract and the same QA.

## Boundary

- Public-domain (or clearly open-licensed) editions only; record the source
  URL, edition and rights basis in `work.json`.
- **TOC first**: `structure.json` exists before body pages are read.
- **Money**: no paid route runs without the payer's authorization for this
  job. The free reader is the default, never the fallback.
- **Staged means finished**: nothing leaves this skill with an unsettled
  reading hidden in it. Uncertain readings are flagged `⟦…?⟧` on the page,
  turned into ledger rows and settled in QA; none survives into a manifest.
- **A digital text of the same work is a witness, never a source.** The
  print is the arbiter; a suspect reading is never passed on silently.
- **Get the structure right before staging**: correcting a live work costs
  about ten times what getting it right up front does.

## Workflow

1. **Scope.** For a live work, read where its text stops (`../reference/api.md`,
   the outline) and find the next section in `structure.json`. Check the
   page AFTER the boundary: a division ends at a sentence, not at a page.
   The new section must be seamless with the approved text.
2. **Prepare scans.** `pdftoppm -jpeg -r 200`, zero-padded names (or
   lexicographic order breaks past page 9). Split two-page spreads at the
   detected gutter (it drifts between ~45% and ~55%; never cut at a fixed
   midpoint). One page per read request; ~1200×1650 px is enough. Keep the
   renders: they are `page_files.scans` and the facsimile pages later.
   Glob-check the page list against `ls` before any run, above all a paid
   one.
3. **Brief.** One `TRANSCRIBE_INSTRUCTIONS.md` per job (reconnaissance §8):
   the page-file contract quoted verbatim, the work's `FORMATTING.md`, the
   generated mark list, and one or two finished *diplomatic* page files as
   the model. Never published (normalized) text: it teaches readers to
   normalize. It states every rule in "Rules every brief must state" below.
4. **Read.** Every reader writes each page file the moment that page is
   finished, and skips any page file that already exists. State both halves
   of that rule in the brief and re-dispatch rather than rebuild: a dead
   batch otherwise loses everything. Each subagent also writes a short
   report file (`tmp/reads/<batch>.md`): the first and last ~8 words of each
   page and its flags. Results live on disk; harvest files, not replies.

   Hold every page to a word-count band against the OCR layer (a page well
   under it has lost text: re-render and re-read it, never patch it by
   hand), and sweep for loops (repeated 8-grams far above the page's own
   count).

   **Check each wave as it lands**, before the next: assemble the pages
   read so far into scratch.

   ```bash
   python3 -m exscriptor.assemble --pages '<work>/diplomatic/pg-{n:03d}.md' \
       --range <first>-<last read> --structure <work>/structure.json --out-dir <work>/tmp/wave
   ```

   It lists every markup defect (unbalanced italics, stray asterisks: a
   reference mark written twice, `*[*1]`), seam (a paragraph cut at a page
   break) and note continuation. Residue refusals for `⟦…?⟧` are the reader
   flags, expected until QA; everything else is fixed now. Collation ignores
   markup, so these surface nowhere else until preflight, by when every
   later stage has inherited them. A pattern in one reader's pages (the
   same slip twice) goes back into the brief for the next wave.
5. **Expand** (command above).
6. **QA**: `transcription-qa` (QA-1, which opens with `ledger flags` and
   runs the editor pass), by a different agent. Re-run `expand` after every
   fix to a diplomatic page.
7. **Assemble** from the edition, with the shared assembler; never a
   per-work copy:

   ```bash
   python3 -m exscriptor.assemble --pages '<work>/edition/pg-{n:03d}.md' \
       --range 17-85 --structure <work>/structure.json --out-dir <work>/assembled \
       [--drop-layer THOMAS] [--seam-duplets]
   ```

   It joins seams, fuses continued notes, numbers notes continuously and
   splits by the section tree, and refuses on any seam, note-continuation,
   structure or residue defect. Fix the diplomatic page, re-run `expand`,
   never patch the output.
8. Hand over to `translation` and `corpus-import`.

## Page files

The contract is `diplomatic-transcription`; read it before writing a brief.
In short:
- everything printed is on the page, as printed;
- notes are `^[…]` at their anchors, marginal ones `^[⟦M⟧ …]`;
- continued notes use `⟦NOTE-CONTINUES⟧` and `⟦CONTINUED-NOTE⟧`;
- one trailing `<!-- notes: … -->` comment;
- layers between `<<<NAME>>>` and `<<<END NAME>>>`;
- uncertain readings as `⟦word?⟧`, an unknown mark as `⟦mark: description⟧`.

**Text and furniture.** Running heads, folios, signatures, catchwords,
stamps and scanner edges are never text. A page or column break never ends
a paragraph: a block starts only where the print starts one. A word
hyphenated at a prose line end is joined; a hyphen inside a compound
stays. Two columns are read left column in full, then right.

## Rules every brief must state

Each was a real, measured failure; readers do not infer them.

a. **Never normalize, never correct.** Copy spelling, u/v, i/j, `&`,
   ligatures, accents, capitalization (a lowercased proper name included),
   punctuation and every mark exactly as printed, and expand nothing. "Copy
   what is there" beats both a plain and an emphatic normalization
   instruction, and an anti-classicizing instruction overshoots into
   invented archaic forms.
b. **At a hyphen seam, the next page begins with ONLY the remaining
   fragment.** Re-emitting the whole word makes a dittography the
   assembler cannot tell from text.
c. **Every printed marginal note or label is a `^[⟦M⟧ …]` note**, never its
   own block and never dropped.
d. **Exact Unicode for every marker, flag and mark**, printed in the brief.
   A brief that writes `<<ST OMITTED>>` or `[[?]]` in ASCII teaches readers
   to emit those bytes, and lookalike markers fail silently downstream.
e. **Flag rather than guess**: `⟦word?⟧` on a genuinely hard reading makes
   the page cheap to adjudicate.
f. **State the provenance** (author, death date, edition, "produce the
   text, never a summary"): it measurably reduces refusals, and a refusal
   that comes back as a fluent summary is the worst failure there is.

## Formatting fidelity

A transcription that gets the words right and the formatting wrong is not
finished: italics mark lemmas, terms and titles; bold marks headings. Never
add a device the print does not have; never drop one it does.

1. The work's `FORMATTING.md` defines the mapping; the reader applies it.
2. The page's notes record the device decisions taken on that page.
3. QA audits formatting per occurrence before staging. An edition can
   alternate a device from one occurrence to the next, so neither a
   neighbouring page nor a count settles it (`references/lessons.md`,
   "Worked method").

## Excluding text the edition prints but you do not publish

A commentary edition usually prints the commented text too; publish only
the commentator (with a `commented_locus`). Getting this wrong republishes
someone else's text under this author's name, and no spelling screen flags
it. **Exclude structurally:** find the edition's layout invariant (for
instance, everything above the anchor heading is the commented text),
transcribe it inside a layer (contract §1), and let the assembler drop it,
reporting what it removed. **A marker the reader emits is not evidence:**
one page emitted the omission marker *and then transcribed the excluded
text anyway*. A leading span one reading has and the other lacks is the
signature of this failure. The edition's own words caught inside a dropped
zone (its verdict line on an article) are hoisted with `--keep REGEX`.

## Subagent budget

Start with 3 subagents; if one dies or throttles, drop to 2, then 1 with
backoff; raise again only after a batch survives. Subagents share one
session budget: within a usage window, treat the last successful wave width
as the estimate and dispatch the next at about half of it. Give parallel
agents disjoint page ranges, never shared files. A subagent's background
jobs die with its session: bulk mechanical work (rendering, OCR) runs in
the parent.

## Per-work context

Read the work's README before starting or resuming; record discoveries
there. Work-specific detail stays out of this skill.

## References

- `references/lessons.md`: the OCR-only workflow, the formatting-audit
  worked method, provider lessons, pitfalls, pipeline rules, known catches,
  delegation lessons, scaling a pilot to a whole work. Load the section you need.
- `../reference/house-style.md`: the edition standard, the normalization
  order, and the pre-staging checklist.
- `transcription-qa`: screens, the editor pass, adjudication, the ledger.
