# Exscriptor agent guide

## What this repo is

Generic tooling for digitizing scanned texts: batch VLM transcription,
OCR second witness, witness collation, deterministic cleanup, structure
screens, credential resolution. See README.md for usage.

The library contains no edition-specific logic: no work names, no
publisher names, no hardcoded paths. Anything edition-specific belongs in
the consumer's own project, built on top of this library. If a change
would require naming a specific work or edition here, parameterize
instead.

## For agents working with this library

1. Install: `pip install git+https://github.com/julioalonzom/exscriptor.git`
   (or a local clone, editable).
2. If something is missing, hardcoded, or awkward for your use case, that
   is a bug in this library — fix it here with a test, commit, and push.
   Do not copy-and-patch the logic into your own project; that fork is
   exactly what this library exists to avoid.
3. Keep the work-agnostic rule above when you change things.
4. Commit messages should say what changed and why; small, one-concern
   commits.
