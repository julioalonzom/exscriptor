# Reading lessons: accumulated experience

What the Schola Thomistica corpus learned by shipping the mistake. Load the
section you need; the contract is `../SKILL.md`.

## The OCR-only workflow

1. **Scope and acquire** — as in `../SKILL.md`, steps 1–2: find the next
   untranscribed section in the source TOC, download the scan, map printed
   pages → PDF pages (`pdftotext` + count form feeds). Record the edition and
   source URL for provenance.
2. **Extract the structure map from the TOC FIRST (mandatory)** — pull the
   work's index out of the scan's front matter (`pdftotext -layout` the TOC
   pages) BEFORE any rendering or cleanup, and write down the nested
   hierarchy exactly as the TOC nests it (every level, printed headings
   verbatim, printed page numbers). Map each level to a corpus section type
   from the platform's vocabulary (volume, tractatus,
   dissertatio, articulus, quaestio, caput, pars, sectio, plus
   introductio/prologus etc.), with per-parent sequence order. The structure
   map is a first-class artifact (keep it in the work dir, e.g.
   `structure.md` / `structure.json`, and encode it in the manifest builder);
   passes 2 AND 3 must both contemplate it — pass 2 keeps headings consistent
   with it, pass 3 splits the assembled text into these exact nested
   sections. Never flatten a hierarchy the TOC nests (measured mistake:
   an introduction was first staged as one flat section; the TOC
   nests § 1/§ 2 with I–IV under each).
3. **Render pages**: `pdftoppm -jpeg -r 300 -f <a> -l <b>` (300 dpi; 200
   works but 300 is safer for footnotes).
4. **OCR pass** — any engine that writes `{filename: text}` JSON:
   `python3 -m exscriptor.shared ocr <pages> --out ocr.json --engine tesseract`,
   or macOS Vision (`pip install 'exscriptor[vision]'`).
   Completion: every page in the JSON; per-page word-count ratio vs the
   embedded text layer between 0.9 and 1.1 (a page under 0.85 has dropped
   text — re-render/retry it).
5. **Write the per-work cleanup instructions** — the LLM pass runs on this
   file alone, so it must be complete. It quotes the page-file contract
   (`diplomatic-transcription` §§2–6) and says the cleanup corrects
   reader and OCR errors to the PRINT and never normalizes: the output is a
   diplomatic page file, and `expand` normalizes it later. Must contain,
   at minimum: the edition/provenance block and the exact structure map from
   step 2; the OCR-artifact catalog below; the footnote rules (mapping,
   inlining, per-page keys, asterisk keys → digit sequence, three-stage
   numbering); the work's `FORMATTING.md` mapping; a word-count quality bar computed
   from the ACTUAL OCR output; the required end-of-run report.
6. **LLM cleanup pass** — delegate to a subagent (or do it yourself); it
   reads the instructions + raw OCR text files ONLY. Its responsibilities,
   in priority order: **(a) section nesting** — every heading present, in
   order, correctly nested, bolded; **(b) footnotes** — extract page-end
   blocks, map mangled markers to body references, inline as `^[N. text]` at
   the reference, number them PER-PAGE as printed (copy the print's keys; the
   print restarts every page — do NOT keep a running counter), fold asterisk
   keys into the per-page digit sequence; **(c) text cleanup** — strip
   running heads/folios/signature feet, join line-break hyphens, reflow
   paragraphs, fix the artifact catalog. Also apply the paragraph-seam checks
   (lowercase start / no terminal period = alarm) as its own per-page
   checklist — the same checks pass 3 re-runs mechanically.
   **The pass is page-by-page by design** — per-page files, per-page
   numbering — so cross-page problems are NOT its job: it flags them.
   The pass-2/pass-3 contract:
   - a note block at the page's bottom whose reference marker is NOT on this
     page (reference on the next page), or a body marker with no note block
     on this page → do NOT guess; leave the note where the print set it and
     end the page file's notes comment with `<!-- dangling: … -->` describing
     it (pass 3 fuses these while assembling);
   - a note CONTINUING across a page break (first half ends without a
     terminal period) → flag the first half as dangling, transcribe the
     continuation normally in the next page's file, pass 3 fuses;
   - within its page: unkeyed bottom block starting with a capital that reads
     as a complete citation = dropped-key note (keep it, attach trailing
     citation lines), unless the block's key count in both witnesses says
     otherwise: when the previous entry has no key line and this text
     extends its citation, it is that note's tail, one note; key line with no text = phantom, drop; unkeyed block
     starting lowercase = continuation — flag as dangling, never emit as body
     text or a fresh note.
   **Output is per-page files, written immediately** (mandatory): write
   `p0NN.md` for each page the moment that page is done, skip any file that
   already exists (resume-friendly, parallel-safe), and never attempt one big
   write (a single whole-section generation truncates — measured twice, no
   output). Each page file ends with a `<!-- notes: … -->` comment recording
   Greek restorations, ambiguous footnote resolutions, uncertain readings,
   and any dangling flags — nothing about a page may exist only in the
   model's reply.
