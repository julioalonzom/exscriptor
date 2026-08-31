"""Deprecated alias for exscriptor.witness.

`ct_oracle` implied a specific reference work; the witness concept is
work-agnostic. Import from `exscriptor.witness` instead. This shim will
be removed in 1.0.
"""
from exscriptor.witness import (  # noqa: F401
    WITNESS_DIR, WITNESS_GLOB, WITNESS_HEADER_REGEX,
    CT_DIR, CT_GLOB, CT_HEADER_REGEX,
    load, word_set, collate, main,
)
