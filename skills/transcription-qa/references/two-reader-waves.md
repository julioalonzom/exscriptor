# Closing the loop in two-reader waves

For a route where disagreements are adjudicated into per-page decision files
(A, B or other) and a separate edit pass applies them. Each item was a real
wave that called itself done too early.

## Proving the decisions landed

- After any re-adjudication, check every re-decided B/other site for its
  words in the page file. Editors may have worked from instruction files
  built before the re-decision; word presence per site is the check, not
  the editor's reply.
- Before dispatching adjudicators, confirm the collation files for the exact
  page range exist and carry sites. A missing input reads as zero
  disagreements to a worker that will report all-clean on nothing.
- Page-boundary metadata (`opens:` comments) tracks body corrections:
  re-check each one the wave's edits touched.
- An editor's note inserted before existing notes shifts their numbers:
  renumber the page's notes and confirm each number is unique. For six notes
  or fewer, small exact-string patches beat a renumber script; after a
  scripted renumber, grep every marker and confirm each body survived (a
  pattern that matches the number and drops the body destroys margin
  labels).

## Reading a decision before applying it

- A B/other with no replacement words is a deletion, usually a margin gloss
  duplicated into running text: confirm the gloss survives as a margin note
  before the running words go.
- A B/other whose `print` field matches A's words contradicts itself (the
  adjudicator confirmed A while labelling B): flip it to A.
- B's words that are a fragment of A's word across a line break (`cones`
  against running `praecones`) suggest a double-read of a hyphen-split
  word: settle it on the image; the joined form stands.
- A print reading that is a real word and nonsense in context is still a
  misprint: a transposition (*casuali* for *causali*, three times in one
  passage on cause), a wrong-but-valid form (*mediate* for *mediante*,
  *quis* for *quia*). The adjudicator rightly reports the ink; the parent
  keeps the correct word with a print note and a ledger row, and flips the
  decision to A so no editor pastes the print's word in. Recurrence in one
  passage is the compositor's habit, not corroboration.
- A certain-error correction needs a witness stronger than one reader's eyes
  (the quoted source; grammar plus a second reader). A lone forensic read
  against a blind reader stays escalated, with the note.
- Expand the marks, not just the letters: a bare `i` is the imperative,
  `.i.` is *id est*. Check for a suspension point before accepting a
  truncated word as the print's spelling: `Calcedonen.` abbreviates
  *Calcedonensem*, and case agreement confirms it.
- Before correcting a citation number, compare the print's biblical
  divisions with modern numbering on citations already verified in the work.
  An isolated deviation (one `Luc. 21` for Lk 22:32 among dozens that match)
  is an error; a systematic offset is the edition's own division and stays.

## Page joins

- A page-final word repeated as the next page's opening is the catchword:
  decide A on both, and record it in the next page's opens metadata.
- A page-final fragment completed as the next page's opening is a
  break-duplication: keep the side carrying the complete word, drop the
  hinge fragment, and ledger the drop. A hyphenated fragment (`multitu-`)
  plus a whole-word opening (`multitudine`) is the certain form; a
  whole-word run-over repeated as the opening needs the image to tell which
  side is the hinge.
- Adjacent pages' join decisions agree with each other. Two adjudicators
  deciding opposite sides independently produce duplications (fragment kept
  on page N, full word inserted on N+1): settle the join as one site on both
  images, then make the losing side's decision file match.
- A fragment at an image edge may be the crop, not the print: a blind reader
  transcribes clipped letters faithfully as a word. Before restoring or
  deleting, check whether the cut is in the image or the print (line starts
  down the half, the OCR witness, the page's other half). The running word
  stands against a cropped fragment, and letters lost to image preparation
  stay lost.