7. **Assemble + review (third pass, the orchestrator)** — bounded work
   regardless of book length; do NOT read whole pages:
   - run the shared assembler (`python3 -m exscriptor.assemble`):
     concatenates p0NN in order, joins seams (hyphenated word across the
     break → join without space; mid-sentence → space; terminal + uppercase
     → paragraph), strips seam/notes comments (`p\d{3}` regex — a `p0\d\d`
     pattern silently misses p100+ page files, measured bug), renumbers
     footnotes CONTINUOUSLY 1..N by order of appearance in ONE pass
     (mechanical; numbers both author notes and editor's notes), runs the
     Marin-Sola paragraph-seam gate, prints seam lines and dangling flags.
   - READ ONLY THE SEAMS: printed last-2/first-2 lines at each boundary, the
     seam-gate violations, and the dangling flags. Fix by hand what the seam
     view shows. The seam checks run in BOTH pass 2 and here — the
     double-check is the point: pass 2's slips show up as pass-3 violations,
     and the gate refuses to stage with any remaining.
   - **Split-note fusion**: a note crossing a page break may come out as a
     truncated inline note plus an unkeyed or `(cont.)`-marked block on the
     next page: append the continuation into the note at its marker, delete
     the stray block; watch for pass-2 DUPLICATION at such seams (a repeated
     sentence at both seam sides). Check a fused note's opening against BOTH
     witnesses for proper names.
   - **Dangling flags in notes are CLAIMS, not files**: a pass-2 page may
     write in its notes comment that a continuation block existed but never
     write the block — the text is silently lost. When pass 3 reads a
     dangling flag, confirm the continuation TEXT is actually present in the
     next page file (mechanically); a flag without the text means pass 2
     dropped it and it must be restored from the raw OCR witness.
   - two-witness diff: words in the assembled text appearing in NEITHER the
     raw OCR nor the embedded text layer → hallucination candidates; witness
     words missing from the assembled text → drop candidates. Triage the
     list; OCR-fix variants are expected noise. Greek is excluded from the
     diff by design — both engines mangle it differently; the report +
     review cover it.
   - footnote checks: numbering sequential with no gaps/duplicates; each
     note's text present in the raw OCR (no invented notes); **split-note
     scan**: any page whose last footnote lacks a terminal period must have
     its continuation fused on the next page; conversely every unkeyed bottom
     block must be explainable as a dropped-key note or a fused continuation.
   - heading presence: every heading from the structure map, in order.
   - **manifest split (structure-map-driven)**: split the assembled text at
     the structure map's headings into the nested sections (`parent_key`
     chains, per-parent `sequence`), strip each printed heading from its
     body, set `source_locator` to the printed page span (span from the
     heading's page to the NEXT heading's page minus one — NOT the heading's
     own page; the last subarticle runs to the region's last page). Verify
     the split round-trips byte-for-byte and footnotes stay 1..N in order —
     then renumber per caput 1..N (third numbering stage).
   - **section texts must come from the SEAM-JOINED assembled text, never
     from raw `\n\n` concatenation of page bodies, and every section text
     must pass `seam_violations` in the builder itself, failing closed**
     (measured: two preface pages staged as mid-sentence paragraphs).
   - read the pages the diff cannot settle (Greek sites, ambiguous footnote
     keys) against the raw OCR / embedded layer, not from plausibility.
   **Production shape: pass 3 is also delegated.** The
   orchestrator only commissions subagents and stages the manifest; the
   pass-3 subagent runs the assembler, reads seam lines and dangling flags,
   fixes cross-page notes, and reports the seam-gate result — the
   orchestrator reviews the report, not the text. Keeps orchestrator context
   bounded regardless of book length.
8. **QA** per `transcription-qa` (an independent critic, then
   adjudication on the page). Nobody reviews after it.
9. **Ingest** via `corpus-import`; facsimile pages come from the same
   renders. Staging mechanics live in `corpus-import`, not here.

## Worked method — auditing one word's italic state per occurrence

1. **Word boxes from the scan's own text layer**, so the crop is exact:
   `pdftotext -bbox -f N -l N raw/<scan>.pdf out.xml` gives each word's box in
   PDF points; scale by `rendered_width / page_width` to map onto the 300-dpi
   render. (The local OCR witness can supply boxes where the PDF has no text
   layer.)
2. **Do NOT trust an automated weight/slant measure.** Two were tried on a
   145-occurrence, eye-adjudicated sample and both were wrong in both
   directions: a centroid-slant measure reads ~0 for round words in either
   face, and an ink-density ratio (occurrence vs the other words on its line)
   inverted true italics on some pages and called italic sites roman on others
   — a neighbouring italic run drags that line's median down. Such a measure
   may propose candidates; it must never decide one.
3. **Triage semantically instead.** A learned-term edition italicizes a term by
   SENSE, not by page: in the sampled edition `esse` is italic in substantive /
   technical phrases (*in esse intelligibili, entitativo, naturali,
   repræsentativo, cognoscitivo, intellectivo*, *esse existentiæ*, *suum esse*)
   and roman as the ordinary copula — even inside an otherwise-italic
   quotation. So triage on the phrase: a technical-phrase occurrence left bare,
   or a copular occurrence marked, is a candidate. This beats the pixel
   measures by a wide margin and costs nothing.
4. **The span criterion — get this right or you will over-count 3×.** An
   occurrence counts as rendered italic when it is wrapped *or when it sits
   inside a larger `*…*` span* (a quotation rendered italic). In the sample,
   6 of 8 "dropped" flags were occurrences the file already rendered italic via
   their enclosing span. Parse span state by walking the text and toggling on
   each single asterisk (skipping `**` heading markers); never by counting
   markers or by regex-matching pairs.
5. **Confirm every candidate by eye** on a labeled montage: crop each
   occurrence with its line-neighbours, stack them, label with the index only
   — never the measurement's guess, which biases the reader. One montage per
   page = one vision call.
6. **Never edit on triage evidence.** Patch only for occurrences the print
   confirmed, and record the repair in that page's own notes trailer (what was
   wrong, how many sites, what evidence).
