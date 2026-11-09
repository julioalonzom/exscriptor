# Latin editorial house style (how the policy is applied)

**Policy has one source: the editorial handbook**,
https://scholathomistica.com/handbook (the current edition; each edition
keeps its own URL). It states what is published and why, which authority
each rule follows, and where the corpus departs from Corpus Christianorum or
DArIL. This file does not restate it: it says how each rule is applied (the
tool, the file, the gate) and settles the cases the handbook leaves to the
tools. Where the two seem to disagree, the handbook is right and this file
is a bug: open an issue or a pull request on exscriptor.

**The policy is fixed; the application is per-work.** Every work is
transcribed diplomatically and normalized by `exscriptor.expand`
("Normalization", below); the work's own mapping lives in its work dir
(`work.json`'s `uv`, `abbreviations.tsv`, `decisions.tsv`, `punctuation.tsv`,
`orthography-allow.txt`). Normalization belongs in tooling, never in a
reader's prompt or a hand edit.

Rules 1–6 apply handbook **§latin-orthography**, 7 **§punctuation**, 9
**§translation**.

1. **i/j.** `expand` writes consonantal `i` (*Iesus*, *eius*, *obiectum*).
2. **Ligatures.** `expand` writes `ae`/`AE`, `oe`/`OE`; no ligature glyph
   survives preflight.
3. **Ampersands.** `&` → ` et `, `&c.` → `etc.`, matching the spacing.
4. **u/v.** By the lexicon in `expand` (work.json `uv`), never a global
   replacement. Early-print capitals: vowel-value V → U (`PROBATVR` →
   `PROBATUR`, `neqve` → `neque`); consonantal V before a vowel stays
   (`VIA`). Untouched: Roman numerals (`XV`) and citation abbreviations with
   a standing V (`Bassaeus V.` = *verbo*).
5. **Diacritics.** `expand` strips OCR-spurious accents (*rebúsque* →
   *rebusque*); a diaeresis stays only where the print has it.
