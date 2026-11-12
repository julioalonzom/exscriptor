---
name: transcription-qa
description: QA a transcription, run by an agent other than the one that produced the text: screens and a critic find misreadings, adjudication decides each on the page, the ledger proves every fix landed. Use after a transcription is read (QA-1) and after a translation raises doubts about the Latin (QA-2).
---

# Transcription QA

This is the last reader the text gets: the editor who approves a batch does
not proofread it (`../README.md`, "Staged means finished"). It runs twice in
every job:

- **QA-1, after transcription:** ledger the readers' flags, settle what
  `expand` could not normalize, run the screens, adjudicate every row on the
  page.
- **QA-2, after translation:** adjudicate the translator's suspects, on the
  Latin side and the translation side.

## Why it works this way

**The dangerous failures are fluent.** A misread letter is cheap and
obvious. What reaches production reads perfectly: an English summary where
the reader declined a page, one junk token standing in for many words, a
duplicated clause, a dropped column chunk, the commented author's text in
front of the commentator's. Reading the output finds none of these; only
comparison with something independent does: a second reader, the scan's OCR
layer, a digital edition, a lexicon, the page image. Each has different
blind spots, and any one alone has shipped an error past the others.

**Structure beats instruction.** What the layout guarantees is checked in
code over the text (`exscriptor`), never asked of a reader and trusted.

## Roles

- **Critic**: one or more agents other than the transcriber. They run the
  screens, compare a sample with the scans, and write ledger rows with
  evidence; the text itself they leave as it is.
- **Adjudicator / editor**: decides every row on the page, fixes the
  diplomatic page file (an edit, not a re-transcription), and closes the
  row with its evidence; as editor, answers `expand`'s doubts in
  `decisions.tsv`. It may be the orchestrator, never the transcriber or
  translator of the same text.

**A returned verdict is a lead, not a finding.** A reader's `ok` means "I
believe the text is right here", not "this edit is safe". Before staging,
the parent opens at least three sites on the page itself, and validates
every class of edit mechanically over all its rows. The failure behind this
rule: a reader marked a site `ok`, the orchestration took the bracket for a
stale comment, and stripping it deleted a word the print has (`Patet
⟦antecedens⟧:` where the page prints `Patet antecedes:`); preflight cannot
see that a bracket held a word. So classify each bracket first: content
that is a word, numeral or punctuation mark is a reading, replaced by what
the page prints; only a comment (`illegible…`, `print: …`, a sentence) is
deleted.

## The ledger

One file per work, `<work>/ledger.jsonl`, in the `exscriptor.ledger` schema
(`python3 -m exscriptor.ledger --help`; the module docstring is the
reference). A row records `unit` (section key or page), `block`, `layer`
(`la`, `en`, …), `category` (omission / addition / transposition /
misreading / normalization / structure / translation), `quoted` (the text
exactly as it stands), `issue`, an optional `proposed` reading, and once
decided `verdict` (corrected / retained / editorial-note / withdrawn),
`final`, `rung` and `evidence`.

```bash
python3 -m exscriptor.ledger validate <work>/ledger.jsonl
python3 -m exscriptor.ledger triage   <work>/ledger.jsonl --text '<work>/assembled/*.md'
python3 -m exscriptor.ledger check    <work>/ledger.jsonl \
    --layer pages='<work>/edition/*.md' --layer manifest@la=<work>/manifests/<m>.json
python3 -m exscriptor.ledger summary  <work>/ledger.jsonl
```

A row is not a decision, and a verdict is not a fix. `check` passes only
when no row is open and every correction shows in every layer named:
`final` is a verbatim substring of the corrected text (a description
fails), and `quoted` occurs nowhere in the current text, notes included.
For a merge or a marker removal, where the old words survive inside the new
text, set `quoted` equal to `final`.

## QA-1: after transcription

Screens read the edition layer (`edition/`); fixes go into the diplomatic
pages (`diplomatic/`), followed by `expand` again.

1. **The readers' flags.**

   ```bash
   python3 -m exscriptor.ledger flags <work>/ledger.jsonl --pages '<work>/diplomatic/*.md'
   ```

   One open row per `⟦word?⟧` and `⟦mark: …⟧` on the pages, decided on the
   scan like any other row. An unknown mark also goes into
   `ABBREVIATIONS.md` and `abbreviations.tsv` with its evidence, and the
   brief is regenerated. Re-run after each reading wave: it adds only new
   flags. Done when every flag on the pages has its row.