7. **Calibration baseline** (measured, 16 pages / 145 occurrences, two
   independent checkers, both directions counted): 3 genuine mismatches = 2.1%
   (2 dropped italics, 1 added). Use that to size a repair pass instead of
   assuming a whole-work rewrite is needed.

## Provider-route transferable lessons

What benchmarking buys is *levers*, not a ranking. Durable examples:
image resolution was the quality knob while extra reasoning budget bought
~nothing at many times the price and wall time (set reasoning low, spend
on resolution; note which knobs your transport even exposes — a shim may
hide some, which alone can justify a native endpoint). Transport quirk
(sandbox-specific, may decay): SDK/stdlib HTTP hung indefinitely under the
agent sandbox while the identical request through `curl` returned in
seconds — do not re-debug; it is the sandbox, not the code. Stating the
text's provenance in the prompt (author, death date, archive identifier,
"produce the text — never a summary") measurably reduces refusals.

- **Copyright refusal reads as fluent success.** A modern typesetting of a
  public-domain text occasionally returns an English summary in place of
  the transcription — locally fluent prose where text should be, which no
  OCR screen flags as a reading error. Gate on the way in
  (refusal-phrase check plus function-word density on any page-length
  reply) and never let it reach a file.
- **A provider-side refusal returns nothing usable.** Retried pages
  sometimes clear, but some pages refuse on every retry and geometry — the
  trigger is the *request*, not the page (a short prompt answered where
  the full page prompt was refused). **Do not grind: retry a refused page
  once, then hand it to a different provider's reader and move
  on.** A refusal is a property of the provider, not the page.
- **Token degeneration is found only by the multi-witness vote.** Junk
  tokens with plausible local shape substituted for dozens of different
  real words (plus one leak of the *task* into the text) survive any
  single-pass read — do not detect by word shape or repetition counts
  (both mislead); the vote finds it. A page that needs several attempts
  gets them; retry until one is clean rather than patch.
- **Looping** is the 8-gram / word-count-vs-OCR sweep (`../SKILL.md`, "Read").

## Pitfalls

- **`tesseract` cannot read files under /tmp on some macOS hosts** (leptonica
  "failed to open locally with tail …" / "image file not found" on a PNG that is
  provably valid; pdftoppm writes there fine). Use either
  `pdftoppm … -png "$PDF" | tesseract stdin stdout -l lat --psm 3`, or render into
  a directory under your home and point tesseract at that. `lat` traineddata is
  installed; tesseract is the THIRD witness, after our transcription and the
  scan's embedded OCR (`pdftotext`).


- **Screen the assembled text for wrapper residue before staging.** VLM output
  can leave `<content>` / `</content>` lines (and soft hyphens, U+00AD) in a page
  file; the stitcher treats them as text and drops them *inside words* at page
  seams, where they reach production and are invisible to every count-based
  screen (`grep -c '</content>'` over `transcription/` is the two-second check).
  Fix the page file, then weld the word in the assembled text.


- **A print line-break hyphen is never a paragraph break.** Join the word
  (measured: 24 false breaks in one edition — *scili-cet*, *sa-pientia*,
  *Antichris-tus* — where agents ended a paragraph at a line-break hyphen
  inside the page; the assembler only welds across pages, so these sailed
  into the edition as mid-word block splits). The seam gate catches
  cross-page breaks; within the page, `word-` + break + lowercase-continue
  is always a join.
