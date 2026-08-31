# Exscriptor agent guide

## What this repo is

Work-agnostic tooling for agent-assisted digitization of historical
scholarly texts. It carries pipeline PRIMITIVES only:

- `gemini_batch_run` — native Gemini Batch VLM transcription (images
  inline, 15 pages/chunk, resumable job JSON) + OpenRouter batch polling.
- `ocr_layer` — the scan PDF's own text layer as an independent second
  witness.
- `ct_oracle` — digital-witness collation: parse a digital edition's
  chunks, compare word sets, flag where to look harder. A WITNESS, never
  a source.
- `edition_rules` — deterministic conversions (ligatures, small-cap
  flattening) done in code, not prompts.
- `check_markers` — zone-marker / marginalia balance screen.
- `credentials` — env vars or DIGITIZATION_ENV .env; no hardcoded paths.

## The contract with work dirs (scriptorium)

Exscriptor NEVER imports work-specific code and contains no edition
names, work names, or hardcoded paths. Work-specific tooling (prompts,
page anatomy, manifest builders, fixes) lives in the consumer's workbench
and BUILDS ON exscriptor via `pip install exscriptor` (or editable
install). If you find yourself adding an edition name to this repo,
stop — parameterize instead.

## BETA — agents: try it and push fixes back

This library is in beta. Agents using it from a workbench SHOULD:

1. Install: `python3 -m pip install exscriptor` (or, for development,
   `python3 -m pip install -e ~/code/exscriptor`).
2. Notice friction — a missing parameter, a hardcoded default, an
   awkward API, a missing CLI? That is a bug in exscriptor, not
   something to work around in the workbench.
3. Fix it HERE, in this repo, with a test, and commit. Small commits,
   one concern each. Do not fork the logic into the workbench.
4. Report what changed in the commit message; the workbench README
   doesn't need to mirror it.

Workaround-in-workbench is the failure mode this beta exists to catch.