2. **The editor pass.** `expand run` leaves in `pending.tsv` what it cannot
   decide safely (a nasal variant, an unknown form, a position-dependent
   mark, a p-mark whose expansion is not a word, a `uv-variant` such as
   *praeuia*/*praevia*) and, on a print with long s, f/ſ doubts in
   `long-s.tsv` (for that, also `references/long-s.md`). With the
   diplomatic page and its scan in hand, the editor answers each in
   `decisions.tsv`, one tab-separated row per decision:

   ```
   page	token	occurrence	edition	method	evidence
   pg-034	ꝓcisam	1	praecisam	scan	p-bar with the prae stroke, line 12
   *	nũquam	*	numquam	editor	the edition spells it out numquam 14x
   pg-051	fit	2	fit	scan	crossbar visible: fit, not sit
   ```

   - `page` and `occurrence` (the token's 1-based count on the page) may be
     `*`, everywhere. `token` is the diplomatic token exactly; `edition` is
     the normalized form, which may equal the token (an identity decision).
   - `method` is `scan` when the image settled it, `editor` when context or
     the edition's habit did; `evidence` is required.
   - A misreading found here (an `f` that is a long s on the page) is fixed
     in the diplomatic page instead, with a ledger row.
   - A spelling is the corpus spelling list's (`spelling-map.tsv`, applied
     by `expand`); a form the list lacks stays as printed (house style rule
     6). A form you think should be classicized goes in the closing report
     with its counts.

   Done when `expand run` leaves both files empty; `exscriptor.status`
   holds the job there.

3. **The punctuation pass.** House style rule 7: the print's punctuation
   and capitals stay, except where they break a rule on the closed list.
   Read each edition page (the scan only when the print's own stop is in
   doubt) and write one row per change in `punctuation.tsv`:

   ```
   page	find	occurrence	replace	rule	evidence
   pg-034	dicendum, quod	*	dicendum quod	daril-quod	declarative quod after dicendum
   pg-034	Omnis, qui	1	Omnis qui	cc52.2-restrictive	qui restricts omnis
   pg-035	est Theologus	1	est theologus	case-common	common noun
   pg-036	deus	2	Deus	cc40.4-nomen-sacrum	the God of the Christians, not a god
   ```

   - `find` is the edition text exactly, long enough to be unique where
     `occurrence` is `1`; `*` changes every occurrence on the page.
   - `rule` is one of `cc52.2-clause`, `cc52.2-indirect`,
     `cc52.2-restrictive`, `daril-et`, `daril-que`, `daril-quod`,
     `cc52.2-dash` (punctuation) or `case-sentence`, `cc40.3-title`,
     `cc40.4-nomen-sacrum`, `cc40.5-proper`, `case-common` (capitals).
   - A sentence the rules do not cover keeps the print's punctuation.
   - A row whose `find` is no longer on the page is stale and blocks the
     run: re-read that sentence and rewrite the row.

   `expand run` applies the rows (method `punctuation` in `expansions.tsv`)
   and refuses a row that changes a letter. Done when every edition page
   has been read and `expand run` applies the file cleanly.

4. **The screens.** Run every one: each catches a class the others are
   blind to. Every finding becomes a ledger row.
   1. **Structure first**, pass/fail, before any accuracy number: zones and
      voices with `exscriptor.check_markers` and `exscriptor.layer_zones`;
      then `exscriptor.assemble` with `structure.json`, which refuses
      missing pages, broken comments, unmatched note continuations, a
      heading that skips the TOC and a split that does not round-trip. A
      page whose words are all right and all in the wrong zone passes every
      accuracy screen.
   2. **Omission against the OCR witness**: `exscriptor.omission` (runs of
      consecutive witness words the page lacks, lexicon-filtered against
      OCR noise). `exscriptor.coverage` scores recall and precision, but on
      a work with footnotes the house's conventions (no running head; notes
      at their anchors, not the page foot) break its alignment, so read its
      scores as relative and take the omission verdict from `omission`. A
      low coverage score with no omission run is a witness problem.
   3. **Second reading, diffed**, where the route has two readers:
      adjudicate only the disagreements, letting the OCR layer settle what
      it can first. Each disagreement is a site made with
      `exscriptor.shared witness-sites` and read blind on its own line:
      `references/hard-sites.md`.
   4. **Lexicon**: `python3 -m exscriptor.lexicon oov` over the edition
      text, with a lexicon built without this work. The forms preflight's
      `misreadings` gate lists are decided by blind reads, per form
      (`references/hard-sites.md`, which also says what counts as a recorded
      read). Read the list per page: a sound page's unknowns are glosses,
      names and rare Latin; an unsound page's are the OCR layer's own
      misreads (`contusio` for *confusio*, `sc` for `scr`). That is the test
      for a reader that copied its lines from the witness instead of reading
      the page. Ask every reader whose report mentions the witness whether it
      used it as a second reading or as the source.
   5. **Orthography**: `python3 -m exscriptor.orthography_screen` on the
      edition text and titles.
   6. **Seams**: `python3 -m exscriptor.seams --boundary-audit` on every
      assembled section, with hash-bound dispositions for genuine
      exceptions.
   7. **Lookalike scripts**: `python3 -m exscriptor.script_screen` (a
      Cyrillic е for e).
   8. **Citations**: every citation (book, chapter, verse, question,
      article) against a witness: the quoted source, the edition's other
      citations of the same place. A citation in no witness is an
      over-correction or an invention.
   9. **Formatting**: the `FORMATTING.md` mapping, audited per occurrence on
      the edition's high-frequency device
      (`../scan-transcription/references/lessons.md`, "Worked method");
      every `⟦R⟧` marginal summary checked against its whole paragraph
      (`diplomatic-transcription` §3).
   10. **A digital edition of the same text, where one exists**: it flags
       and never settles. Fetch narrowly and keep it out of the repository
       (`references/screens.md`, "A fourth screen").
   11. **The critic's sample against the scans**: vision subagents compare
       the first and last page of every chapter, where boundary cuts
       concentrate, plus a seeded random 10% of the other pages (at least
       5). The seed and the page list go in the critic's report file.
   12. **Terminal punctuation** over every assembled section and
       translation: blocks ending mid-sentence, footnotes without a final
       stop. Most hits are legitimate (display headings, `etc.`, Greek
       tails); judge each on the page image. Real catches: a signature mark
       read as text, an unclosed footnote, a sentence broken around a
       figure.

   A page that fails several screens at once is a bad read: re-read it.
   Done when every screen has run on every page and each finding is a
   ledger row.

5. **Adjudicate** every open row (below). On a route with two readers whose
   decisions an edit pass applies, also `references/two-reader-waves.md`.
   Done when `ledger check` passes against the pages.

## Adjudication

Decide **the letters on the page**, not the word's plausibility. Readings
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
on. The witness ladder for edge-cut text: `references/screens.md`, "A sixth
screen".

**Printer's errors** (standing policy, no per-edition confirmation):

- *Certain error* (a citation contradicting the verse it quotes, an
  impossible number): correct it in the diplomatic page, with
  `^[Editor's note: the print reads X; read Y.]` right after the emended
  words (`diplomatic-transcription` §4; the assembler numbers it).
- *Suspected error*: keep the printed reading and add
  `^[Editor's note: so the print; probably …]`.
- *Either, inside a footnote*: the editor's note goes at the end of that
  footnote in plain brackets, `^[1. … [Editor's note: …]]` (house style
  rule 4).
- *A work with no footnotes*: the reasoning goes in the ledger only.

**A note that stops short** (mid-word, `ap-]`, or mid-sentence at the foot
of a page) was cut at the page foot; its rest is on a following page.
Before writing any note about it:

1. Read the next page's footnote area on the scan. The rest opens it with
   no number, often lower-case or mid-word.
2. If that page's file lacks it, look in its body: an unmarked continuation
   is often read as body paragraphs, which then read as text that "does not
   follow".
3. Repair both pages per `diplomatic-transcription` §2: the cut note ends
   `⟦NOTE-CONTINUES⟧]`, and the rest becomes the next page's last block,
   opening `⟦CONTINUED-NOTE⟧ `. Remove any stray body copy.

Preflight refuses an editor's note saying the print has no continuation. If
the next page's scan is missing or unreadable, complete the note from
context with an editor's note saying what the scan lacks, and escalate it.

**A reading that cannot be settled** after the ladder: take the best reading
from context and Latin knowledge, add the editor's note, set the row's
verdict to `editorial-note` with `"escalate": true`, and go on
(`../README.md`, "Staged means finished", says when to stop instead). The
closing report lists these sites with a one-line offer to re-read them with
a stronger vision model.

## QA-2: after translation

The translator is the first independent reader of every word, and ledgers
what looks wrong without editing it.

1. **Triage**: `ledger triage` drops rows whose quoted text no longer
   occurs. Confirm each such row is really fixed, then close it with that
   evidence (on one run, 95 rows became 11).
2. **Adjudicate every remaining misreading row on the print**, expecting
   most to be unfounded: the ear flags the right passages and is wrong
   about the reading most of the time. Keep the translator's reasoning in
   the row and add the verdict beside it.
3. **Check the translation side of the same rows.** A wrong Latin reading
   often hides a translation that silently improved on its source.
4. **Normalization rows** become decisions: `decisions.tsv` for one
   occurrence (or `*` for everywhere), `abbreviations.tsv` for a systematic
   mark, then `expand run`. A printer's error is not a normalization: it
   follows the printer's-error policy.
5. Re-translate every block whose Latin changed, so the final text uses one
   reading throughout.

Done when every row is closed and every changed block is re-translated.

## Closing

QA is finished when all three hold:

- `ledger check` passes against the pages and the manifest;
- `python3 -m exscriptor.preflight <manifest>` passes (it runs the ledger
  gate again, with the others);
- `ledger summary` has given the counts and the escalated sites for the
  closing report.

## References

- `references/hard-sites.md`: hard sites (misreadings, second-reader
  disagreements): making them, the reader, what a reading decides, what
  counts as a recorded read.
- `references/long-s.md`: a print with long s, both directions.
- `references/two-reader-waves.md`: proving a wave's decisions landed.
- `references/screens.md`: screen structure, settling voice by complement,
  a digital edition as a fourth screen, the published text against a fresh
  assembly, the witness ladder for closing markers.
