---
name: diplomatic-transcription
description: The page-file contract, binding on every reader (vision subagents, a page-reading model, OCR with a cleanup pass) and every later fix. Every work is transcribed diplomatically and normalized afterwards by exscriptor.expand; this is the diplomatic half. A page file records everything printed on one page, as printed, in one notation for footnotes, marginal notes, notes continued across pages, emendations and omitted zones. The same files are clean training data for a page-reading model. Use whenever a page file is written or corrected, and when writing a work's TRANSCRIBE_INSTRUCTIONS.md. Sequencing and readers are scan-transcription.
---

# Diplomatic transcription: the page-file contract

A page file is a witness to one printed page. It serves two readers:
- the pipeline, which builds the edition from it;
- a page-reading model, which can be trained on (scan, page file) pairs.

Both need the same thing: **what the page prints, where it prints it, nothing added and nothing
dropped**. Editorial decisions are made downstream, never silently in the transcribed text:
normalization by `exscriptor.expand` (and the editor's `decisions.tsv`), emendation by the
adjudicator in the marked form of §4.

Every convention here exists because training data broke without it (a data audit of
Schola Thomistica's page files, 2026-10-10):
- one work omitted its marginal notes, and the reader learned to skip margins;
- 202 pages replaced printed text with an omission marker, and the reader learned to stop
  mid-page;
- emended words sat in the body, and the reader learned to "correct" the print;
- marginal notes were written three different ways across three works.

## 1. Completeness: every printed word is on the page file

- **Body, headings, footnotes, marginal notes, and the commented text a commentary prints:** all of
  it. A zone the project won't publish goes in a layer (`<<<NAME>>>` … `<<<END NAME>>>`, dropped at
  assembly with `--drop-layer`). It is not left out.
- **Left out of the body, and recorded in the trailing comment:** running heads, folios,
  signatures, catchwords. These are the only printed things the body omits.
- **When a job truly cannot afford a zone,** replace it with `⟪OMITTED: <what>⟫` at its place.
  The page still works for the website, and a training set can exclude it automatically.
  Never omit silently, and never as a work-wide "house decision" (one work's stripped glosses).

## 2. Footnotes

- **Inline at the anchor:** `^[N. text]`, with N the printed number or mark (`*`, `†`, `a`). Keep the
  note's italics and bold.
- **A note cut off at the page foot** ends with `⟦NOTE-CONTINUES⟧` before its closing bracket.
- **Its continuation on the next page** is the page file's **last block**, opening
  `⟦CONTINUED-NOTE⟧ `. The assembler fuses the two.
- **Recognizing a continuation:** the first lines of the footnote area carry no note number and
  usually start lower-case or mid-word (`tionem licitam…`). They belong to the previous page's last
  note. Check that page: its last note must end `⟦NOTE-CONTINUES⟧`. Never drop these lines, and never
  attach them to the first numbered note of this page.

## 3. Marginal notes

Distinguish **paragraph summaries** from citations and local notes. A marginal summary that describes the whole paragraph, or serves as its title, is published as an italic run-in opener in the same paragraph, after any paragraph numeral:

```
**II.** *Dissolvitur obiectio contra assertionem*.— Sed, ut haec assertio…
```

The page file preserves its printed origin and wording. At the first governing clause, use `^[⟦M⟧⟦R⟧ summary]`, preserving printed italic/roman spans inside the note:

```
**II.** Sed, ut haec assertio…^[⟦M⟧⟦R⟧ Dissolvitur obiectio contra assertionem.]
```

`⟦R⟧` classifies a paragraph rubric; it is metadata, not printed text. It is an additive extension of `diplomatic-v1`. Assembly joins page continuations first, then moves the rubric to the beginning of its owning paragraph and renders it in italics followed by `.— `. This creates neither a separate paragraph nor a section. Do not move it by hand in the page file: its physical anchor remains evidence for the reader and training data.

- **Citations and local glosses** remain ordinary notes: `^[⟦M⟧ *Habetur in bibliotheca SS. Patrum tom. 4.*]`. Do not give them `⟦R⟧`.
- **Classify by scope, not font or brevity.** An argument label such as *Confutatio* beside a later part of a long paragraph remains a local note unless it governs the whole paragraph. Read the whole paragraph, including page continuations. Never invent or rewrite a title.
- **Placement:** use the printed anchor mark when present; otherwise the sentence or clause beside the note's first line, adjusted only to the passage it clearly governs.
- **Exactly one note per printed marginal item**, in print order. Never merge or split items. Multiple whole-paragraph summaries retain their order when published as openers.
- **Marginal section numerals** become `**N.**` at the beginning of the paragraph they number; they are not notes. If the print starts a distinct numbered division mid-line within a physical paragraph, keep its numeral inline at that division’s first governing clause. Neither invent a paragraph break nor move the numeral back to a different argument merely to put it at a paragraph opening.
- **Record `margins: N`** in the trailing comment. Every marginal item, including a rubric, has one `⟦M⟧` tag. `⟦R⟧` does not change that count. QA and training preserve both classifications and the printed typography.
- **An editorial note about a rubric** travels with it only when explicitly marked immediately after it: `^[⟦M⟧⟦R⟧ Summary.]^[⟦R-NOTE⟧ Editor's note: …]`. Preserve its exact wording. Ordinary adjacent editorial notes about the body keep their anchors and have no `⟦R-NOTE⟧`. Nested notes inside a rubric are refused; settle their exact attachment before rebuilding.
- **Retroactive corrections:** classify existing marginalia from the complete paragraph and scan; fix the source page files and rebuild forward. Move the corresponding translated summary to the same paragraph opening, preserving its words. Preserve body wording and paragraph boundaries, and renew alignment and facsimile offsets after rebuilding.

## 4. What the print says, not what it should say

- **Spelling, punctuation, capitalization and typographical slips** are copied as printed, on every
  print: every abbreviation mark (`ABBREVIATIONS.md`), `ſ`, u/v, i/j, `&`, ligatures and accents
  exactly as printed. `expand` normalizes them afterwards; a reader never does.
- **`ſ` only in an `old` print** (`work.json`, §7). The scout found no long s in a `modern` print, so
  a long-s shape there is a speck on a round s: write `s`. If a `modern` print really shows long s,
  the declaration is wrong: report it, don't decide it page by page.
- **An emendation** (a wrong citation, a certain printer's error) is made only by the adjudicator,
  never by a reader (a reader flags it, below). It is allowed in the body only together with a note
  in exactly this form, anchored immediately after the emended word or phrase:

  ```
  …ad uiuificantem^[Editor's note: the print reads iuuificantem; read uiuificantem.]
  ```

  `the print reads X; read Y.` with X and Y as exact strings, and Y the text just before the note.
  That makes the printed page recoverable by code, so the page stays usable as training data. A
  suspected error keeps the print in the body: `^[Editor's note: so the print; probably …]`.
- **Inside a footnote, the note never nests.** An emendation in a footnote's text puts its
  editor's note at the end of that footnote, in plain brackets, not `^[…]` at the word:

  ```
  ^[1. … Quidquid vero censeas … propugnavit. [Editor's note: the print reads Quiquid; read Quidquid.]]
  ```

  A footnote cut at the page foot takes the note at the end of its `⟦CONTINUED-NOTE⟧` block (the
  last piece, if it runs over several pages). An unclosed, doubled (`^[^[`) or nested note is refused
  by the platform and by preflight.
  Adding or deleting any note renumbers every later note of the whole assembly (numbers are
  positional, per section order): do it before translation alignment, never after — late notes
  invalidate every downstream translation footnote number and every alignment disposition.
- **An editor's note is the editor's own text, in its final form:** `expand` copies it verbatim.
  X is the print letter for letter; everything else (the explanation, a Latin quotation used as
  evidence) is written as it will be published. Never number it: the assembler numbers every note.
- **Uncertain readings** are `⟦word?⟧`. Flag rather than guess.

## 5. Layout and type

- In prose, use one paragraph per line with a blank line between paragraphs. Join width-induced
  line wraps; a word hyphenated at a prose line end is joined (`volun-` / `tati` is `voluntati`).
  A line-end hyphen survives only on a page's last line (the hyphen seam, below).
- Verse preserves semantic verse lines with Markdown hard breaks (two trailing spaces before newline)
  and blank lines between printed stanzas. Join a width-induced wrap within one verse line. Close
  and reopen italic spans on each semantic line. Check verse-line/stanza counts and hard breaks
  survive both expansion and assembly.
- **What repeats on every printed line goes with the line breaks.** Many 19th-century prints open
  each line of a quotation with « or ». Keep the quotation's opening « and closing », and drop the
  repeated line-start marks. They are never a note mark and never `*`.
- On two-column pages, the left column in full, then the right.
- **Headings** are whole bold lines (`**THESIS XIV.**`), whatever face the print uses. There, bold
  is structure: the work's `structure.json` matches it.
- **Faces in the text:** italic is `*…*`, in the body and in notes. Bold (`**…**`) and bold italic
  (`***…***`) are written only for the devices the work's `FORMATTING.md` lists. The scout settles
  them once, from a font layer or a 300-dpi crop. A reader never judges weight from ink: a heavy
  scan makes roman look bold and italic look bold italic. No line opens and closes with `***`.
  Never add a device the print does not have.
- **Every span closes on the line it opens.** A span the print carries across a paragraph or page
  break is closed before the break and re-opened after it. So every line has an even number of
  asterisks, a `*` note mark (`^[* …]`) aside. `exscriptor.assemble` refuses a page otherwise.
- **Glyphs the fount draws alike** (1 and l, 0 and O) are written as the sense needs: a digit in a
  number (`1. q. 23. a. 4.`, `1. dist. 41.`), a letter in a word or an abbreviation (`l. c.` for
  loco citato, `l. IV.` for libro IV). This is a reading, not a doubt.
- **At a hyphen seam,** the next page begins with only the remaining fragment.

## 6. The trailing comment

One comment, the last thing in the file, with these keys (omit a key that doesn't apply):

```
<!-- notes: footnotes: N; margins: N; continues: yes|no; continued: yes|no; omitted: none|<what>; uncertainties: <sites>|none; catchword: <text>|none; signature: <text>|none; joins-next: space|hyphen|para -->
```

`continues`/`continued` say whether this page has `⟦NOTE-CONTINUES⟧` and `⟦CONTINUED-NOTE⟧`.
A training set uses the counts to reject a page whose notes don't add up.

## 7. Declare it in work.json

A work whose page files follow this contract says so in `work.json`:

```json
"page_files": {"contract": "diplomatic-v1", "print": "old", "dir": "diplomatic", "scans": "pages"}
```

- `print`: `old` (abbreviation marks or long s: the work has an abbreviation table) or `modern`.
- `dir`: where the page files are (`pg-NNN.md`), normally `diplomatic`.
- `scans`: the directory holding one `pg-NNN.jpg` per page file, named like it. Scan and page
  file are paired by that name (a symlink each is enough when the renders live elsewhere).

There is no normalized mode: every reader's page files are diplomatic. The declaration is also what
puts the work on the shared pipeline: `exscriptor.status` reads the pages from `dir` and requires
the `expand` edition layer.

## Checklist for a work's TRANSCRIBE_INSTRUCTIONS.md

The brief quotes §§2–6 verbatim, with these exact Unicode markers:
- `⟦M⟧`;
- `⟦NOTE-CONTINUES⟧`;
- `⟦CONTINUED-NOTE⟧`;
- `⟪OMITTED: …⟫`;
- `⟦word?⟧`.

It adds the work's own mapping from `FORMATTING.md`. A brief that departs from this contract
(another marginal convention, omitted zones) says so in one line and why. It also sets
`"contract"` in `work.json` to something other than `diplomatic-v1`.
