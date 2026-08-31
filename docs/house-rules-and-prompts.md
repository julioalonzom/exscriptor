# Exscriptor — house-rules and prompts layer

Exscriptor deliberately carries MECHANISMS, not policies. The things that
vary per project live in your project, as explicit documents that the
orchestrating agent and its subagents read:

## House rules (one file per project, e.g. `FORMATTING.md`)

`edition_rules` implements the MECHANICAL subset of your house rules in
code — the deterministic conversions that must happen on every page
without exception (ligature expansion, small-capital flattening). The
POLICY subset — what your project normalizes or preserves, how sections
nest, how footnotes are numbered, when a departure from the print is
deliberate — cannot be code: it is a document.

State it in a versioned file in your project. Structure that works:

1. Scope and provenance of the edition it governs.
2. Orthography rules (mechanical ones marked as such — those belong in
   `edition_rules`-style code too, so the document and the code agree).
3. Structure and sections: hierarchy, how headings are marked, what the
   corpus/platform derives from metadata vs. body text.
4. Footnotes and apparatus: numbering, placement, markers.
5. What the transcriber must NOT do (no silent normalization, no
   conjectural emendation, ...).

## Prompts (one per track, per project)

- **VLM track**: one transcription prompt per edition, describing the
  page anatomy (zones, type sizes, apparatus conventions) and asking for
  NO normalization — deterministic conversions happen in code after.
  Passed to `ex-batch-submit --prompt-file`.
- **OCR track**: a cleanup-pass instruction document per work, given to
  the cleanup subagents. It tells them: what they receive (raw OCR text,
  never the image), what they are responsible for (section nesting,
  footnotes, cleanup — in that order), the house rules to apply, the
  output format (one page file, written immediately), and how to skip
  already-done pages so runs are resumable.

The orchestrating agent composes these from the house-rules document +
the work's structure map; it does not invent rules from thin air.

## Subagents (OCR track)

The OCR pipeline is: scan → OCR engine (macOS Vision or any engine
producing `{filename: text}` JSON) → raw OCR text → cheap LLM cleanup
pass (subagents, one batch of pages each, following the cleanup
instructions) → house-style page files. The skill that orchestrates this
lives in your project's skill collection; exscriptor provides the
mechanisms the skill calls (`ocr_pages_json`, `edition_rules.clean`,
`check_markers`, the witness collation).
