---
name: paragraph-alignment
description: Use before staging any batch that carries a translation (required; preflight checks it), and when checking that parallel source and translation paragraphs correspond after imports, paragraph merges or count warnings.
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
   translation was made.
2. **Screen.**

   ```bash
   python3 -m exscriptor.alignment screen <work>/manifests/<stem>.json \
       --target en --report <work>/alignment/<stem>.json [--source live.json]
   ```

   It flags, per section, ratio outliers (target/source length outside
   0.5–2.0), the last pair of every section, and a seeded random sample of
   internal pairs (`--rate`, at least one per section). A section whose block
   counts differ is an error: fix the structure first. The seed is stored in
   the report, so the sample is reproducible.
3. **Read every flagged pair**, with its neighbours:

   ```bash
   python3 -m exscriptor.alignment show <work>/manifests/<stem>.json --report <work>/alignment/<stem>.json
   ```

   Read each pair whole, as `show` prints it. Never clip pairs to their
   opening and closing lines to save context: an omission or a duplicated
   sentence sits in the middle. To save context, read fewer pairs per
   reader, not less of each pair. Compare the argument, not shared names or
   opening words. Look for omitted
   or duplicated content, split or merged paragraphs, headings paired with
   prose, repeated quotations, and a displacement that continues past the
   flagged block. When an offset appears, trace consecutive blocks until the
   mapping demonstrably returns; never apply a blind global shift.
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
   from your file and re-run, the rest merge. Read each
   pair yourself; a disposition written by a program is not a reading. A
   misaligned pair is never disposed: fix it (step 5). Wording defects you
   notice on the way (a typo, a garbled phrase) are not alignment, but
   fix them too and re-screen.
5. **Repair real defects** in the text, then re-run `screen`. A changed
   section's hash no longer matches, so its old dispositions drop and it is
   read again. Readers holding a `show` snapshot must re-run `show` after
   any sibling text edit before reading further — a stale snapshot reads
   pairs that no longer exist and its dispositions are refused. By default correct the target text and its paragraph
   boundaries, never the source wording. In an explicitly authorized
   format-only repair, source paragraph breaks may move to match the target;
   the wording of both stays verbatim. Target-only structural rubrics stay
   separate aligned blocks, with an editorial source-language equivalent
   where needed. When the manifest is rebuilt under a new stem, carry
   dispositions forward: keep only rows whose `section#block@hash` keys
   still appear in the new `show` output (`dispose` refuses the rest, which
   are genuinely changed and must be read again). After a house pass (the
   spelling map, stop spacing or `house quotes`), every key moves though no
   reading changed: `python3 -m exscriptor.alignment rekey OLD.json NEW.json
   --report <old report> --out carried.json` proves per pair that only those
   rules changed it, then `screen` the new manifest and `dispose
   --dispositions carried.json`; read again only the pairs it lists.
6. If the source reading itself is uncertain, it is no longer an alignment
   question: take it to `transcription-qa`. A scan is not needed to
   decide which target block translates clear Latin.
7. **Check**, then run preflight:

   ```bash
   python3 -m exscriptor.alignment check <work>/manifests/<stem>.json --report <work>/alignment/<stem>.json
   ```

## Limits

Ratios and samples locate the pairs worth reading; they prove nothing either
way. Never normalize lengths, translate a quotation twice, or split blocks to
make ratios uniform. Paragraph-count parity and the server's
parallel-alignment validation are structural gates only; the reading above
is the semantic one.
