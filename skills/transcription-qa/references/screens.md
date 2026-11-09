# Screens — accumulated method

Real experience from the Schola Thomistica corpus: the findings that cost
something to make. Load the section you need; the contract is `SKILL.md`.

## Screen structure BEFORE you score accuracy

Every word-counting screen is blind to a page whose words are all correct
and all in the wrong zone — and where commentary prints around the text
it comments, that is the worst error available: publishing the
commentator's words as the author's. Demonstrated twice (2026-08-06) at
healthy word ratios with whole blocks misattributed — invisible to every
accuracy number. So structure is a **separate, pass/fail gate that runs
first**, checked by asking whether independent readers saw the same page
shape (zone-sequence comparison across runs, flagging disagreements,
orphan markers, and voice blocks with no body; exits non-zero so it can
gate). **A majority is a hint, never a verdict** — two agreeing readers
have both been wrong while the lone dissenter was right. When flagged:
open the image, then read the zone *contents*. Corollary: **score
structure pass/fail before any accuracy number matters** — a cheap reader
wrong about whose words they are costs more to re-cut by hand than it saves.

### Settle voice by complement, not by asking readers (Summa-specific instantiation of a general rule)

Comparing readers tells you *that* they disagree about a zone, never *who
is right*, and on hard pages they agree wrongly. Where the page carries a
work **and a commentary on it**:

> **An independent edition of the commented work identifies both voices:
> what it carries is the commented text, and the rest must be the
> commentary.**

One positive test and its complement; no third possibility. There will
never be an independent witness to the *commentary* (it is being
digitized), so a symmetric test would invent one.

- **Look for the commented work's existing digital edition first** (for
  the Prima Pars: CT; detect/repair/profile tooling via exscriptor).
  This is what makes a zone-unreliable reader safe as a *letter*
  witness — rehabilitate a reader only when something other than the
  reader checks the thing it gets wrong.
- **Score 5-word shingles, not words** (commentators quote in 2–3-word
  lemmas; measured: commented-text blocks 0.64–1.00, commentary blocks
  0.00–0.03, nothing between — a mislabelled block scores zero).
- **Score the worst window, never the block average** (a welded-on
  paragraph averages 0.86 and passes); a block whose windows disagree
  needs a *cut* from the page image, not a relabel. The witness never
  supplies a **word** — only *whose voice*, words stay as the page said.
- **Strip your own markup before scoring** (headings, cross-reference
  lines, spliced marginal citations); **build the reference from the
  whole section** (prooemia included); **give it the pages of the section
  it scores**.

### The three screens, and what each alone would miss

Run all three (on one quaestio this found 11 real errors in ~10k words,
including two where both reader passes were wrong and OCR was right):

1. **OCR layer diff** — the only witness with no domain knowledge, so the
   only one that catches silent classicizing.
2. **Second reader pass, diffed** — catches degeneration and dropped
   spans, which OCR noise hides.
3. **High-resolution crop** — settles every disagreement the first two
   raise. Adjudicate from the scan, never from plausibility.

**At quaestio scale, mechanize step 2** — the vote step (same check as
step 5, stated once there). **A page failing several screens at once is a
bad read** — re-transcribe rather than patch, prefer what two witnesses
agree on, even after publication (one production page re-read for less
than a cent beat an hour of hand-patching). **Ask what each screen throws
away, and write one that keeps it** — every normalization-before-compare
opens a defect class no screen reports (here: emphasis asterisks shifted
thirty-seven times corpus-wide under full green checks; the screen that
found it counts asterisks). Before believing a clean report, list what
its checks fold away.

### A fourth screen where one exists: an existing digital edition

Where an edition of the same text exists (e.g. CT for the *Summa*: same
edition and printing, hand-corrected — far stronger than OCR where it
covers), diff against it to decide **where to look harder**. Rules, two
legal:

- **The scan decides.** The edition flags; it never settles. Never adopt
  a reading because the other edition has it — go to the crop; record
  illegible sites as unsettled. This keeps our text independently derived
  from the printed page — the honest editorial position and what keeps
  the result ours.
- **Fetch narrowly, on demand.** The sections being worked, as worked.
  Never mirror a corpus: CT asserts all rights reserved, and while a
  faithful transcription of a public-domain text carries little or no
  copyright, the EU/Spanish *sui generis* database right (Dir. 96/9/EC)
  protects the investment and forbids extracting a substantial part. Bulk
  download is clearly wrong; per-section fetching as a collation witness
  is not.
- **Never commit it.** Third-party edition text is ephemeral working
  material: gitignored, never published, never in an export, deleted
  after adjudication. It must not reach run files or a manifest.

Measured value (12 already-staged articles): seven sites, three real
errors in submitted text — a shared misreading both passes agreed on, a
**silent classicizing** both readers "corrected" from the print, a shared
misreading where ours was ungrammatical — plus one where the other
edition was wrong and ours stood (confirm every flag against a third
witness and the crop: **an edition right nine times is a witness right
nine times, not a source**). Generalize the implementation notes: **align
on the unit the other edition keys** (articles, not pages — so this
screen runs after assembly); **strip your own additions first** (fold out
your markup, nothing else — classicizing variants must survive to be
reported). Disclose the screen in the manifest `method` field like the
others. **Run every new screen backwards over everything shipped.**

### A fifth screen: the published text against a fresh assembly