6. **Spelling: the corpus spelling list, and nothing else.** The list
   ships with exscriptor, `src/exscriptor/spelling-map.tsv` (`python3 -c
   'from exscriptor import house; print(house.default_map())'`); its header
   says how to read a row. No flag and no local copy: a `spelling-map.tsv`
   lying in a repository or job is a leftover nothing reads.
   - `expand run` applies it and prints its hash; `exscriptor.preflight`
     refuses a batch with any form it would change and records the list's
     sha; `exscriptor.house apply` fixes a layer `expand` does not build (a
     legacy `transcription/` layer, a translation's Latin quotations).
   - **Pairs** (`tanquam$|tamquam$  majority`): two spellings both
     legitimate (*tanquam/tamquam, nunquam/numquam, unquam/umquam,
     quanquam/quamquam, -cunque/-cumque, utrunque/utrumque,
     loquut-/locut-, enunci-/enunti-, quatuor-/quattuor-*): a variant in
     common use in this literature, not a printer's slip. Lewis & Short's
     headword is the standard; a variant it prints beside the headword is
     not exempt by that alone (*caeterus*, *coelum* change). Each work writes the one its own text uses more
     often, a tie keeps the first; `expand run` counts over the whole work
     and prints the choice (`pairs: tamquam 24 / tanquam 7`). Never decide
     a pair by hand or across works.
   - **A closed list.** A form not on it stays as printed: no agent
     classicizes by hand, and `decisions.tsv` is not a spelling channel. A
     new row is a pull request to exscriptor, under its CONTRIBUTING.md
     (a class, evidence in the reason, collisions searched); `python3 -m
     exscriptor.house candidates --lexicon <lexicon>.json` lists
     pairs to propose. A form you think should change goes in the closing
     report with its counts, as a proposed row; a merged row reaches
     earlier works by an edit batch.
   - A name or a quoted vernacular word the map would change (*Sylvanus*)
     goes in the work's `orthography-allow.txt`, with its reason.
   - Corrections outside the map only to a verified reading or an obvious
     misreading, with the evidence in the ledger.
7. **Punctuation and capitals: the closed list, as `punctuation.tsv` rows.**
   - **Mechanical, by code:** `expand` removes a space before `. , ; : ? !`
     (". . ." ellipses are left alone).
   - **The editor's rows**, each naming a rule id from `exscriptor.house`
     (`PUNCTUATION_RULES`, `CASE_RULES`), one id per handbook clause:
     `cc52.2-clause`, `cc52.2-indirect`, `cc52.2-restrictive` (which also
     carries DArIL's closely bound relative clause), `daril-et`,
     `daril-que`, `daril-quod`, `cc52.2-dash`; capitals `case-sentence`,
     `cc40.3-title`, `cc40.4-nomen-sacrum`, `cc40.5-proper`, `case-common`.
     What each clause allows, including its exceptions (feasts and churches
     for *sanctus*, *beatus*; the adjectives made from names), is the
     handbook's text: read it there before writing a row. No row is the
     default answer.
   - `expand run` applies the rows and **refuses any row that changes a
     letter** (a case row may change only case); a row whose text has left
     the page is stale and blocks the run. The pass runs after `expand` and
     before translation, so translators read the revised Latin
     (`transcription-qa`, "The punctuation pass").
   - A work already live keeps its print's punctuation until it is reopened.
8. **Greek/Hebrew** preserved as-is; no Latin rule touches them.
9. **Quotation marks in a translation.** Translators write the target
   language's marks (English “…” with ‘…’ inside; Spanish « »).
   `python3 -m exscriptor.house quotes 'translation-en/*.md'` converts a file
   that carries « », and preflight's `quotes` gate refuses « » in English.

## Editor's notes and the print-is-never-lost rule (2026-09-02)

When a passage cannot be adjudicated after reasonable effort, or the print is
certainly wrong:

- **No doom loops.** If a suspect reading cannot be settled after ~3-4
  evidence lookups (context, OCR witness, page scan), stop investigating and
  make the best editorial choice available. Record why in an inline
  `^[Editor's note: …]` footnote at that exact position in the affected text
  (LA or EN, whichever carries the fix); the assembler numbers it. Footnote markers never add
  paragraph blocks.
- **Follow the print unless you are 100% sure the print is wrong.** OCR
  corruption is corrected to the best reading of the print; the print itself
  is only overridden on certainty (e.g. a Bible quotation that provably
  contradicts the Vulgate it cites). When you do override a certain print
  error, the footnote MUST quote what the print had — the print's reading is
  never lost.
- Uncertain readings that could not be resolved still belong in the work's
  defects/suspects ledger even when an editorial note covers them.

## Rules that replace judgement (2026-10-02)

Each of these was once a judgement call. Apply the rule; do not re-decide it.

1. **Roman numerals in citations are capitals**, at every level and in every
   language: `qu. XLIII, art. 2`, `II *Sent.*, dist. III, qu. VII`,
   `*Ioan.* XIV`, `Cf. num. XIX`, translations included (`q. CXIII`, never
   `q. 113`). The print's small capitals are capitals. Figures stay figures
   where the print has figures (`art. 4`, `ad 2`, `n. 5`, verses). This
   supersedes the earlier two-tier rule (subdivisions lowercase).
2. **The page is not the paragraph.** Running heads, page numbers, signatures
   and catchwords are never text. A page or column break never ends a
   paragraph: a new block starts where the print signals one (for example an
   indent, heading, numbered paragraph or a run-in mark identified during
   reconnaissance). A glyph may also have literal uses in the same print;
   record and preserve those separately. A block that ends without a stop and a next
   block that starts lowercase are one paragraph (`exscriptor.seams`).
3. **One mark per note.** The printed reference mark (`*`, a letter, a
   figure) becomes the note anchor and nothing else; never a literal `*`
   beside it. An italic span closes on its last word, never after a space.
   (`exscriptor` flags both as « stray asterisk ».)
   Marginal summaries that describe a whole paragraph or serve as its title
   become italic run-in openers in that same paragraph, after any numeral:
   `**II.** *Dissolvitur obiectio contra assertionem*.— Sed…`.
   In diplomatic page files, preserve the printed anchor, wording and font as
   `^[⟦M⟧⟦R⟧ summary]`; assembly moves and formats the opener after joining pages.
   Citations and local glosses remain `^[⟦M⟧ note]` at their associated passage.
   Classify by the complete paragraph's scope, not typography: a label for a
   later argument within a paragraph remains local. Preserve each printed item
   in order; invent no titles. Translations use the corresponding opener in
   the same block. This convention applies to supplied transcriptions too;
   actual structural headings remain headings. Audit every marginal item.
4. **Printer's errors.** Certain (a misspelling no reading supports, an
   impossible date): correct it and add `^[Editor's note: the print reads
   X; read Y.]` right after it, X and Y exact strings
   (`diplomatic-transcription` §4). Suspected (it could be the
   author's): keep the print and add `^[Editor's note: so the print;
   probably …]`. An editor's note is written in its final form and copied
   verbatim by `expand`: X letter for letter as printed, the rest as it
   will be published. **Inline notes never nest** (2026-10-23): an
   editor's note on a footnote's own text goes at the END of that footnote,
   unnumbered, in plain square brackets, never as `^[…]` inside it:
   `^[46. Verba Hugonis … censeas. [Editor's note: the print reads
   *Quiquid*; read *Quidquid*.]]`. Several go in order, each in its own
   brackets; a footnote that runs over pages takes them at the end of its
   last piece (the `⟦CONTINUED-NOTE⟧` block). The platform refuses a nested,
   doubled (`^[^[`) or unclosed note, and so does preflight's residue gate. Undecidable after the
   evidence ladder: the best reading, a note, and a ledger row with
   `"escalate": true`.
5. **A missing full stop** at the end of a complete paragraph (typically a
   full, justified line at the foot of a column) is supplied, with a ledger
   row (`normalization`, rung `scan`), and no editor's note.
6. **The editors' own apparatus in the text is print.** A conjecture
   (« quamvis (quoniam?) ») stays as a note, `^[quoniam?]`, at its place. A
   translation gives the conjectured word in the target language with the
   question mark: `^[since?]`, `^[¿puesto que?]`. It is not a question
   (never « why? »).
7. **Translations follow the Latin's punctuation at block ends**: a block
   that ends on a note still ends with the Latin's stop (`…below^[Art. 6,
   ad 1.].`). Citations inside notes keep the Latin's form, numerals in
   capitals; editor's notes are translated.
8. **A term under discussion** (Cajetan's `ly *X*`) is italic in every
   language: "the term *X*", "el término *X*". Never quotation marks plus
   an emptied italic.
9. **A note is one block, however many paragraphs the print sets inside it**
   (2026-10-19). Some notes are an exchange — Merkelbach's `… tantum obligaret
   *sub levi*!` / `Obiciunt a) …` / `b) Etiam allegant …` / `— Sed id falsum
   est : …`, each printed paragraph indented (Summa II, p. 35, continuation of
   p. 34's note 2). Do not close the note at the first break and let the later
   paragraphs fall into the body: a note is rendered as one footnote, and the
   note's `^[…]` text cannot carry a blank line without breaking the paragraph
   it sits in. Write one block and name the print's break points in the page's
   `uncertainties` field, so the flattening is recorded rather than silent.
10. **The body starts at the first text; the title page and blank leaves are
   not part of it** (2026-10-30). The title page's edition, place,
   printer and year go in the source record (`publication_year`, the
   description), never in a section. A blank leaf (title verso, end of a
   part) gets an empty page file, as the contract requires, and no facsimile
   row: a blank page is no page of the work, and a row for it shadows the
   page before it in the reader. Prefaces, dedications, approbations and
   indexes that carry text stay. Preflight enforces both (`title-page`, and
   `facsimile`, which passes the gap a blank leaf leaves).

## Defect tolerance: fix, don't bounce

The policy is handbook **§review**: reliable mechanical defects are fixed
through the reviewed correction mechanism, not grounds for rejection. How:

- A mechanical fix (ampersands, ligatures, j/i, spurious diacritics, the
  spelling map) is applied by an explicit replacement at word boundaries and
  proved by a word-level diff showing only the intended words changed, then
  submitted with `propose_revision`, the contributor's credit intact.
- u/v needs a judgment per token (*Iesu* vs *uirtus*): normalize only where
  the pattern is unambiguous; otherwise keep the contributor's reading and
  say so in the findings.
- Whether a submission is fixable (`propose_revision`) or goes back
  (`request_revision`, naming exactly what would make it pass) is the
  reviewing agent's call: weigh the volume of defects, the ambiguity of each
  fix, and how much reconstruction rather than normalization it needs.
- Normalization never substitutes for collation: verify against the cited
  edition first.

## Normalization: two layers, never mixed (2026-10-01; every print since 2026-10-10)

Every print is read diplomatically and normalized by `exscriptor.expand`,
whoever the reader. The marks and letterforms below are the early prints'
(roughly pre-1700: Briceño 1639, Álvarez 1622, Bañez 1584). A print without
them (Salmanticenses 1870, Franzelin) runs the same `expand` with no table,
and, when its u/v already follows rule 4 (`work.json` `"uv": "as-printed"`),
with `--keep-uv`: then only the safe rules of step 1 change anything.
Reference: A. Cappelli, *The Elements of Abbreviation in Medieval
Latin Paleography*, trans. Heimann & Kay (Kansas, 1982), the six categories
used below; the full *Lexicon abbreviaturarum* (7th ed. 2011) and Pelzer's
supplement from Vatican manuscripts for lookup.

**Two layers, never mixed.** The diplomatic page files copy the print: every
mark verbatim, written with the exact Unicode character the work's
`ABBREVIATIONS.md` names (`ꝓ` U+A753, not `p` plus a guess), `ſ` as `ſ`,
u/v and i/j as printed. Nothing is expanded in the reading prompt: readers
asked to transcribe *and* normalize make more mistakes, and the diplomatic
layer is the training data for smaller readers later. The edition layer
expands everything; zero marks survive into it (gate below).

**`ABBREVIATIONS.md` per edition, written at scouting.** Every mark seen on
sample pages: glyph, code point, expansion(s), where it may stand (Cappelli:
`ꝯ` is *con-* at a word's start, `ꝰ` is *-us* raised at its end; `;` after
`b` is *-bus*, after `q` *-que*), and an example page. Founts differ, so
another printer's table is evidence, not the rule. A mark found later that is
not in the inventory is added with its evidence, never guessed.

**Normalization runs in this order, and only as far as it is safe.**
`python3 -m exscriptor.expand run` (see `scan-transcription`) does
steps 1, 2 and 4 mechanically and queues step 3. Comments and editor's notes
are copied verbatim.

1. **Safe deterministic rules, in code.** These are always right:
   - `æ œ ę` → `ae oe ae`; `&` → `et`, `&c.` → `etc.`; consonantal `j` → `i`;
   - print accents dropped (`quòd`, `à`; the diaeresis is kept);
   - vowel-value V → U in capitals (`SVMMARIVM`), and in lower case after
     *q*, before a consonant, or at a word's end (`Qvibvs`);
   - long `ſ` → `s`, safe because the diplomatic layer writes `ſ` only where
     the print has one (an `f` that may be a long s is step 3);
   - marks that the edition's `abbreviations.tsv` records with exactly one
     meaning (`⁊` → *et*). A table expansion that yields a word the lexicon
     has never seen goes to step 3 instead (`ꝓcisam` → *procisam* is the
     wrong p-mark).

   - the corpus spelling map (rule 6) and the stop spacing (rule 7), from
     `exscriptor.house`, applied last.

   A print's habitual letterform that rules 1–5 change, and code does not,
   is a `decisions.tsv` row with page and occurrence `*`. A spelling is
   never a decision row: it is in the map or it stays (rule 6).
2. **Lexicon-decided: the nasal bar and u/v** (u/v only without
   `--keep-uv`). A tilde or macron over a
   vowel (Cappelli §3.1) is an omitted *m* or *n*, and no positional rule
   decides which: "word-final means m" ships *tamem* and *nom*. `expand`
   generates every m/n and u/v reading and lets the corpus lexicon decide:
   - `unique`, `frequency` and `prefer` (the edition's own spelled-out habit)
     are applied;
   - `variant` (*numquam*/*nunquam*) and `none` go to step 3;
   - a medial *v* is never varied, since it is always a consonant;
   - a form the lexicon does not know takes *u* → *v* where it is certainly
     a consonant: between vowels (*concursiua*), word-initially before a
     vowel (*uenerabilium*), after a verbal prefix (*conuocasse*);
   - a word hyphenated across a page break is decided on the joined word;
   - a well-formed Roman numeral (*iv*, *xv*) is never touched.
3. **Context-dependent cases: the LLM editor pass,** with the diplomatic page
   and its scan in hand, working through `pending.tsv` and `long-s.tsv`
   (`transcription-qa`, "The editor pass", has the file format):
   - an `f` that may be a long s (*fit*/*sit*, *fed*/*sed*);
   - nasal variants and unknown forms;
   - position-dependent marks;
   - the p-marks (`ꝑ` *per/par*, `ꝓ` *pro*, `p̄` *prae*), which are near
     identical in some founts. A real word decides: *procisam* is not Latin,
     *praecisam* is.

   Decisions go in `decisions.tsv` (per occurrence, per page or everywhere,
   method `editor` or `scan`, with evidence), and `expand run` repeats.
   Deterministic rules run first precisely so the editor has fewer decisions
   to get inconsistently right.
4. **Record every change.** `expand` writes `expansions.tsv`: page,
   diplomatic token, edition token, method (`rule` / `lexicon` / `pattern` /
   `editor` / `scan`), detail, count. That table makes the edition
   reproducible from the diplomatic layer, and each row is a training pair.

**A print whose Latin is glossed in a modern language** (Merkelbach II 1935,
2026-10-20). The rules above are rules of Latin orthography, and `expand`
applies them to every token: it cannot tell Dutch `machtelijke` from Latin, so
it wrote `machteliike`, `Ianvier` for `Janvier`, `iugement` for `jugement`,
`Gaude` for `Gaudé`. Every vernacular gloss and modern surname the print
carries therefore goes in `orthography-allow.txt` and is copied verbatim — the
same file the orthography screen reads, so the token is accepted at preflight
too. Latin is not listed: `hìc`→`hic` and `objective`→`obiective` are the rule
working (Merkelbach's `objective/subjective` are the Latin adverbs). List the
file's entries as the *screen* tokenizes — whitespace tokens, so `soi-même`,
`sous-espèces`, `L'éducation`, accents included — not the words inside them.
Grow the file as pages land: a missing token is silently normalized into
nonsense, and only `expansions.tsv` shows it. **Dutch `ij` is a digraph, and
`expand`'s consonantal-`j` rule does not know it**: `huiselijk` becomes
`huiseliik`, `persoonlijk` `persoonliik`, `vaderlijk` `vaderliik` — every Dutch
word carrying the digraph must be listed, and a page whose glosses turn Dutch is
where they surface (Merkelbach II pp. 164-165, 2026-10-24). The screen's own
token is sometimes not a word at all: where the print closes a face against a
gloss (`detineatur.*Ius ad rem*(*à la chose*`), the whitespace token straddles
the markup (`rem*(*à`) and no entry can match it. That was a screen bug, fixed
in exscriptor (`orthography_screen` splits on emphasis markers before reporting,
2026-10-24) — the category list stays the same, only the reported token
changes, so an existing allow-file needs no rewriting.

**The same screen is a misreading screen.** Run `expand` and
`orthography_screen --allow-file` over the edition pages after every reading
wave, not only at preflight: an accent-bearing token that is neither allowed
nor a word is usually a fragment. On Merkelbach p. 25 it found `vertus
annexées,qu qui s'y rattachent` for the print's `vertus annexées ou qui s'y
rattachent` — the reader had read French `ou` as `,qu` and left the following
`qui`, which no marker or seam screen looks for.

## Pre-staging checklist

`python3 -m exscriptor.preflight <manifest.json>` runs the mechanical gates on
the exact file that will be submitted, and the submit scripts refuse without
its passing report. For Latin, that covers:

- the orthography screen on texts AND titles (marks, long s, ligatures,
  `&`, consonantal `j`, print accents, vowel-value V). Titles are metadata
  and bypass every body-text gate. Legitimate exceptions, such as an accented
  author siglum (`Sà`), a vernacular quotation or a proper name, go in
  `<work>/orthography-allow.txt`, one token per line with a `#` reason;
- the spelling gate: no form the spelling map changes and no space before a
  stop (rule 6, 7); the quotes gate: no « » in an English text (rule 9);
- `source_key`, role, license and locator on every text;
- residue, seams, parity, alignment and the ledger.

Two steps stay with the agent:

- [ ] The out-of-vocabulary list is triaged: misreads fixed, names and
  genuine hapaxes left. Pass `--lexicon <lexicon>.json` to
  preflight, or run `python3 -m exscriptor.lexicon oov <assembled la>
  --lexicon <lexicon>.json`. Build the lexicon from the *live*
  text of every shipped work *except the work under examination*, or its
  misreads become vocabulary. Never from the manifests: they keep every
  superseded, rejected and pre-fix version, and one misread staged once
  (Soto's `Resutatio`) then passes every later work's gates. Fetch the
  published texts through the public API (`api.md`), then `python3 -m
  exscriptor.lexicon build '<live texts>' --exclude '<work>/*' --out
  <lexicon>.json`. The lexicon records its sources: `oov` and
  preflight refuse one built from this work's files.
- [ ] A distributed sample is collated against the cited edition's scan
  (`transcription-qa`, the critic's sample).
