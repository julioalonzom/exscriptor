---
name: transcription-qa
description: Use after a transcription is read (critic + adjudication on the page files) and again after a translation (adjudicating the translator's suspects). The independent check that finds what a reader got wrong, decides it on the page, and proves every fix landed. Never run by the agent that produced the text.
---

# Schola Transcription QA

Nobody reviews a staged batch for its readings after this skill: the editor
who approves it does not proofread it (`../README.md`, "Staged means
finished"), so this is the last reader the text gets. It runs twice in every job:

- **QA-1, after transcription:** the readers' flags are ledgered, the editor
  pass settles what `expand` could not normalize, a critic screens the pages
  and ledgers findings, then an adjudicator decides each one on the page.
- **QA-2, after translation:** the translator's suspects are adjudicated, on
  both the Latin and the English side.

## Why it works this way

**The dangerous failures are the fluent ones.** A misread letter is cheap and
obvious. What reaches production reads perfectly: an English summary where the
reader declined a page, one junk token standing in for many real words, a
duplicated clause, a column chunk silently dropped, the commented author's text
in front of the commentator's. **You cannot find these by reading the
output**, only by comparing it with something independent: a second reader,
the scan's OCR layer, a digital edition, a lexicon, the page image. Each has
different blind spots, and any one alone has shipped an error past the others.

**Structure beats instruction.** What the layout guarantees is checked in code
over the text (`exscriptor`), not asked of a reader and trusted.

**A five-page benchmark does not predict sixty-page behaviour.** Per-word
accuracy was ~99.6%; the failures above are per-page events that never
occurred in the sample. Screen every page anyway.

## Roles

- **Critic**: one or more agents that are not the transcriber. They run the
  screens and compare a sample against the scans, and they write ledger rows
  with evidence. They never edit the text.
- **Adjudicator / editor**: decides every row on the page, edits the
  diplomatic page files (never re-transcribes), and closes the row with its
  evidence; as editor, answers `expand`'s doubts in `decisions.tsv`. It may
  be the orchestrator, never the transcriber or translator of the same text.

Subagents write their results to disk (ledger fragments, reports); the parent
harvests the files, never the replies.

**A returned verdict is a lead, never a finding.** A reader's `ok` means "I
believe the text is right here", which is not "this edit is safe". Before a
batch is staged, the parent opens at least three of the sites on the page
itself, and every class of edit is validated mechanically over all rows — the
class, not the sample. The failure this rule exists for: a reader marked a
site `ok`, the orchestration read that as "the bracket is a stale comment",
and stripping the bracket deleted a word the print has (`Patet ⟦antecedens⟧:`
where the page prints `Patet antecedes:`). Preflight passed it, because
preflight cannot see that a bracket was holding a word. Classify each bracket
first: one whose content is a word, numeral or punctuation mark is a reading
and must be replaced by what the page prints; only one whose content is a
comment (`illegible…`, `uncertain…`, `print: …`, a sentence) may be deleted.

## The ledger

One file per work, `<work>/ledger.jsonl`, in the `exscriptor.ledger`
schema (run `python3 -m exscriptor.ledger --help`; the module docstring is
the reference). Each row records:

- `unit` (section key or page name), `block`, and `layer` (`la`, `en`, ...);
- `category`, one of omission / addition / transposition / misreading /
  normalization / structure / translation;
- `quoted`: the text exactly as it stands;
- `issue`, and an optional `proposed` reading;
- once decided: `verdict` (corrected / retained / editorial-note /
  withdrawn), `final`, `rung` and `evidence`.

```bash
python3 -m exscriptor.ledger validate <work>/ledger.jsonl
python3 -m exscriptor.ledger triage   <work>/ledger.jsonl --text '<work>/assembled/*.md'
python3 -m exscriptor.ledger check    <work>/ledger.jsonl \
    --layer pages='<work>/edition/*.md' --layer manifest@la=<work>/manifests/<m>.json
python3 -m exscriptor.ledger summary  <work>/ledger.jsonl
```

A row is not a decision, and a verdict is not a fix. `check` passes only when
no row is open and every correction is visible in every layer named.
`final` must be a verbatim substring of the corrected text (a description
fails the gate), and `quoted` must occur nowhere in the current text —
not even with notes stripped, which the gate also searches. For a merge
or a marker removal, where the old words survive inside the new text, set
`quoted` equal to `final`.

## QA-1: after transcription

Run the screens on the edition layer that `expand` produced (`edition/`),
and fix readings in the diplomatic pages (`diplomatic/`; a legacy modern
work: `transcription/`), then re-run `expand`. A fix is never made in
`edition/`.

### 0. The readers' flags

```bash
python3 -m exscriptor.ledger flags <work>/ledger.jsonl --pages '<work>/diplomatic/*.md'
```

One open row per `⟦word?⟧` and `⟦mark: …⟧` on the pages. Each is decided on
the scan like any other row; an unknown mark also goes into
`ABBREVIATIONS.md` and `abbreviations.tsv` with its evidence, and the brief
is regenerated. Re-run after each reading wave: it adds only new flags.

### The editor pass: `pending.tsv`, `long-s.tsv`, `decisions.tsv`

`expand run` leaves what it cannot decide safely in `pending.tsv` (a nasal
variant, an unknown form, a position-dependent mark, a p-mark whose
expansion is not a word, a `uv-variant`: both u/v spellings attested and
neither dominant, *praeuia*/*praevia*) and, on a print with long s, in `long-s.tsv` (an
`f` that may be a long s: `fed`/*sed* misreads, `fit`/*sit* context
questions). The editor (the adjudicator role) works through both with the
diplomatic page and its scan in hand, and answers in `decisions.tsv`, one
tab-separated row per decision:

```
page	token	occurrence	edition	method	evidence
pg-034	ꝓcisam	1	praecisam	scan	p-bar with the prae stroke, line 12
*	nũquam	*	numquam	editor	the edition spells it out numquam 14x
pg-051	fit	2	fit	scan	crossbar visible: fit, not sit
```

- `page` and `occurrence` (the token's 1-based count on that page) may be
  `*`: everywhere. `token` is the diplomatic token exactly; `edition` is the
  normalized form, which may equal the token (an identity decision: the f
  really is an f). A contextual f/long-s ambiguity requires its own page and
  occurrence; a decision for one word does not establish another occurrence.
  The preflight guard refuses broad ambiguous wildcards. Where a usable OCR
  witness is declared, `long-s-witness` flags additional rare disagreements:
  settle them on the scan, never by copying OCR. No OCR or a witness that
  merges f and long s leaves this screen incomplete; independently review
  the scans and record that limitation.
- `method` is `scan` when the image settled it, `editor` when context or the
  edition's habit did; `evidence` is required.
- A reader's misreading found here (an `f` that is a long s on the page) is
  fixed in the diplomatic page instead, with a ledger row.
- **`long-s.tsv` looks in one direction only, and both directions fail.**
  On a print with long s, also run `python3 -m exscriptor.longs screen
  diplomatic --lexicon <lexicon without this work> --out tmp/fs-sites.tsv`.
  It also catches ſ written for f (Soto 1550 shipped `ſiunt`, `inſuſionem`,
  `Reſutatio` after two QA rounds). Settle each site on the cheapest rung
  that decides it:
  - **One reading is no Latin word** (`oov`: *Reſutatio*, *conſingunt*,
    *refipifcentiam*, *differere*): the word and its sentence decide. Rung
    `context`, evidence naming the sense. No crop needed.
  - **Both are words, and the sentence admits only one** (*diſſerendum*
    "to be discussed" in *quod de humana voluntate … superest*, against
    *differendum* "to be deferred"; *partem ſortis ſanctorum*, Col 1:12):
    the sense decides. Rung `context`. This is also how an `ff`/`ſſ`
    ligature the crop cannot separate is settled.
  - **Both are words and both fit** (*fit*/*ſit*, *fine*/*ſine*,
    *adferant*/*adſerant*): only the glyph decides. Crop it (`exscriptor.longs
    sheets`) or send it to the hard-case vision route. The crossbar runs
    through the stem on f and stops at the left on ſ. Rung `scan`.
  A word the lexicon lacks is not thereby wrong (*diſſerebam*, *referatis*,
  *adferamus* are good Latin): read the sentence before changing it.
  Preflight enforces the `oov` class: the non-waivable `long-s-swap` gate
  lists every f/ſ non-word whose swap is a word, in either direction. Keep a
  genuine form only with a ledger row on its page (`pg`, `quoted` = the
  token, verdict `retained`, evidence); a waiver is refused.
- **A reader that writes long s as s** (some fine-tuned page readers) hands the
  corrector one image decision per s, about 200 a page. Treat that
  corrector's ſ/f changes against the draft as a site list in their own
  right: they are where its errors cluster.

Re-run `expand run` until both files are empty; `exscriptor.status` holds
the job there. Deterministic rules run first precisely so the editor has
fewer decisions to get inconsistently right.

A decision is never a spelling: *charitas* → *caritas* is the corpus
spelling list's (exscriptor's `spelling-map.tsv`, applied by `expand`), and a form the list
does not list stays as printed (house style rule 6). If you think a form
should be classicized, say so in the closing report with its counts; do not
write a row.

### The punctuation pass: `punctuation.tsv`

After the editor pass, before translation. House style rule 7: the print's
punctuation and capitals stay, except where they break a rule on the closed
list. Read each edition page (the scan only when the print's own stop is in
doubt) and write one row per change:

```
page	find	occurrence	replace	rule	evidence
pg-034	dicendum, quod	*	dicendum quod	daril-quod	declarative quod after dicendum
pg-034	Omnis, qui	1	Omnis qui	cc52.2-restrictive	qui restricts omnis
pg-035	est Theologus	1	est theologus	case-common	common noun
pg-036	deus	2	Deus	cc40.4-nomen-sacrum	the God of the Christians, not a god
```

- `find` is the edition text exactly, long enough to be unique where
  `occurrence` is `1`; `*` changes every occurrence on that page.
- `rule` is one of `cc52.2-clause`, `cc52.2-indirect`, `cc52.2-restrictive`,
  `daril-et`, `daril-que`, `daril-quod`, `cc52.2-dash` (punctuation) or
  `case-sentence`, `cc40.3-title`, `cc40.4-nomen-sacrum`, `cc40.5-proper`,
  `case-common` (capitals). Anything else is refused.
- `expand run` applies the rows, records them in `expansions.tsv` (method
  `punctuation`), and refuses the file if any row changes a letter (a case
  row may change only case). No row is the right answer for a sentence the
  rules do not cover: when in doubt, leave the print's punctuation.
- A row whose `find` is no longer on the page (the page was fixed under
  it) is stale and blocks the run: re-read that sentence and rewrite it.

### The screens

Run all of them; each catches a class the others are blind to.

1. **Structure first** (pass/fail, before any accuracy number). Zones and
   voices: `exscriptor.check_markers`, `exscriptor.layer_zones`. Then
   `exscriptor.assemble` with the work's `structure.json`: it refuses missing
   pages, broken comments, unmatched footnote continuations, a heading that
   skips the TOC, and a split that does not round-trip. A page whose words are
   all right and all in the wrong zone passes every accuracy screen.
2. **Coverage against the OCR witness**: `exscriptor.coverage` (recall falls
   when a column chunk is omitted; precision falls when text is invented at a
   seam). Calibrate the threshold on pages you adjudicated by hand. Two of the
   house's own conventions break its *character* alignment on any work with
   footnotes: page files carry no running head, and each note is written at its
   printed anchor inside the paragraph while the witness keeps it at the page
   foot. So where those apply, read its scores as relative only and take the
   omission verdict from **`exscriptor.omission`** (token-level, count-aware
   runs of consecutive witness words the page does not contain, lexicon-filtered
   against the wire noise a bilevel scan's OCR emits, head words dropped by the
   caller). Merkelbach II pp. 7-123, 2026-10-21: `coverage` failed 43 of 117
   pages, worst 0.49, while `omission` found no dropped text at all — the absent
   words were heads, hyphen fragments of the OCR's own line breaks, and noise.
   A low coverage score with no omission run is a witness problem, not a
   reading problem.
3. **Second reading, diffed**, where the route has two readers: adjudicate
   only the disagreements; let the OCR layer settle what it can first. Each
   disagreement is a site made with `exscriptor.shared witness-sites` and
   read blind on its own line: `references/hard-sites.md`.
4. **Lexicon**: `python3 -m exscriptor.lexicon oov` over the edition text
   (build the lexicon excluding this work). Misreads are not words. The
   forms preflight's `misreadings` gate lists (run it with `--lexicon`) are
   decided by blind reads, per form, and waived only as
   `references/hard-sites.md` says. `gemini_sites` records
   qualify when its jobs and readings are retained. For other vision readers,
   retain `qa-reports/blind-readings.jsonl`, one row per site with `id`,
   `unit` (page), `edition` (flagged form), `word` (blind result), `found: true`,
   `reader`, `printed_line` containing the actual `word`, `confidence` (not low),
   a work-relative retained `crop`, its `crop_sha256`, the source
   `page_sha256`, and `prompt_sha256`. Preserve the raw result, page and prompt
   so the record can be audited; hashes alone do not prove a blind visual read.
   Read the
   list per page, not only in aggregate: a sound page's unknowns are vernacular
   glosses, proper names and rare Latin, and an unsound one's are the forms the
   OCR layer emits when it misreads (`contusio` for *confusio*, an `sc` for
   `scr`, a fragment left by its own line break). That makes the screen the test
   for the one failure a page file cannot otherwise reveal: a reader whose
   whole-page vision pass returned filler and who settled its lines from the
   witness, which the contract forbids. Merkelbach II p. 131, 2026-10-23: its
   reader reported exactly that fallback; the page's six unknowns were
   `obsession`, `kwelgedachte`, `defixam`, `ruendi`, `inquirebat`, `silendi` —
   glosses and rare Latin, no OCR noise — so it was read, not copied, and stood.
   Ask every reader whose report mentions the witness whether it used it as a
   second reading or as the source, and check that page against the witness's
   characteristic errors either way.
5. **Orthography**: `python3 -m exscriptor.orthography_screen` on the edition
   text and titles.
6. **Seams**: `python3 -m exscriptor.seams --boundary-audit` on every
   assembled section, with hash-bound dispositions for genuine exceptions.
7. **Lookalike scripts**: `python3 -m exscriptor.script_screen` (a Cyrillic
   е for e).
8. **Citations**: check every citation (book, chapter, verse, question,
   article) against a witness: the quoted source, the edition's other
   citations of the same place. A citation found in no witness is an
   over-correction or an invention.
9. **Formatting**: the work's `FORMATTING.md` mapping, audited per occurrence
   on the edition's high-frequency device
   (`../scan-transcription/references/lessons.md`, "Worked method").
10. **A digital edition of the same text, where one exists** (CT for the
    Summa): it flags and never settles. Fetch narrowly, never commit it
    (`references/screens.md`, "A fourth screen").
11. **The critic's sample against the scans**: vision subagents compare the
    first and last page of every chapter, where boundary cuts concentrate,
    plus a seeded random 10% of the other pages (at least 5). The seed and
    the page list go in the critic's report file. They compare the
    diplomatic page with the scan, and report systematic issues as ledger
    rows.
12. **Terminal punctuation over every assembled section and translation**
    (a short script over `assembled/` and `translation-<lang>/`): blocks
    ending mid-sentence and footnote bodies without terminal punctuation.
    Most hits are legitimate (display headings, `etc.`, quotations,
    Greek/Hebrew tails) — judge each suspect on the page image. Real
    catches: a signature mark transcribed as text, an unclosed footnote, a
    sentence broken around a figure or footer. Fix in the page files,
    mirror in the translation, rebuild, re-screen.

A page that fails several screens at once is a bad read: re-read it rather
than patch it.

## Adjudication

Decide **the letters on the page, never the word's plausibility.** Readings
that look wrong to a classically trained eye are often the print's own:
pleonasm, loose connectives, an edition's habitual spelling.

The evidence ladder is the ledger's `rung`, cheapest first:

- context, grammar, parallel passage;
- a witness (another edition, the commented text, the quoted source);
- the OCR layer;
- **the scan**: a high-resolution crop of the line, which outranks every
  other rung.

Climb only as far as the decision needs. Go to the scan below ~95%
confidence, and always for structure and for anything a translation depends
on. The witness ladder for edge-cut text is in `references/screens.md`, "A
sixth screen".

**Printer's errors (standing policy, no per-edition confirmation):**

- *Certain error* (a citation contradicting the verse it quotes, an
  impossible number): correct it in the diplomatic page, with
  `^[Editor's note: the print reads X; read Y.]` right after the emended
  words (`diplomatic-transcription` §4; the assembler numbers it).
- *Suspected error*: keep the printed reading and add
  `^[Editor's note: so the print; probably …]`.
- *Either, inside a footnote*: the editor's note goes at the end of that
  footnote in plain brackets, `^[1. … [Editor's note: …]]`, never nested
  (house style rule 4).
- *Zero-footnote work*: record the reasoning in the ledger only.

**A note that stops short** (it ends mid-word, `ap-]`, or mid-sentence at
the foot of a page) was cut at the page foot. Its rest is on a following
page, never lost. Before writing any note about it:

1. Read the next page's footnote area on the scan. The rest opens it with
   no number, often lower-case or mid-word.
2. If that page's file lacks it, look in its body: an unmarked continuation
   is often read as body paragraphs, which then read as text that "does not
   follow".
3. Repair both pages per `diplomatic-transcription` §2: the cut note
   ends `⟦NOTE-CONTINUES⟧]`, and the rest becomes the next page's last block,
   opening `⟦CONTINUED-NOTE⟧ `. Remove any stray body copy.

An editor's note saying the print has no continuation is refused by
preflight. If the scan of the next page is missing or unreadable, the site
cannot be settled: complete the note from context, with an editor's note
saying what the scan lacks, and escalate it.

**When a reading cannot be settled** after the ladder: take the best reading
from context and Latin knowledge, add the editor's note, set the row's
verdict to `editorial-note` with `"escalate": true`, and go on. The closing
report lists these sites with a one-line offer to re-read them with a
stronger vision model. Stop before staging only if they are dense (more than
~1 per 5,000 words) or touch structure or titles (`../README.md`).

Fix content in the diplomatic page files, then re-run `expand` and rebuild. A fix made only in an assembled file or a manifest is reverted by the
next build.

### Closing the loop (two-reader waves)

When disagreements are adjudicated into per-page decision files and a
separate edit pass applies them:

- After any re-adjudication, sweep every re-decided B/other site for its
  words in the page file before calling the wave done — the editors may
  have worked from instruction files built before the re-decision, and a
  re-decided site silently stays unapplied. Word-presence per site is the
  check, not the editor's reply.
- A B/other decision with no replacement words is a deletion, usually a
  margin gloss duplicated into running text: verify the gloss survives as
  a margin note before the running words go, or the label is lost.
- A page-final word repeated as the next page's opening is the catchword:
  decide A on both, and record it in the next page's opens metadata.
- Adjacent pages' join decisions must agree with each other: when one
  page's decision keeps or drops a join fragment, verify the other page's
  decision on the same join before applying. Two adjudicators deciding
  opposite sides independently produce duplications (fragment kept on
  page N, full word inserted on page N+1); settle the join as one site
  on both images, then flip the losing side's decision file to match.
- A fragment reading at an image edge may be a scan-crop artifact, not a
  print reading: the delivered halves are themselves cropped, and a blind
  reader will faithfully transcribe the clipped letters as a word. Before
  restoring or deleting, check whether the crop is in the image or the
  print (compare line starts down the half; check the OCR witness and the
  page's other half). Never restore letters lost to image preparation;
  never let a cropped-image fragment overturn the running word.
- A page-final fragment or run-over word completed as the next page's
  opening is a break-duplication, not a catchword: verify both sides on
  the image, keep the side carrying the complete word, drop the hinge
  fragment, and ledger the drop. A hyphenated fragment (multitu-) plus a
  whole-word opening (multitudine) is the certain form; a whole-word
  run-over (possunt, li. 16.) repeated as the opening needs the image to
  tell which side is the hinge.
- Page-boundary metadata (`opens:` comments) must track body corrections;
  re-check each one the wave's edits touched.
- Expand the marks, not just the letters: a bare `i` is the imperative,
  `.i.` is *id est*. The same letters with different points are different
  words. Check for a suspension point before accepting a truncated word
  as the print's spelling: `Calcedonen.` abbreviates *Calcedonensem*,
  and grammar (case agreement) confirms the expansion.
- A certain-error correction needs a witness stronger than one reader's
  eyes (the quoted source, grammar plus a second reader). A lone forensic
  read against a blind reader's remains escalated, with the note.
- Never trust a worker's "clean" claim: before dispatching adjudicators,
  confirm the collation files for the exact page range exist and carry
  sites. A missing input file reads as zero disagreements to a worker
  that will happily report all-clean on nothing.
- An editor's note inserted before existing notes breaks sequential
  numbering: renumber the page's notes after every insertion and verify
  each number is unique. For a half-dozen notes or fewer prefer small
  exact-string patches over a renumber script; after any scripted
  renumber, grep every marker and confirm each body text survived — a
  pattern that matches the number but drops the body silently destroys
  margin labels.
- A print reading that is a real word but nonsense in context is still a misprint: a transposition (casuali for causali, three times in one passage on cause), a wrong-but-valid form (mediate for mediante, quis for quia, nostram for nostrae). The adjudicator rightly reports the ink; the parent then keeps the file's correct word with a print note and a ledger row, and flips the decision to A so no editor pastes the print's word in. Recurrence in one passage is the compositor's habit, not corroboration; grammar plus the surrounding argument is the witness.
- Cross-check the decision letter against its own evidence before applying:
  a B/other whose `print` field matches A's words is a self-contradictory
  decision (the adjudicator confirmed A while labeling B) — flip it to A
  instead of editing. Likewise when B's words are a fragment of A's word
  across a line break (`cones` against running `praecones`), suspect a
  double-read of a hyphen-split word and settle it on the image; the
  joined form stands.
- Before correcting a citation number, check the print's biblical divisions
  against modern numbering on citations already verified in the work: an
  isolated deviation (one `Luc. 21` for Lk 22:32 among dozens of matching
  references) is an error, but a systematic offset is the edition's own
  division and must be kept.

## QA-2: after translation

The translator is the first independent reader of every word, and ledgers
what looks wrong without editing it.

1. **Triage**: `ledger triage` drops rows whose quoted text no longer occurs.
   Confirm each such row is really fixed, then close it with that evidence. On
   one run 95 rows became 11.
2. **Adjudicate every remaining misreading row on the print**, and expect most
   to be unfounded: the ear flags the right passages and is wrong about the
   reading most of the time. Leave the translator's reasoning in the row and
   add the verdict beside it.
3. **Check the English side of the same rows.** A wrong Latin reading often
   hides a translation that silently improved on its source.
4. **Normalization rows** become decisions, never hand edits of the pages or
   the edition: `decisions.tsv` for one occurrence (or `*` for everywhere),
   `abbreviations.tsv` for a systematic mark, then re-run `expand run`.
   (A legacy modern work without `page_files`: its `edition_rules.py`.)

   A printer's error is not a normalization: it goes through the
   printer's-error policy above.
5. Re-translate every block whose Latin changed. The final text uses one
   reading throughout.

## Closing

- `ledger check` passes against the pages and the manifest.
- `python3 -m exscriptor.preflight <manifest>` passes (it runs the ledger gate
  again, with the others).
- `ledger summary` gives the counts and the best-guess sites for the closing
  report.

## References

- `references/hard-sites.md`: hard sites (misreadings, second-reader
  disagreements): making them, the reader, what a reading decides.
- `references/screens.md`: screen structure, settling voice by complement,
  the three screens, a digital edition as a fourth, the published text
  against a fresh assembly, and the witness ladder for closing markers.


## Paragraph-summary marginalia

Check every `⟦R⟧` classification against its whole paragraph, including page continuations. A paragraph-wide summary becomes an italic run-in opener in that same block; citations and local glosses stay notes. Preserve printed words, font and anchor in the diplomatic source (`^[⟦M⟧⟦R⟧ …]`) and count it among the M items. Multiple summaries keep print order. Verify the corresponding translated opener, unchanged body wording and paragraph boundaries, and renew alignment and facsimile offsets after any retrofit. An editor's note about a rubric must remain attached to that rubric when it moves.
