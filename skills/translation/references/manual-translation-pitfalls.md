# Manual translation — durable pitfalls 
Always-on rules (mechanism + one-line why; no dates, no session IDs, no quoted user text as content; quote ONLY when the quote IS the rule).

## Manual (no-subagent) path — primary when billing dies / user insists / child fails
When `subprocess.CalledProcessError` on tesseract (`leptonica failed to open locally with tail`), `HTTP 402 Insufficient Balance`, or user says `"just me"`: same contract. Count LA FIRST (`[b for b in q.split("\n\n") if b.strip()]`), verify EN=LA before ANY write, same register (`Prob.`→`Proof`, `Resp.`→`Answer`, `nego`→`I deny`, `«...»` kept, `^[...]` at exact position with translated prose inside, citation forms `D. Tho.`/`lib.`/`cap.` in print form, glossary consistent). Latin never edited. Real doubts flagged in `ledger/*.ledger.md` (`latin-apparently-wrong`, `latin-dubious`, `translation-difficult`) with quoted LA + evidence + `retained`/`retained-as-printed`/`unresolved`. If full prose for a large range isn't produced, render each block faithfully, keep 1:1, record `open — full prose pending`. Mechanism: a placeholder passes count gates but reaches staging silently because no fidelity gate reads content; only a real-file read (`grep '[Block'`, `len > ~5× source`) detects it.

## Block-level recovery assembly — when full-file concatenation fails
When variable reset, truncation, or an abbreviation leaks (`[Block 13: ...]`), build verified per-block files (`blk13.md` ... `blk57.md`), verify each (`len > source-block-scale`, `"[Block"` false, `"... summary"` false), concatenate ONLY after all pass, then verify assembled file (`len` ≈ sum, `"[Block"` false, `"END OF ARTICLE"` present). Mechanism: each intermediate is recoverable; a truncated concatenation corrupts irreversibly.

## No fabricated blocks — brief count ≠ file count
When brief claims 58 and `la/` verifies 57 (e.g. `quaestio-3-articulus-4-utrum-in-deo-sit-idem-essentia-et-esse.part1of3.md`), translate the file (57 EN = 57 LA), never invent the 58th. Document discrepancy in ledger (`retained` — file authoritative), mark `open` any decision that needs it. Mechanism: fabricated block has no source evidence and reaches staging silently.

## Older-edition witness (before any repair or `unresolved`)
Query `older-editions/find_in_older.py` against `banez-1584-rome-djvu.txt` (coarse 16th-c. OCR: `f`/`ſ` → long-s, `ae`/`x` → æ, j/i unseparated) before calling a reading a 1934 compositor slip. Agreement = `retained-as-printed`; disagreement = 1934 variant recorded in ledger; never silently substitute. Read page image at archive.org hit. Document edition/year/leaf. Mechanism: the 1934 Urbano is a reprint with compositor errors; the 1584 Rome is the authoritative older witness.

## False-alarm embedded-author screen (`SUMMA` ≠ `RESPONDEO` body)
`SUMMA ARTICULI` is Bañez's correct commentary head; the embedded-article DEFECT requires `RESPONDEO dicendum` / article-style `PROBATVR` blocks embedded under Bañez's name with misplaced head. Always confirm `RESPONDEO dicendum` is actually present (not just `SUMMA`) before calling repair needed; confirm with older-edition witness. Mechanism: false alarm → destructive live deletion of real Bañez text.

## `/tmp` + tesseract environment trap
Tesseract on this host cannot read `/tmp` PNG (`leptonica failed to open`) but reads same file under `$HOME` or via `pdftoppm -png ... | tesseract stdin stdout -l lat --psm 3`. Use stdin route (preferred, no temp files) or home-dir copy. Mechanism: `/tmp` filesystem boundary with tesseract's file-open layer. Never conclude "tesseract broken" — it's the path.

## Concurrent-edit partition (5a word + 5S structure on same pages)
Run word-level adjudication and structural repair in sequence or on disjoint ranges; never same pages simultaneously. Mechanism: two rounds on same file = second writer clobbers first's structural changes silently; the gate screen in SKILL.md enforces this.

## No summaries — user correction overrides any brief
User correction 2026-09-11: `"no one asked for a summary. i asked for a scholarly translation"`. EN file must contain real scholarly prose per block. A placeholder line (`[Block N: ...]`) is failure, not stage. If a range cannot have full prose, render faithfully per block and document `open` in ledger — never fabricate prose or a fabricated block.

