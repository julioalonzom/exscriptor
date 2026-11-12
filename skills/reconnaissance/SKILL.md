---
name: reconnaissance
description: Measure a scanned edition before any body page is read. Settle its rights, scope, section tree, print devices, marks and reader, and write the reading brief. Use at the start of a digitization job, or before extending a work into a range not yet covered.
---

# Reconnaissance: measure the print before reading it

No body page is read before this session ends. Reconnaissance decides what is
expensive to change once a thousand pages exist:
- what is in scope;
- how the sections nest;
- how the print signals a paragraph;
- what happens to marginalia and abbreviation marks.

It costs a few sample pages, all read with your own vision.

Inspect the scans with your own vision, page by page, at full resolution. The
reader you use for production is a reader, not a scout. A structural decision
taken from a downscaled strip or a model's summary is one you will discover is
wrong only after the pages are transcribed.

Policy (spelling, punctuation, notes) is the Schola Thomistica editorial
handbook, https://scholathomistica.com/handbook. These skills say how to apply
it with exscriptor.

## What it leaves behind

Everything lives in the job's folder (`<work>/`), so that a fresh session can
pick the job up from the files alone.

| File | What it holds |
|---|---|
| `SCOUT.md` | the measurements below, in prose, with page references |
| `work.json` | the machine-readable job, read by `python3 -m exscriptor.status <work>` |
| `structure.json` | the printed contents as a section tree, with heading patterns |
| `FORMATTING.md` | which print device becomes which markup, with examples and exceptions |
| `ABBREVIATIONS.md`, `abbreviations.tsv` | a print with marks or long s: the mark inventory |
| `paragraphs.json` | only for a marked paragraph convention (§4) |
| `TRANSCRIBE_INSTRUCTIONS.md` | the reading brief the reader follows |

## 1. The edition, its rights and its text layer

Record, before anything else:

- **The item and the edition.** The item you are reading (host, identifier,
  download URL), and the edition itself: author, title, printer or publisher,
  place, year, volume.
- **The rights basis for the edition.** A public-domain claim is about the
  *edition*, not the author's dates. A critical edition, introduction,
  apparatus or modern translation can carry its own live right.
- **Whether the PDF has a usable text layer, and how good it is.** Check two
  pages with `pdftotext -f N -l N` and give the words right as a percentage.
  - That layer is your independent witness later, and on a modern print with a
    clean layer it may be the reader itself.
  - On an early print, test whether it distinguishes the printed `f` from long
    `s`. If it does not, record that blind spot, so QA supplies independent scan
    review for it.
  - If `pdffonts` lists real font names (not a single synthetic
    `GlyphLessFont`), the layer carries italics and bold exactly; read them from
    PyMuPDF span fonts instead of asking a vision model.

Render the pages yourself: `pdftoppm -jpeg -r 200`, with zero-padded names
(`pages/pg-NNN.jpg`), all at one resolution. Keep the renders. They are the
pages the reader gets, and later the pages a facsimile is registered against.

Done when `SCOUT.md` names the item, the edition, its rights basis with
evidence, and the text layer's accuracy.

## 2. Scope: three scopes, never one range

Keep separate, and write down separately:

- the **source** scope: what the volume contains;
- the **reading** scope: the pages and zones you will transcribe;
- the **facsimile** scope: the pages you will attach as images, if any.

Verify on a real full-page render:
- the first and last content of the requested work;
- its neighbouring works;
- every structural anchor.

Front matter may be substantive: a preface or a dedicatory letter is text. A
contents list or a navigational index, wherever it is printed (front, middle or
end), is research material, not body text, and is never dispatched to the
reader. Distinguish a genuine text merely titled "index" from a list of
locators by inspecting its entries and their page references.

Record every excluded zone and the reason. Where a leaf mixes excluded and
included material (a page that ends one work and begins another), document
the exact treatment that keeps all the included words, rather than dropping
the leaf. Each scope comes from the pages themselves, not from a numeric
range.

