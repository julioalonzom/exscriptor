"""schola_digitization — shared pipeline library for text digitization.

Everything here is work-agnostic: VLM transcription (OpenRouter sync + native
Gemini Batch), the scan's own OCR as second witness, CT collation, zone/sea
assembler primitives, edition rules, and batch job management.

Per-work code (prompts, page anatomy, manifest builders, one-off fixes) lives
under works/<work>/, NOT here. A work dir may import this package; this
package must never import from a work dir.
"""

__version__ = "0.1.0"