No reading-screen looks at the site. Once live, rebuild section texts
from the diplomatic pages and diff against what production serves —
production ought to be exactly what the assembler returns. Differences
come from: repairs kept local after shipping; production edits never
brought back; assembler changes between divisions. Two practices:
**reproduce how each batch was actually assembled** (per-batch page
ranges, not whole-work at once — seam-guessing assemblers answer
differently by range) and **run it before starting the next division**.
**Before calling a difference a defect, ask who last wrote that text**
(editor edits are decisions: differences repeating identically across
sections = policy → encode in the assembler; idiosyncratic ones =
defects → settle against the page; a rule kept only in production is
exceptions waiting to be reverted). **Make the screen report its own
coverage** ("N compared / N skipped" — a key pattern matching articles
silently skipped every division-level section, one still printing
invented footnotes after its neighbours were fixed).

### A sixth screen: closing markers with a witness ladder (no vision needed)

Edge-cut crops leave `[illegible]` where the print continues past the crop.
Before re-reading with vision, climb this ladder — on one volume it closed 62/62
without a single new page read. Order by authority; every rung is mechanical:

1. **The twin.** Greek↔Latin↔English inside the edition: the missing word's
   counterpart is usually fully legible in a parallel language (grammar +
   lexicon pin the reading; translators' silence on an intensive like
   `αὐτοῦ` is normal droppage, not counter-evidence).
2. **The same translation in another edition** (e.g. Corderius 1634/1757
   full text for Migne's Corderius). Same translator = same text modulo
   compositor variants; agreement with the twin settles whole clauses.
   Record edition variants in the ledger, never import them silently
   (`erit` vs `efficit`, `exstitimus` vs `extitimus`, added/dropped
   doublets like `de tota`).
3. **OCR of the same edition** (IA `djvu.txt` of the scanned volume).
   Garbled but independent and complete: it sees the words the crops cut.
4. **Full-page OCR rows with coordinates** (local Tesseract over the same
   scans). Crops cut edges; full-page rows often caught the line the crop
   lost — mine them by y-range. Know its failure modes: it silently drops
   hard words and whole lines (absence proves nothing), duplicates a line
   across its column split (same words twice, once garbled), and mangles
   Greek-line Latin-bleed.
5. **The quoted source.** Scripture quotes go to the Vulgate; Thomas quotes
   to the Summa; Maximus to the Maximus text. Verbatim where the edition
   quotes verbatim, sense-checked where Corderius paraphrases.

Reader-failure patterns this ladder exposes (all seen in one volume):
a VLM marker can mask a 50–150-char silent drop (the marker is honest about
*its* word, not about the clause); a fluent unmarked word can be a fusion
of two cut fragments (`commodo` from `corruptio…modo ad` — delete on
witness evidence, don't enshrine); `tess` single letters (`D`, `s!`) are
dirt until a witness promotes them; a same-edition OCR ghost word with no
twin and no print trace (`Trinitate`) is a splice — drop it. Every closure
goes in the defects ledger with its rung (T/E1634/BIM3/TESS/VULG + grammar),
so the next reader can re-derive it without re-doing it.

The ladder's top rung extends to a confidence-gated closure rule (a standing
principle): when every witness leaves only ONE damaged string and
you are CERTAIN of the Greek and English twins, fill the Latin gap by
grammar — do not leave a hole the language can close. Gate it: a certain
restoration goes in clean (ledger the reasoning, no editorial note); a
probabilistic choice (competing grammatical readings) takes the editorial
fallback — best reading + inline `^[Editor's note: …]` (or, on a
zero-footnote work, ledger-only). Verify by grammar and lexicon, not by
facet: the fill must be a REAL Latin form of a REAL word fitting the
deepest syntactic slot left open.

Witness ladder, rung 2 upgraded — the other edition is FETCHABLE, not
broadcast-only: `https://archive.org/stream/<id>/<id>_djvu.txt` via
curl/urllib gives the full same-translation text instantly; grep it for the
sentence (with OCR-garbled variants: `[-c]t`→t, long-ſ→s, doubled vowels,
split words) as often as needed mid-adjudication instead of waiting for
pre-staged witness files. It settles whole clauses and — like any witness —
still yields to the print: record disagreement, never import silently.

### Checking notes and margins: test the witness before excusing it

A repo note said the outer margin "is not machine-checked" because OCR
cannot read small type — true of one tool, repeated as though true of the
page. **The scan's own OCR layer reads the margins fine.** Re-test any
"cannot" claim before building policy on it.

- **Ask a forced choice, not a resemblance** (which of two numeral-forms
  does the OCR text contain — fuzzy matching best-matches "Part. II."
  to the wrong note).
- **OCR cannot arbitrate glyph-identical pairs** (`1` vs small-cap `I`
  errs in BOTH directions) — go to a ~900 dpi crop; **only a RUN of the
  glyph changes the referent** (single `1`/`I` both resolve to one;
  `11` vs `II` is eleven vs two — this triage turned 76 suspects into 3).
- **Count the edition's own convention** — per-abbreviation tallies
  defend readings as well as accusing them (consistent `qu.`-Roman /
  `vers.`-Arabic / `art.`-Arabic habits cleared notes without a crop
  each). Final tally pattern: a handful of wrong references in hundreds
  of notes, plus non-reading defects (printed key copied into the note
  body; orphan emphasis markers) — **sweep note bodies for unbalanced
  emphasis markers** and strip orphans deterministically.
