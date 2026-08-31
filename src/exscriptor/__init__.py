"""exscriptor — tools for digitizing scanned texts.

VLM batch transcription, OCR second witness, digital-witness collation,
deterministic text cleanup, structure screens, credential resolution.

The library is deliberately generic: no work names, no edition names, no
hardcoded paths. Edition-specific tooling (prompts, page anatomy, assembly,
corpus export) belongs in the consumer's own project, built on top of this
library via import or the `ex-*` CLIs.
"""

__version__ = "0.1.0"
