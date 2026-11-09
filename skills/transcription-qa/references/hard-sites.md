# Hard sites: one pipeline, every route

A hard site is a word whose reading the page file cannot settle by itself:
- a form the `misreadings` gate lists (seen once, one letter from a common form);
- a disagreement with a second reader of the pages (a fine-tuned page
  reader, a benchmark's re-read, another transcription).

Every site is read **blind**, on its own line, by a reader that is told
neither form. Every rule below was set on a 1624 two-column print.

## Make the sites with the tools, never by hand

A form looked up by itself lands on its first occurrence on the page, not on
the disputed one. On that print, 5 of 8 hand-made sites read other lines.

```
S=tmp/misreadings      # or tmp/witness-<reader> for a second reader
python3 -m exscriptor.shared misreading-sites manifests/<stem>.preflight.json edition/pg-*.md --out $S/sites.jsonl --columns 2
python3 -m exscriptor.shared witness-sites diplomatic/pg-*.md --witness-dir <witness dir> --out $S/sites.jsonl --columns 2
python3 -m exscriptor.shared ocr <the sites' leaf scans> --out $S/ocr.json --lines $S/lines.json --columns 2 --engine tesseract
python3 -m exscriptor.shared crop $S/sites.jsonl --lines $S/lines.json --image '<scan dir>/{leaf}.jpg' --out-dir $S/crops
```

Use `misreading-sites` or `witness-sites` (one per run dir), then `ocr` and
`crop`. Each site gets a line crop, a 3x zoom of the word, and its whole
`page`.

## The reader

- **Free (default):** vision subagents read each crop
  blind. Ask "transcribe this line", naming neither form.
- **A paid vision batch**, only when the person paying has authorized it for
  this job. The model is named on the command line; there is no default:
  ```
  python3 -m exscriptor.gemini_sites --sites $S/sites.jsonl --out $S/gemini --model <model> --poll-wait 5400
  ```
  It writes `word`, `printed_line`, `found` and `confidence` per site.
  - Re-running it sends only the sites without a reading.
  - A site not found in its crop is resent once with its whole page.
  - `--wide <id>` resends a named site with its page.

Keep every run under `tmp/`, with the run's `jobs.json` beside its
`readings.jsonl`. Preflight reconciles every such run.

## What a reading decides

- **It differs from the page:** fix the page, on the reader's own line.
  - A word printed twice on a page goes where the reader saw it. Preflight
    anchors each reading by its `printed_line` and checks the word there.
  - The diplomatic page copies the print's marks (*cõſtantur*, not
    *conſtantur*). `expand` resolves them.
- **It gives a printer's error:** correct it with the house style's
  editor's note (rule 4), never a waiver.
  - A form that is a word in no language (*iudiuiduum*, *teſtimomnio*) is a
    printer's error however faithfully it was read.
  - A note whose reading is the print's own form says nothing, and preflight
    refuses it.
- **It gives a genuine form** you can name and parse: waive it with
  `blind read: <the reader's form>`. Preflight checks the waiver against the
  reading.
- **It settles nothing.** Re-read it, or take the unsettled route: the
  best reading, an editor's note, and a ledger row with `escalate: true`.
  These readings settle nothing:
  - not found;
  - `low` confidence;
  - read on a look-alike line (its `printed_line` falls elsewhere on the
    page than the site; preflight says so; resend with `--wide`);
  - a row you deleted.
- **The reading of a word split at a line end:** half a word decides
  nothing. A reading joined with the hyphen (*ſpirita-lis*) is the whole word.

Preflight refuses each of these:
- a site sent to the reader without a reading;
- a found reading that is not in the batch at its own line, or named in a
  note.
