# Long s: both directions

For a print with long s. `long-s.tsv` (from `expand`) lists an `f` that may
be a long s: `fed`/*sed* misreads, `fit`/*sit* questions. It looks one way
only, and both directions fail: also run

```bash
python3 -m exscriptor.longs screen diplomatic --lexicon <lexicon without this work> --out tmp/fs-sites.tsv
```

which also catches ſ written for f (one 1550 print shipped `ſiunt`,
`inſuſionem`, `Reſutatio` after two QA rounds). Settle each site on the
cheapest rung that decides it:

- **One reading is no Latin word** (`oov`: *Reſutatio*, *conſingunt*,
  *refipifcentiam*, *differere*): the word and its sentence decide. Rung
  `context`, evidence naming the sense. No crop needed.
- **Both are words, and the sentence admits only one** (*diſſerendum* "to be
  discussed" in *quod de humana voluntate … superest*, against *differendum*
  "to be deferred"; *partem ſortis ſanctorum*, Col 1:12): the sense decides.
  Rung `context`. This also settles an `ff`/`ſſ` ligature the crop cannot
  separate.
- **Both are words and both fit** (*fit*/*ſit*, *fine*/*ſine*,
  *adferant*/*adſerant*): only the glyph decides. Crop it (`exscriptor.longs
  sheets`) or send it to the hard-case vision route
  (`hard-sites.md`). The crossbar runs through the stem on f and stops at the
  left on ſ. Rung `scan`.

A word the lexicon lacks may still be good Latin (*diſſerebam*, *referatis*,
*adferamus*): read the sentence before changing it. Preflight's
non-waivable `long-s-swap` gate lists every f/ſ non-word whose swap is a
word, in either direction. A genuine form stays with a ledger row on its
page (`pg`, `quoted` = the token, verdict `retained`, evidence); a waiver
is refused.

A contextual f/ſ question is decided per page and occurrence: a decision for
one word establishes no other occurrence, and preflight refuses broad
ambiguous wildcards. Where a usable OCR witness is declared,
`long-s-witness` flags further rare disagreements; settle them on the scan.
With no OCR, or one that merges f and ſ, this screen is incomplete: review
the scans independently and record that limitation.

**A reader that writes long s as s** (some fine-tuned page readers) hands
the corrector one image decision per s, about 200 a page. The corrector's
ſ/f changes against the draft are a site list of their own: its errors
cluster there.