- **After the last Thomas block on a page, expect the commentator — never
  assume Thomas runs to the foot.** The measured failure: a page ending
  ARTICULUS + question + ST, where the print's bottom column holds the
  commentator's opening lines (Banez q26 a4: *Et haec dicta sufficiant… /
  Circa totam hanc quaestionem… / Ex quo sequitur, non esse de ratione*),
  mis-zoned as Thomas and omitted — leaving the next page opening
  lowercase mid-sentence. Rule: a page whose file ends in ST OMITTED and
  whose next page opens lowercase is a ZONE suspect, not a seam join —
  re-examine the previous page's tail for a voice flip before joining.
  Corollary: the work's LAST page has no next page to raise the alarm, so
  its tail is always verified against the scan by hand.
- **Two-witness screens: count candidates, but DECIDE on blocks.** Per-word
  candidate counts are noise on a hard print — the witnesses are OCR engines and
  garble ordinary Latin, so a healthy page reports a handful of "unwitnessed"
  tokens that are pure variants. The signal that catches a bad read is a LONG
  RUN of the transcription matching no run of the witness (12+ words): that is
  text which was not on the page, and it is how a paraphrase-class read hides
  (it passes every count-based screen because it is fluent Latin of the right
  length). Two traps when you build this: (a) a witness carrying interleaved
  MARGINAL labels shifts a global alignment and produces phantom blocks — verify
  each block's own head/tail before sending anyone to the scan; (b) that
  verification must be FUZZY (skeleton membership), because an exact-substring
  test calls plainly-present text "absent" whenever the witness garbles a
  letter. Matching on a consonant skeleton rather than a prefix stem is what
  keeps either list readable.
- **An assembled range's text BEFORE its first heading belongs to a section, not
  to the bin.** A splitter that only emits sections at matched headings silently
  drops it, and in a commentary edition that leading stretch is usually the
  commentator's own inserted material running up to the next display heading
  (a *Notationes* / *Animadversio* block opening the quaestio, a tractatus tail).
  Assign it to the owning section and REPORT its size; never let it vanish, and
  never treat the section as textless because its heading sits on a later page.
- **A display heading that is not part of the skeleton needs ONE canonical form
  in the brief.** Commentators insert their own titled blocks (`Notationes circa
  omnes articulos…`, `Animadversio notatu digna`) outside the
  liber/quaestio/disputatio ladder; with no stated form, agents render them
  bold-italic (`***…***`), which no downstream pattern recognises. One bold line,
  the printed wording, no emphasis wrapper.
- **In a commentary edition, the edition's own verdicts on the commented text
  belong to the commentator.** Lines like `Conclusio est affirmativa.` /
  `negativa.` that close an article — and any summary remark the edition attaches
  to it — sit OUTSIDE the exclusion zone and are published, while the commented
  author's article text inside it is not. State this in the brief explicitly:
  an agent that infers it is right by luck, and one that guesses the other way
  silently deletes the commentator or republishes the commented work.
