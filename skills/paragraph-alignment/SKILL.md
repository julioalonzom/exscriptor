---
name: paragraph-alignment
description: Read a translation against its source pair by pair, and record a disposition for every flagged pair in the alignment report. Use before staging any batch with a translation (preflight requires the report), and after imports, paragraph merges or count warnings.
---

# Paragraph alignment

Purpose: every translated paragraph renders the same passage as its paired
source paragraph. Equal paragraph counts are necessary and never proof: an
omitted block and a duplicate cancel each other, and a sustained one-block
offset keeps every count equal while every pair after it is wrong.

The mechanics live in `exscriptor.alignment`; this skill is the reading
method. `python3 -m exscriptor.preflight` refuses a batch with a translation
unless the alignment report covers its current text.

## Workflow

1. **Work from the exact text that will be staged.** For a translate-only
   batch, save a fresh snapshot of the live source and pass it with
   `--source`: imports may have changed paragraph boundaries since the
   translation was made. Done when the manifest and source are the bytes
   that will be staged.
2. **Screen.**

   ```bash
   python3 -m exscriptor.alignment screen <work>/manifests/<stem>.json \
       --target en --report <work>/alignment/<stem>.json [--source live.json]
   ```

   It flags, per section, ratio outliers (target/source length outside
   0.5–2.0), the last pair of every section, and a seeded random sample of
   internal pairs (`--rate`, at least one per section). A section whose block
   counts differ is an error: fix the structure first. The seed is stored in
   the report, so the sample is reproducible. Done when `screen` reports no
   count error.
3. **Read every flagged pair**, with its neighbours:

   ```bash
   python3 -m exscriptor.alignment show <work>/manifests/<stem>.json --report <work>/alignment/<stem>.json [--section KEY …]
   ```

   On a long work, give each reader its own sections with `--section`
   (repeatable; the report's keys, `<work>/<section>` in a two-work batch):
   a whole book's output overflows a reader's context. Each reader writes
   its own dispositions file, and the parent runs `dispose` on them one at a
   time: `dispose` rewrites the one report.

   Read each pair whole, as `show` prints it: an omission or a duplicated
   sentence sits in the middle. To save context, give each reader fewer
   pairs, each read whole. Compare the argument, not shared names or
   opening words. Look for omitted
   or duplicated content, split or merged paragraphs, headings paired with
   prose, repeated quotations, and a displacement that continues past the
   flagged block. When an offset appears, trace consecutive blocks until the
   mapping demonstrably returns, and repair it pair by pair.
   Footnote numbers must correspond 1:1 in order, not just in count: a new
   numbered note in the source shifts every later number, and the
   translation is renumbered to match before staging.
4. **Record a disposition** for each flagged pair in a file of your own,
   `{"<key>": {"verdict": "aligned", "note": "..."}}`, the key exactly as
   `show` prints it after `===` (`q12-a2#20@e88c2490c5`: section, block, and a
   hash of the pair's text, so a reading of a pair edited since is refused),
   or `"outlier-ok"` for a
   legitimate ratio extreme (a heading, a long Greek quotation) with the
   reason. Merge it with

   ```bash
   python3 -m exscriptor.alignment dispose <work>/manifests/<stem>.json \
       --report <work>/alignment/<stem>.json --dispositions <your file>.json
   ```

   The note names what you compared in THAT pair: its numeral, argument,
   example or citation, the first and the last idea. `dispose` and `check`
   refuse a note under six words or the same note on two pairs. `dispose`
   refuses the whole file when any key is stale: delete the refused keys
   from your file and re-run, the rest merge. Each disposition is your own
   reading of the pair; one written by a program is not. A misaligned pair
   is repaired (step 5), never disposed. A wording defect you notice on the
   way (a typo, a garbled phrase) is fixed too, then re-screened. Done when
   every flagged pair has a disposition.
5. **Repair real defects**, then re-run `screen`. A changed section's hash
   no longer matches, so its old dispositions drop and it is read again.
   - **The target moves, the source stays.** Correct the target text and its
     paragraph boundaries. Only an explicitly authorized format-only repair
     moves a source paragraph break, with both wordings verbatim. A
     target-only rubric stays its own aligned block, with an editorial
     source-language equivalent where needed.
   - **A `show` snapshot goes stale** with any sibling text edit: re-run
     `show` before reading further, or the dispositions are refused.
   - **A rebuilt manifest under a new stem** keeps the dispositions whose
     `section#block@hash` keys still appear in its `show` output; `dispose`
     refuses the rest, which changed and are read again.
   - **After a house pass** (the spelling map, stop spacing, `house
     quotes`) every key moves though no reading changed:
     `python3 -m exscriptor.alignment rekey OLD.json NEW.json --report <old report> --out carried.json`
     proves per pair that only those rules changed it; then `screen` the new
     manifest, `dispose --dispositions carried.json`, and read again only
     the pairs it lists.

   Done when `screen` flags nothing without a current disposition.
6. If the source reading itself is uncertain, it is no longer an alignment
   question: take it to `transcription-qa`. Which target block translates
   clear Latin is decided from the texts alone.
7. **Check**, then run preflight:

   ```bash
   python3 -m exscriptor.alignment check <work>/manifests/<stem>.json --report <work>/alignment/<stem>.json
   ```

   Done when it exits 0.

## Limits

Ratios and samples locate the pairs worth reading; they prove nothing either
way. Never even out lengths, translate a quotation twice, or split blocks to
make ratios uniform. Paragraph-count parity and the server's
parallel-alignment validation are structural gates only; the reading above
is the semantic one.