A volume can print a whole second work after the first (an editor's
paraphrase, another author's treatise). Find where it starts and cut there.
Its leaves never join the author's chapters, however mid-sentence the
author's text looks without them.

Done when the three scopes and every excluded zone are written down, each
checked on a full-page render.

## 3. The section tree, from the printed contents first

Transcribe every printed contents page with vision, then build
`structure.json`:

- **Every level the contents nests.** The printed headings verbatim, with their
  printed page numbers.
- **A section type per level.** Map each level to the type the corpus uses
  (volume, tractatus, disputatio, quaestio, articulus, caput, sectio,
  introductio, prologus and the like), with the order of each type within its
  parent.
- **A `headings` map.** For each section type, the regex of its heading line in
  the page files. `exscriptor.assemble` matches headings by type in document
  order, and refuses a heading that skips an entry.
- **The page offset.** The offset between the printed page number and the file
  page, verified at several anchors: the start of a part, the first page of a
  book, the last leaf.

Reconcile the contents against body headings now. Match by type and order,
never by title text: a contents line and a body heading are often worded
differently. A flattened hierarchy is much more expensive to correct after the
pages exist than to measure here.

Running-header strips (stacked crops of the top lines, read in one vision
call) are the cheapest way to find where parts begin. They are never ground
truth for a page number: small-crop reads inflate digits, and models add
commentary to their own records. Read every folio that settles an offset off a
full-page render.

Done when every contents entry has its body heading, matched by type and
order, and the offset holds at every anchor.

## 4. Paragraph, note and marginal devices (`FORMATTING.md`)

Sample at least six pages across the volume:
- the first body page;
- a page carrying a heading;
- a footnoted page;
- a page with marginalia;
- a dense page;
- the last page.

On each, identify what the print uses and what each device means.

- **Paragraph starts.** Indent, run-in mark, ornament, numbering, a blank line,
  or nothing at all. Give an example page for each form and every exception
  you saw.
  - A glyph may serve two purposes (a paragraph mark and a printer's signature,
    a paragraph mark and a cross-reference). Classify per occurrence and say how
    the two are told apart.
  - Each convention is measured on this edition: another edition, or another
    book by the same printer, is no evidence.
  - For a marked convention, write `paragraphs.json`: the `marker`, a `literal`
    page-to-occurrences map (1-based occurrences on each page that are *not*
    paragraph starts), and `page_sha256` binding each such page to its
    diplomatic file.
  - Pass it as `--paragraphs` to `exscriptor.expand run`. The command refuses
    stale exception numbers and unclassified marks in notes, so a later reading
    that changes the marks forces you to update the contract, not to guess.
- **Notes.**
  - Where they sit: foot, margin or end.
  - How the anchor is printed: asterisk, letter or figure.
  - How a note that continues on the next page opens.
  - How notes are numbered: per page, per section or continuous.
- **Marginalia.** Distinguish by function and scope, *with the image in hand*,
  not by font or by the print's own name for it. An edition may mix them on one
  page.
  - A whole-paragraph summary becomes `^[⟦M⟧⟦R⟧ …]` and is published as an
    italic run-in opener.
  - A local label or a citation becomes `^[⟦M⟧ …]`.
  - Every marginal item keeps its physical anchor.
- **Type and layers.**
  - Columns.
  - Italics and how they are used.
  - Small capitals, letterspacing, drop capitals (all become plain text).
  - Greek and Hebrew.
  - Quotation marks.
  - Any layer you will not publish (a commented text above an anchor heading, a
    facing translation), and where each begins and ends.
- **Running heads, folios, catchwords, signatures.** Dropped from the body;
  recorded in the page's trailing comment.

State, for each device, what it becomes in the page files (the contract is
`diplomatic-transcription`), and name it in the reading brief. Where the
edition is inconsistent with itself (italicizing a term on some pages and not
others), record the inconsistency, so QA audits it per occurrence instead of
trusting one sample.

If exscriptor cannot express a convention this print uses, stop and report the
gap (an issue on github.com/julioalonzom/exscriptor) before production reading;
a per-work edit of derived files is undone by the next build.

Done when `FORMATTING.md` maps every device you saw to its markup, with an
example page for each and every exception.

## 5. A print with marks: the abbreviation inventory

If the sample pages show contraction marks, superscript letters or long `s`,
read them at high resolution and list every mark. Follow Cappelli's six
categories (*The Elements of Abbreviation in Medieval Latin Paleography*,
trans. Heimann & Kay):
- truncation;
- contraction;
- a mark with a meaning of its own;
- a mark whose meaning depends on position;
- superscript letters;
- conventional signs.

`ABBREVIATIONS.md` has one row per mark:

- the glyph as an exact Unicode character and code point (`ꝓ` U+A753, never a
  plain letter plus a guess);
- its expansion, and where it may stand (`ꝯ` is *con-* at a word's start, `ꝰ`
  is *-us* raised at its end; `;` after `b` is *-bus*, after `q` *-que*);
- an example page;
- whether it has exactly one meaning in *this* fount. Another printer's table
  is evidence, not the rule.

`abbreviations.tsv` is the machine half: the rows `expand` applies. Its
columns are `pattern  expansion  kind  note  glyph`, where kind is `literal`,
`token` or `regex`.
- **Only marks with exactly one meaning in this fount.**
- **A mark with several meanings stays out.** The p-marks are the usual case
  (`ꝑ` *per/par*, `ꝓ` *pro*, `p̄` *prae*, near-identical in some founts); the
  lexicon or the editor decides them per occurrence.
- **Unknown results go to the editor.** `expand` sends any table expansion that
  yields an unknown word to the editor.

Generate the brief's mark list from the table, never by hand:

```bash
python3 -m exscriptor.expand brief <work>/abbreviations.tsv >> <work>/TRANSCRIBE_INSTRUCTIONS.md
```

A mark found later (readers flag it `⟦mark: description⟧`) is added to both
files with its evidence, and the brief is regenerated.

Done when every mark on the sample pages has its row, and the table holds
only single-meaning marks.

## 6. u/v and the era

Sample a dozen `v`-words and a dozen `u`-words. Decide whether the print
already writes consonantal `v` and vowel `u` the way the edition's orthography
does (most 19th–20th-century Latin does), or writes `u` for both and by
position (most early prints). In the second case, normalization is a lexical
decision per word, and its exceptions are the editor's (`decisions.tsv`), not
the reader's.

Record the era too. It sets which reader can be trusted, what the OCR layer is
worth, and what the cost per page will be.

Done when `SCOUT.md` states the u/v practice with its sample and the era.

## 7. `work.json`

```json
{
  "slug": "<site work slug>",
  "source": {"url": "https://archive.org/details/<id>", "edition": "Printer, Place Year, vol.", "rights": "public domain: <basis>"},
  "mode": "create | translate-only",
  "languages": ["la", "en"],
  "pages": {"first": 17, "last": 404},
  "page_pattern": "pg-{n:03d}.md",
  "page_files": {"contract": "diplomatic-v1", "print": "old | modern", "dir": "diplomatic", "scans": "pages"},
  "uv": "normalize | as-printed",
  "reader": {"name": "<who reads the pages>"}
}
```

- **`print`** is `old` if the sample pages show any abbreviation mark or long s
  (then §5 is required, and `expand` runs with `--table`), and `modern`
  otherwise.
- **`uv`** is `as-printed` when the print already follows the house rule
  (`expand --keep-uv`).
- **`page_files`** puts the work on the shared pipeline: diplomatic → `expand`
  → `edition/`.
- **`reader`** is chosen on two or three sample pages, each read by the
  candidates and adjudicated by hand against the scan
  (`scan-transcription`, "The reader"). A paid route needs the payer's
  authorization, after you quote pages × price.
- **`manifest`** (`work`, `authors`, `sources` keyed by language, `batch_slug`)
  is what `python3 -m exscriptor.manifest` builds the batch from; its
  `--help` has the contract. Fill it here, while the rights are in front of
  you.

Done when `python3 -m exscriptor.status <work>` reads it and names the next
step.

## 8. The reading brief

`TRANSCRIBE_INSTRUCTIONS.md` contains:
- the page-file contract (`diplomatic-transcription`, §§2–6, quoted
  verbatim);
- this edition's `FORMATTING.md` mapping;
- the generated mark list, for a print with marks;
- one or two finished *diplomatic* page files from the closest work, as the
  model of the format (published text is normalized, and teaches readers
  to normalize);
- the provenance (author, death date, edition) and "produce the text, never
  a summary": it measurably reduces refusals, and a refusal that comes back
  as a fluent summary is the worst failure there is;
- every marker in its exact Unicode (`diplomatic-transcription`, the
  checklist): an ASCII `<<ST OMITTED>>` or `[[?]]` in the brief teaches
  readers to emit those bytes, and lookalike markers fail silently
  downstream;
- skip-if-exists and write-on-finish (`scan-transcription`, step 3).

Done when the scope, the tree, the formatting decisions, the mark inventory,
the reader and the brief agree with each other and are written down. Unsettled meaning or an unsettled boundary is settled on the
scans before the reader starts. If it cannot be settled, record the
uncertainty and say so in the batch summary, rather than letting a guess
become the convention. A later discovery updates the decision and reruns the
work it affected.