- **Citation links need an attribution guard, not just a locus check.** A cited
  locus in the commented work is ours only when no other author's name governs
  the citation: `Caietan. in hoc art.`, `Bannez 1. p. q. 3 art. 2` are that
  author's references, and linking them to the commented work puts words in the
  wrong mouth. Scan back to the sentence boundary for a proper name before
  linking, require an explicit work marker (a bare `q. 3 art. 2` is ambiguous —
  it also points at the commentator's own earlier disputations), and keep the
  pass idempotent by refusing to re-link inside an existing `[[…]]` span.
- **A vision reader on a two-column print: two full-width bands per page, not a crop
  per column.** Vision subagents asked for accuracy will invent a
  band-crop-per-column workflow on their own; it reads correctly and makes each
  page several vision calls, so the session budget — not the page count — sets
  the wave size. But the opposite instruction is also wrong: a WHOLE page handed
  to the reader is downscaled ~4×, and on small-type prints the whole-page read
  comes back materially wrong (measured: a paraphrase with invented clauses,
  invisible to word-level screens because it still reads as fluent Latin).
  **Two full-width half-page bands per page (~2 vision calls) is the measured
  sweet spot** — ≈1.2 min/page/agent at 300 dpi. State the band geometry in the
  brief, add a targeted crop only where bands and the OCR witness disagree, and
  size waves by that budget. Expect early files to land out of order (agents
  read ahead, write each page as they finish).
- **A paragraph that runs across a COLUMN seam is one paragraph, judged by the
  indent.** In a two-column print the continuation stands flush left at the top
  of the next column; a genuinely new paragraph there is indented or opens with
  a numbered run-in. Transcribers split these (pp. 23, 24 of one volume), which
  the paragraph-seam gate catches as PAIR-SEAM/LOWER-START and refuses to stage
  — and which reads perfectly while being wrong. Same class as a page seam, and
  it needs the same explicit rule in the brief.
- **A vision reader's page file can end mid-column with a clean-looking report.**
  The first/last-words reply describes what the agent wrote, not what the
  page holds — one agent dropped an entire right column and reported a
  hyphen join into text it never transcribed. Gate promotion on per-page
  word-count ratio vs the OCR layer (applied per page, not per wave), and never patch a page file before its delegation unit
  reports complete — a still-writing subagent silently reverts or
  interleaves adjudication edits.
- **`seam_join` must join on mid-sentence, not on the next page's first
  letter.** The shared assembler documented "join with a space when the previous
  page ends mid-sentence OR the next opens lowercase" but implemented only the
  lowercase half, so a page ending `… et modo tetigimus,` followed by
  `Proprium est materiae …` became a paragraph break. A capitalised Latin word
  is not evidence of a new paragraph; require sentence-terminal punctuation on
  the previous page before breaking. Whatever the join rule, the gate is what
  catches it — classify every remaining violation before staging.

- **Adversarial spot-check pass before QA acceptance.** For large works, don't
  review the whole transcription — dispatch 2-3 vision subagents that each
  compare a slice of the transcription against the scan: (a) the START of
  each chapter (first page of the chapter vs its transcription), (b) the END
  of each chapter (last page — the chapter-boundary cut-off failure class
  above concentrates here), (c) a few random pages. They report
  systematic issues (formatting, footnote anchoring, lost/lowercase-lead-in
  paragraphs); findings go to the work's defects ledger and get fixed before
  QA. This is cheap insurance for a 700-page work where full-work review is
  too expensive — and translation will later serve as the text-wide second pass.

- **Table of contents comes FIRST.** Extract the ToC as step 1 of any
  digitization, map its nesting (it matters for the platform reader), and at
  assembly time assert the digitized section tree matches it.
- **A page that simultaneously ends chapter N and begins chapter N+1 is
  BOTH.** Orchestrators treating it as only the first page of the new
  chapter silently lose the tail of the previous chapter. Check every
  chapter-start page for prior-chapter tail content, and vice versa at
  chapter ends.
- **A footnote continued onto the next page has no marker number there** —
  models misread the continuation as body text. Detect: a page whose body
  starts mid-sentence without a footnote-continuation handling; footnote
  blocks must end with a period.
- **Paragraphs generally do not start lowercase and generally end with a
  period**; any exception must be individually verified against the scan,
  not waved through.

## Pipeline rules (learned by breaking them, 2026-08)

About the code around the reading, where a batch dies quietly:

- **Read one variable from a credentials file, never source it**, and
  never print a value.
- **Classify terminal errors before writing the retry loop** — match on
  the response *body*, not the status: one status covers both "slow down"
  (retry) and "credits gone" (stop), and status-keyed retries cost ~75 s
  per page relearning depletion. Abort the whole run on credit-death.
- **Append usage rows only on FIRST sight of a batch name** (persist a
  `usage_harvested.json` keyed by batch). A poll-loop harvester that
  appends on every cycle multiplies each batch's usage rows ~70× — the
  ledger then reports ~70× the real spend, and every downstream estimate
  (including abort decisions) is read off the inflated number.
- **Probe the thinking knob in both spellings, per model, before a paid
  batch.** A `thinkingLevel: "low"` setting on one dense-17th-c.
  transcription job still billed 12–28K thought tokens/page at output
  rate ≈ 10× the cost of everything else combined; `thinkingLevel:
  "minimal"` was hard-rejected for that model (400 INVALID_ARGUMENT)
  while `thinkingBudget: 0` was accepted. Probe one real page per
  configuration and measure cost AND quality before batching — reasoning
  buys ~nothing for verbatim transcription (measured ~$0.003/page vs
  ~$0.026 with the knob ineffective).
- **Screen every page file for task/prompt leakage on the way in.** Vision
  models under instruction-heavy prompts leak the prompt or their own
  reasoning into the output (one run: 35/90 files carried prompt phrasing,
  one carried the prompt text wholesale). Gate the way in — refusal-phrase
  check plus a small set of prompt-word greps on each response before it
  becomes a file; a leaked page is re-read, not patched.
- **300 dpi is not a legibility guarantee on a scan with a varying page
  box.** Leaves whose PDF page box shrinks render via `pdftoppm` as
  25–95 px-wide thumbnails a reader refuses or paraphrases. Fix: extract
  the JPX image layer (`pdfimages -png`) and polarity-invert over the
  COLOR layer (the smask is the wrong witness) — restores ~2500×4100
  legibility. Pre-check rendered page width before submitting a batch.
- **Persist per page, and skip what exists** (it has paid out repeatedly).
- **Price a route by the scarce resource, not the invoice** — the reader
  spending session budget also starves the orchestrator; cheap API calls
  beat dead subagents. Cost dimension is per-job (credits vs session
  budget); the person paying decides, and no spend route opens at all
  unless they opened it for this job.
- **A small benchmark measures capability, not rate** — guards must live
  in the production path, not only the benchmark (a truncation-at-20%
  failure escaped because the guard tested only categorically-wrong
  responses while the quantitative check sat twenty lines away in the
  benchmark). State whether a benchmark buys structural or statistical
  coverage; different sample designs.
- **A stated property of the source is a check waiting to be written** —
  falsify README claims with one grep (a "j→i is a no-op here" claim died
  to one OCR-layer grep revealing over a thousand unmodernized tokens
  against dozens of already-published modernizations — consistent
  modernization is invisible to every witness-agreement screen).
- **When a constant moves into a module, grep for the copies it
  replaced** — extracting a computed table does not remove the hand
  copies (one file kept its own alternation below the import; articles
  past its range lost all markers in production).
- **An unreadable-reading marker in a note block usually accuses the
  transcriber, not the page** — look for the spurious marker (apparatus
  letter as asterisk, merged margin notes, margin asterisk double-read
  as body marker) before rendering a crop.
- **When you fix a parsing bug, grep its shape in every sibling parser**
  — zone parsing must carry an **ordered list of (label, body)**, never a
  dict (a dict keyed by label silently dropped a repeated zone; a later
  prompt change armed the dormant copy in a sibling file).
- **A prompt change is a change to every route that imports the prompt**
  — re-read one known page per route afterwards and diff.
- **Normalize at promotion, not in the transport** — attach cleanup to
  the step every page passes through, guarded by assertions (word stream
  unchanged up to case/ligature; zone sequence identical). **A run
  directory must hold what the reader said** — transports that keep
  normalizing make the guard compare a thing with itself (passed 163
  pages because it could not fail) and hide normalization defects from
  the vote. Ask of any never-fired guard what its firing would look like.
- **Deterministic cleanup must be a fixed point on everything already
  promoted** (one-line whole-corpus run; it revealed the gap above).
- **Diff production against a fresh assembly, every round** (same screen
  as the fifth screen — stated once there). **Where a pipeline writes to
  two places, check their difference** — back-port corrections as a
  program, by the same table, or the two part again.
- **Folding is for matching, never for writing** — splice the *original
  surface* and re-check alignment on it (a folded-key back-port wrote
  folded tokens back and corrupted case, numeral script, punctuation).
- **Do not tabulate the first N of an infinite sequence — compute it**
  (three hand ordinal tables each ran out one division early; derive
  genuine data-mappings from the source, e.g. the scan's OCR layer).
- **A cluster of one-off spellings on one page is a structural fault**
  (unjoined line-break hyphens), not misreadings — read the cluster
  before correcting any member (word-count ratio cannot see it).
- **An in-tolerance ratio is not soundness** — systematic token
  substitution preserves word count (0.956 with ~20 substitutions/page);
  only the witness arbitration found it. **Swap in the other witness for
  that page**, never patch instances one by one.
- **`1` vs `I` is unarbitrable as a reading, not as evidence** — the OCR
  layer reports letter-vs-digit reliably; combined with edition habit
  that settles it.

## Known catches

- The scan corrects the corpus: adjudication finds errors in hand-checked
  production text — report them; don't silently edit prod.
- Prompt-stated normalizations are applied inconsistently — mechanical
  rules belong in the deterministic pass, never the prompt (emphasizing
  j→i made accuracy *worse*; "copy what is there" beats both plain and
  emphatic versions).
- Anti-classicizing instructions overshoot into **hyper-archaizing**
  (invented archaic forms) — state "copy what is there"; inventing
  archaic forms is the same error mirrored.
- **A division ends at a sentence, not a page** — bound sections by a
  SENTENCE from the text; running heads lie (one head read two divisions
  ahead while the text continued); confirm a division's end by checking
  the next page's opening. Later-batch truncation of a boundary removes
  the assembler's anchor (symptom: one section with two articles' words).
- **Crop anchoring: `sips -c` crops about the CENTRE**; `pdftoppm -x -y`
  takes a plain top-left origin and is safer. A mis-anchored crop yields
  plausible prose full of holes rather than failing outright.
- Glob-check before paid runs; zero-pad chunk numbers; spread-splitter
  drift (`../SKILL.md`, "Prepare scans").
- **`tesseract` on macOS cannot open files under `/tmp`** (leptonica "failed to open locally with tail"; `file` confirms the PNG is valid). Workarounds: stdin route (`pdftoppm -png … | tesseract stdin stdout -l lat --psm 3`) or a directory under your home. `tesseract` is the third witness (after our transcription + the scan's embedded `pdftotext` OCR) — never make it the only witness.
- **A subagent's background jobs (tesseract, bulk render batches) die with its session** — only a parent-side background process survives. A parent must take over any bulk, page-bound, or long-running mechanical work rather than delegating it to a child whose session will kill it.

#### Pitfall — an edition can alternate a device per occurrence

Do not infer a page's formatting from its neighbours or from a count. One
edition here sets the technical *esse* ITALIC on some pages and ROMAN on
others, and within one page 7 of 8 occurrences italic and the 8th roman — so a
reader who marks none can be right on one page and wrong on the next, and no
majority/count heuristic decides it. Corollaries: (a) a "zero marks" page is
not evidence of a dropped device, it is a page to audit; (b) a page-level
"everything italic" habit is equally suspect; (c) the same test applies to any
device — quoted lemmas, Greek, letterspaced runs, bold.

## Delegation lessons (OCR-only route and subagent waves)

- **Task granularity is the root cause of the reliability gap — size
  delegated pass-2 work ATOMIC, not long.** One section per subagent = one
  bounded write is robust; 30–35-page ranges are 30+ failure points per
  subagent. **The 65K max_tokens reservation**: every delegated API call
  reserves 65 536 output tokens up front; a low balance kills the NEXT call
  with `HTTP 402` — cap the delegation's max_tokens to the real per-call
  need (~4–8K) or top up credits before a big wave. Assign DISJOINT page
  ranges up front (overlapping ranges resolved only by skip-if-exists — half
  the work redundant). Winning shape: chunk pass-2 into ≤10–15-page
  delegations, each brief one contiguous range, reads batched but one
  `write_file` per page in order; a near-end death → the orchestrator
  hand-finishes the missing pages rather than re-delegating.
  Batch the independent reads while keeping every write in its own call
  (~1 call/page) to dodge the platform's per-run tool-call cap.
- **Within the subagent budget (SKILL.md), dispatch a wave's agents
  together**, not one after another: sequential waves took about three times
  the wall clock, and per-page writes let finished chunks be checked while the
  rest run.
- **QA concurrently with transcription** — verify completed chunks and
  adjudicate `⟦greek: ?⟧` flags WHILE agents still write remaining pages;
  doing all QA after serialization is the expensive order, and by the time
  the last page lands most of pass 3 is done.
- **Agent Greek reconstructions from garbled OCR are NOT reliable** — when
  BOTH witnesses garble a Greek (or Hebrew/Syriac) passage, do not accept
  the agent's reconstruction as final; one cheap-vision-adjudicator call on
  a tight crop (or standard-text restoration with an explicit flag) is the
  gate. Measured: four confidently-wrong restorations in one pilot.
- **Vision-adjudication crops must stay small**: > ~8k px wide 413s;
  the service DOWNSCALES ≥ ~3200 px crops to ~1280 px — footnote print
  becomes illegible. Use half-width crops ≤ ~1608 px at 2× (or split a band
  into halves), JPEG quality 85, per-line crops for multi-line footnotes.
  Locate the target line's y-position FIRST by ink-row analysis, not page
  fractions. One-word-per-line output makes extraction reliable; extract the
  transcription from the tail past any chain-of-thought preamble.
- **bbox→image coordinates are unreliable across renders** — freshly located
  raster crops (or full-width band crops the adjudicator searches) beat
  pdftotext-bbox mapping and re-rendered page coordinates.
- **The cheap vision adjudicator is unreliable for Hebrew, Syriac, and
  schema-words in scaling systems** — it hallucinated Psalm verses on scan
  crops; restore from the standard text of the quoted passage, confirm only
  the distinct words; where a word stays unsettled, take the editorial
  fallback (best reading + editor's note, ledgered) rather than looping
  adjudication calls.
- **Manifest split boundaries: body of heading A runs to the START of the
  next heading, never its `.end()`** — slicing at `.end()` swallows the next
  heading into the previous body; keep `_end` positions and slice
  `[end(A):start(B)]`; the round-trip check catches it — always run it.
- **ABBYY-first reconnaissance before rendering** — the embedded text layer
  (`pdftotext`, all pages, even undigitized ones) is the cheapest way to
  scope a region: pin heading pages, find the region's end, and DETECT
  structure the map lacks. Verify structure against the BODY headings, not
  the index (an index can flatten grouping levels).
- **Heading form must be uniform across subagents, or the builder dies with
  "heading not found"** — the pass-2 brief states the exact heading form
  (block titles as two adjacent bold lines; articulus/subarticle headings
  single line); pass 3 spot-checks uniformity.
- **A footnote glued to a heading line breaks the split round-trip** —
  normalize so a heading-attached footnote occupies its own paragraph; pass-2
  briefs say a footnote marker on a heading line still emits `^[N. …]` right
  after the bold.
- **An articulus can be a textless grouping node** — the builder allows
  `texts`-less articuli; a whole data-table page may likewise be SKIPPED on
  the editor's call, the decision recorded in structure notes and the brief.
- **Fused continuation text can be TRUNCATED in the page file — verify
  against the raw OCR before fusing** (measured: a page file carried a
  710-char continuation; raw OCR had ~1,300). Re-read the RAW OCR page when
  fusing a flagged continuation.
- **An indented paragraph opening with a lowercase word is a print anomaly,
  not a transcription error** — verify on the scan (first-line x-offset),
  keep the print reading, document it. When the seam gate reports
  LOWER-START/PAIR-SEAM, CLASSIFY before fixing: duplicate tail,
  same-page split the print runs continuously, abbreviation/Roman-numeral
  terminal, flush-left vs indented continuation, genuine print anomaly →
  keep + document as an EXPECTED violation; zero unclassified violations.
- **latin1 raw quirk** — raw files can be Latin-1: read via `iconv`; the
  German open-quote „ renders as `â` in that decoding — don't "fix" it.
- **read_file truncation** — display can cut a page's LAST lines; before
  declaring a final note missing, verify with `tail`/`wc -l` on the raw file.
- **Transcript silence ≠ stall** — diagnose by page-file count + transcript
  mtime, not the last log line; act only when BOTH freeze for minutes.

## From the OCR-only route's mechanics

### Inline citations and numbered points stay inline

This print genre (19th-c. seminary manuals) puts short source references
INLINE in the body (`Ephes. I, 16. seq.`-shaped) and numbered body points
INLINE too (`Iam vero 1) … 2) …`). Only genuine page-bottom `(N)` notes are
footnotes. A text-pass model will happily "clean up" bare citations and
numbered points into `^[N. …]` markers — mechanically renumbering them and
often dropping the closing `]` so the marker swallows following body text
(one 19th-century manual: 439 spurious markers across 55 sections, published before anyone noticed).
RULES:
- The cleanup brief must state the distinction EXPLICITLY: short citations
  and `N)`/`N°` numbered points stay inline exactly as printed; only
  page-bottom notes become `^[N. …]`.
- A reference may be made a link only as `corpus-import` says (citation links).
- Before staging, mechanically check every `^[N.` marker: content must match
  a page-bottom section in the raw OCR (not a bare citation, not an `N)`
  body point). A hoist → revert inline. If the print has NO page-bottom
  notes in a caput, the caput must have ZERO footnotes.
- Watch for unclosed `^[N.` markers: a missing `]` makes note content
  swallow following body text (measured: one note swallowed two paragraphs).

### Cleanup-brief notes from one modern-print pilot (instance material, not contract)

- **Invisible-marker anchoring** — on scripture-citation-heavy pages a fully
  invisible body marker is the NORM (11 of 24 pages had ≥1). When a note's
  marker is invisible in BOTH engines but the note unambiguously annotates
  one sentence, place it there and document it. NOT a dangling flag —
  dangling is reserved for markers on ANOTHER page. Anchoring two
  marker-less notes back-to-back at one spot is acceptable.
- **Exact footnote-format brief** — state the format, not just the rule, or
  delegates emit bare superscripts with note text stranded in notes comments
  (4 of 5 first-wave pages before the brief was hardened). Caret + open
  bracket + DIGIT key + period + space + text + close bracket at the body
  reference; FORBIDDEN: body superscripts, notes-comment-only text,
  `[1]`/`{1}` styles, asterisk keys.

### Scaling a pilot to a whole work

Learned extending a one-division pilot to three. **Every
failure below produced text that read perfectly and was wrong**, none
could occur in a single-division run, each fixed structurally:

- **Page seams swallow structural boundaries** — a join-unless-heading
  heuristic welds a division that opens in prose onto its predecessor
  (12 of 14 articles vanished). Teach the seam rule the edition's *own*
  opening formulae and block numerals.
- **Display lines run together** — explode whole-line headings into own
  paragraphs before splitting, keyed on line shape.
- **An invented sentinel is the one the reader drops** (`PARALLELA:`-shaped
  lines go missing ~1 division in 4 — nothing on the page to copy; the
  line reads fine and silently never becomes a link). **Anchor inventions
  by POSITION**, never by the droppable sentinel.
- **A commentator's divider has variants** — the split must assert its
  expected section count and refuse to emit otherwise.
- **The reader invents notes** — sweep for the uncertainty-flag character
  before assembling; a high-resolution crop refutes instantly.
- **A second pass invents at least as often as the first drops** — on
  count disagreements check the *direction* before promoting (here every
  count difference was the second pass hallucinating).
- **Word-count ratio vs OCR finds dropped spans cheaply** (0.57 vs 0.85
  neighbours) — same sweep as step 5.
