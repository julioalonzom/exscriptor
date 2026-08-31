#!/usr/bin/env python3
"""Deterministic conversions the transcription prompt used to ask for.

The Leonine is a critical edition and needs no orthographic policy of the
kind the Banez print required — it is internally consistent and already
writes `i` for consonantal `j`. What it does need is the pair of
conversions that used to sit in `prompt.py` and were moved here after the
Banez benchmark showed that stating a deterministic substitution in a
prompt costs accuracy without buying obedience:

  LIGATURES        æ/œ as printed -> ae/oe.
  SMALL CAPITALS   copied as CAPITALS -> ordinary capitalization.

Both are applied on the way in, by the transcriber's `clean()`, so the
per-page files keep the shape the pilot's twenty-four pages already have
and `assemble.py` sees one format rather than two.

The small-capital flattener is the reason this file exists. The print sets
the scholastic argument markers in small caps — AD PRIMUM SIC PROCEDITUR,
PRAETEREA, SED CONTRA, RESPONDEO DICENDUM, AD PRIMUM ERGO DICENDUM — and
they are the article's skeleton, the thing a reader scans. They are not a
closed set to match against, though: this edition small-caps whatever it
pleases, so the rule is structural rather than a word list.

Three things must survive it, and each is why a naive `.title()` is wrong:

  * Roman numerals (I, IV, XIV, LII) are capitals that stay capitals.
  * Manuscript sigla (ACDEFG, PEab, sF, DEGpCF) are capitals that are not
    words at all — so the apparatus and marginalia blocks are never
    touched, only the author (THOMAS) and commentator (CAIETANUS) zones.
  * Headings (QUAESTIO SECUNDA, UTRUM DEUM ESSE SIT PER SE NOTUM) are
    genuinely set in full capitals and are emitted as whole bold or italic
    lines — so a line that is entirely emphasized is skipped.
"""

from __future__ import annotations

import re

LIGATURES = {"æ": "ae", "Æ": "Ae", "œ": "oe", "Œ": "Oe"}

# The apparatus keys the model sometimes writes as LaTeX. It is asked for the
# printed Greek letter and mostly gives it, but a page now and then comes back
# with `[$\beta$]` for `[β]` — which every downstream tool then reads as the
# word "beta" standing in the text. That surfaced as two permanent
# `ct_witness.py` sites in QQ XIV-XV: not a reading, not an error anyone could
# act on, and exactly the kind of residue that teaches people to skim a report.
# Deterministic, so it belongs here rather than in the prompt.
_LATEX_GREEK = re.compile(r"\[\$\\([a-zA-Z]+)\$\]")
_GREEK_NAMES = {
    name: chr(code)
    for code, name in enumerate(
        [
            "alpha",
            "beta",
            "gamma",
            "delta",
            "epsilon",
            "zeta",
            "eta",
            "theta",
            "iota",
            "kappa",
            "lambda",
            "mu",
            "nu",
            "xi",
            "omicron",
            "pi",
            "rho",
            "finalsigma",
            "sigma",
            "tau",
            "upsilon",
            "phi",
            "chi",
            "psi",
            "omega",
        ],
        start=0x3B1,
    )
}


def expand_latex_greek(text: str) -> str:
    """`[$\\beta$]` -> `[β]`, leaving anything unrecognized alone."""
    return _LATEX_GREEK.sub(
        lambda m: (
            f"[{_GREEK_NAMES[m.group(1).lower()]}]"
            if m.group(1).lower() in _GREEK_NAMES
            else m.group(0)
        ),
        text,
    )


# The consonantal `j` this edition does not use. Every `j` in a Latin word
# is the transcriber modernizing: the volume's own OCR layer carries 1171
# `obiect`/`subiect` and not one `object`/`subject`, so there is nothing to
# arbitrate and no page this can be wrong about.
#
# Deterministic, and therefore here rather than in a prompt — the Bañez
# benchmark showed that stating a substitution to a model costs accuracy
# without buying obedience. It is the same class of rule as æ -> ae. Forty-six
# words had already reached `transcription/` across twenty pages, thirty-eight
# of them published, before anything looked (PAPERCUTS G9).
#
# In a WORD, and Latin has no one-letter words. The lone `j` this therefore
# refuses to touch is an apparatus siglum — a `[j]` in the text, a `j)`
# opening its note — and the volume keys ten or more variants on a page, so
# `j` and `i` are both live. Rewriting the tenth key to the ninth's letter
# collides two notes into one and reads, to every screen downstream, as a
# page that simply has one note fewer.
_CONSONANTAL_J = re.compile(r"\b([A-Za-z]*)j([A-Za-z]*)\b")


def latinize_j(text: str) -> str:
    """`obiectum` for the transcriber's `objectum`, `maior` for `Major`."""
    return _CONSONANTAL_J.sub(
        lambda m: (
            f"{m.group(1)}i{m.group(2)}" if m.group(1) or m.group(2) else m.group(0)
        ),
        text,
    )


# Blocks whose capitals are data, not typography: sigla and reference
# abbreviations live here and must be left exactly as transcribed.
# Zone names this edition family uses: AUTHOR = the edited text,
# COMMENTATOR = the surrounding commentary. Override DIGITIZE_ZONES="A,B"
# for other editions (same convention as check_markers).
AUTHOR_ZONE = "THOMAS"
COMMENTATOR_ZONE = "CAIETANUS"

VERBATIM_BLOCKS = {
    f"{AUTHOR_ZONE}-APPARATUS",
    f"{AUTHOR_ZONE}-MARGINALIA",
    f"{COMMENTATOR_ZONE}-MARGINALIA",
}

_BLOCK = re.compile(r"^<<<([A-Z-]+)>>>$", re.MULTILINE)

# A line that is nothing but one emphasized span: a heading, already
# styled, and set in real capitals by the printer.
_WHOLE_LINE_EMPHASIS = re.compile(r"^\s*(\*{1,2})[^*].*\1\s*$")

_ROMAN = re.compile(r"^[IVXLCDM]+$")

# Sentinels the assembler keys on, which happen to be spelled in capitals.
# `PARALLELA:` prefixes the parallel-places line and `assemble.py` matches it
# case-sensitively; flattening it to `Parallela:` silently drops every
# cross-work citation on the page.
PROTECTED = {"PARALLELA"}

# One or more capitalized tokens in a row. `[A-Z]{2,}` rather than
# `[A-Z]+`: a lone capital is an initial (`A.`, `S. Th.`), not small caps.
_CAPS_RUN = re.compile(r"\b[A-Z]{2,}\b(?:[ ,]+\b[A-Z]{2,}\b)*")


# A hyphen the printer used to break a word across a line, left behind
# because the reader kept the print's line break instead of reflowing the
# paragraph. Inside a paragraph the transcription is one line per paragraph,
# so a newline directly after a hyphen between two lowercase letters can
# only be the print's line-breaking hyphen: no Latin word in this edition
# carries a medial hyphen, and the apparatus's lemma dash is a spaced « – ».
# PDF 101 shipped 19 of these (`Avi-\ncenna`, `dupli-\nciter`, `effe-\nctus`)
# and they surfaced as fragment-shaped one-off words in `hapax_typos.py`.
#
# The newline may be a BLANK line. A reader who meets the break where the
# print changes column sometimes takes it for a paragraph boundary and
# leaves an empty line inside the word — PDF 157 had `intellec-\n\ntus`,
# which reached the assembled article as the two words « intellec- » and
# « tus » and was caught only by the Corpus Thomisticum collation. Crossing
# the blank line is safe rather than a special case: **a word ending in a
# hyphen never ends a paragraph**, so wherever this pattern matches, the two
# halves belong together no matter how much whitespace the reader inserted.
_BROKEN_WORD = re.compile(r"([a-zæœ])-\n\s*\n?[ \t]*([a-zæœ])")


def join_broken_words(text: str) -> str:
    return _BROKEN_WORD.sub(r"\1\2", text)


_CLOSING_MARKER = re.compile(r"^<{2,3}/[A-Za-z-]+>>>[ \t]*\n?", re.MULTILINE)


def drop_closing_markers(text: str) -> str:
    """Delete XML-style closing markers a reader invented.

    The page prompt asks for `<<<THOMAS>>>` as an opening delimiter and
    never closes a zone, but a model that has seen a lot of XML sometimes
    supplies `<<</Thomas>>>` anyway — qwen did it on one page in 82.

    It has to be deleted rather than tolerated, and the reason is that
    nothing downstream can see it. `_BLOCK` and every sibling pattern match
    `<<<NAME>>>` with an uppercase name, so a closing marker is not a
    marker to any of them; it is simply a line of body text, and it would
    ride through promotion into the assembled section and out to a reader.
    Deterministic and exact — this edition prints no such string — so it
    belongs here rather than in the prompt, where it would be one more rule
    a model may or may not follow.
    """
    return _CLOSING_MARKER.sub("", text)


def expand_ligatures(text: str) -> str:
    for src, dst in LIGATURES.items():
        text = text.replace(src, dst)
    return text


def _flatten_run(match: re.Match[str]) -> str:
    run = match.group(0)
    parts = re.split(r"([ ,]+)", run)
    words = parts[::2]
    # A run that is only Roman numerals is a citation, not emphasis.
    if all(_ROMAN.match(w) for w in words):
        return run
    if any(w in PROTECTED for w in words):
        return run
    out: list[str] = []
    seen_word = False
    for i, part in enumerate(parts):
        # Separators pass through, and so do Roman numerals inside a run:
        # « SED CONTRA, ut patet in I Poster. » keeps its I.
        if i % 2 or _ROMAN.match(part):
            out.append(part)
            continue
        out.append(part.capitalize() if not seen_word else part.lower())
        seen_word = True
    return "".join(out)


def flatten_small_caps(text: str) -> str:
    """Sentence-case runs of capitals in a body block.

    The first word of a run is capitalized and the rest lowercased. In this
    edition every small-capital run in the body opens a sentence — the
    argument markers do, and so does the drop-cap word that begins a
    paragraph (QUIA igitur ... -> Quia igitur ...) — so the rule needs no
    look-behind, which is what makes it safe to apply to text a model
    produced rather than to text whose structure we control.
    """
    out = []
    for line in text.split("\n"):
        if not _WHOLE_LINE_EMPHASIS.match(line):
            line = _CAPS_RUN.sub(_flatten_run, line)
        out.append(line)
    return "\n".join(out)


# `[*3]` in a body block, and the note line `*3 Vers. 6.` that answers it.
# The note key is also accepted in bracketed form, which the model emits
# about half the time, having just written the marker that way in the text.
_STAR_MARKER = re.compile(r"\[\*(\d+)\]")
_STAR_NOTE = re.compile(r"^\[?\*(\d+)\]?[ \t]+", re.MULTILINE)


def strip_orphan_italics(block: str) -> str:
    """Drop a leading `*` that opens an emphasis the note never closes.

    The page keys each marginal reference with a printed asterisk, and on
    one page in this range the model copied that asterisk into the note
    body as well as using it as the key. It survives everything downstream
    — it is not a misreading, the marker check counts keys and not
    asterisks — and lands in the reader as `^[*Vers. 21.]`, ten times on
    the page.

    Balanced asterisks are real italics (`*De Fide Orth.*, cap. I, III.`)
    and are left alone; only an odd count with a leading `*` is an orphan.
    """
    out = []
    for line in block.split("\n"):
        m = re.match(r"^(\*\d+[ \t]+)\*(?!\*)(.*)$", line)
        if m and (m.group(2).count("*") % 2 == 0):
            line = m.group(1) + m.group(2)
        out.append(line)
    return "\n".join(out)


def split_notes(block: str) -> list[tuple[str, str]]:
    """The note block as (text, key) pairs, in the order the margin lists them."""
    marks = list(_STAR_NOTE.finditer(block))
    if not marks:
        return []
    ends = [m.start() for m in marks[1:]] + [len(block)]
    return [
        (block[m.end() : end], m.group(1)) for m, end in zip(marks, ends, strict=True)
    ]


def renumber_marginalia(zones: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Renumber each zone's `[*N]` keys 1..n in reading order.

    Takes an ORDERED LIST of (label, body), not a dict: a page can print the
    same zone twice — Cajetan's overrun at the top, a new article beneath —
    and a dict silently keeps only the last of them. Numbering runs once per
    zone across all its stretches in printed order, because the printer's
    `*`/`**` sequence runs down the whole page and not down each stretch.

    The numbers are ours, not the printer's — the page keys its marginal
    references with `*` and `**`, which say *this one, then the next* and
    carry no arithmetic. The prompt asks for one sequence per zone per page,
    and the model instead restarts it at each ARTICULUS heading, so a page
    can hold two `[*1]`s and the marker check pairs a note with the wrong
    reference.

    **The numbers are the pairing, wherever they are usable.** An earlier
    version renumbered the markers by their order in the body and the notes
    by their order in the margin, *independently*, which silently assumes
    the Nth marker in reading order is the Nth note down the margin. That is
    false whenever the print's margin order differs from the order the two
    columns reference it, and PDF 28 is such a page: the body reads
    « ut alibi[*12] ipse dicere videtur » before « quoad secundum praecipue
    punctum[*11] », and those pairings are right — *alibi* takes the
    *Sentences* citation and *punctum* takes « Cf. num. seq. ». Renumbering
    positionally exchanged them.

    That old version defended itself by noting it "preserves the COUNT on
    each side, which is what `check_markers.py` compares". That is exactly
    why the damage was invisible: swapping two notes preserves every count,
    so the one screen that looks at marginalia had nothing to report. An
    argument that a transformation cannot break a *check* is not an argument
    that it cannot break the *data*.

    So: when the model's own numbers are unique they carry the pairing and
    are honoured — the markers are renumbered into reading order and each
    note travels with its marker. Only when they repeat, which is the fault
    this function exists for (the model restarts at `[*1]` under each
    ARTICULUS heading, leaving two `[*1]`s on one page), is there no pairing
    left to preserve and position is all the information there is.
    """
    out = list(zones)
    for zone in (AUTHOR_ZONE, COMMENTATOR_ZONE):
        notes = f"{zone}-MARGINALIA"
        body_at = [i for i, (label, _) in enumerate(out) if label == zone]
        note_at = [i for i, (label, _) in enumerate(out) if label == notes]
        if not body_at or not note_at:
            continue

        keys = [k for i in body_at for k in _STAR_MARKER.findall(out[i][1])]
        note_bodies = [m for i in note_at for m in _STAR_NOTE.finditer(out[i][1])]
        listed = [key for i in note_at for _, key in split_notes(out[i][1])]
        by_key = {}
        for i in note_at:
            for piece, key in split_notes(out[i][1]):
                by_key.setdefault(key, piece)

        # Nothing to fix: the markers already read 1..n in order and the
        # margin lists the notes the same way. Return the page untouched
        # rather than reformatted — a normalizer that rewrites what is
        # already right is indistinguishable from one that breaks it, and
        # every promoted page has to stay a fixed point of this function
        # (PAPERCUTS C6).
        want = [str(n) for n in range(1, len(keys) + 1)]
        if keys == want and listed == want:
            continue

        unique = len(set(keys)) == len(keys)
        # The notes' own keys must be unique too, and across every block of
        # the zone — `by_key` is built with `setdefault`, so two notes keyed
        # `*1` in two stretches of one zone collapse into one and the second
        # is DELETED by the rebuild below. Comparing sets hid it: dropping a
        # duplicate key changes no set. PDF 271 lost « S. Th. lect. X. » this
        # way, and only `promote.py`'s note guard noticed.
        bijection = (
            unique and len(set(listed)) == len(listed) and set(keys) == set(by_key)
        )

        if unique and not bijection:
            # Markers and notes do not correspond: one side has a member the
            # other lacks. That is a genuine fault and `check_markers.py`
            # exists to report it — so leave the zone exactly as transcribed
            # and let it be reported. Renumbering here would either invent a
            # pairing that the page does not support or, as a first version
            # of this did, quietly drop the unpaired note's key and take its
            # text with it into the margin as anonymous prose.
            continue

        body_seq = iter(range(1, len(keys) + 1))
        for i in body_at:
            body = _STAR_MARKER.sub(lambda _: f"[*{next(body_seq)}]", out[i][1])
            out[i] = (zone, body)

        if bijection:
            # Rebuild the note block in the markers' reading order, each note
            # keeping the text it was already attached to.
            body = "\n" + "\n".join(
                f"*{n} {by_key[key].strip()}" for n, key in enumerate(keys, 1)
            )
            out[note_at[0]] = (notes, strip_orphan_italics(body + "\n"))
            for i in note_at[1:]:
                out[i] = (notes, "\n")
        else:
            note_seq = iter(range(1, len(note_bodies) + 1))
            for i in note_at:
                body = _STAR_NOTE.sub(lambda _: f"*{next(note_seq)} ", out[i][1])
                out[i] = (notes, strip_orphan_italics(body))
    return out


def apply(text: str) -> str:
    """Normalize a transcribed page, block by block."""
    text = latinize_j(expand_latex_greek(text))
    text = drop_closing_markers(join_broken_words(expand_ligatures(text)))

    pieces = _BLOCK.split(text)
    # split() yields [before, name, body, name, body, ...]; a page that is
    # somehow blockless is treated as body, which is the safe default.
    if len(pieces) == 1:
        return flatten_small_caps(text)

    # An ordered list, never a dict keyed by label. A page whose Cajetan
    # commentary overruns the previous article prints CAIETANUS, THOMAS,
    # CAIETANUS — and keying by label deleted the first stretch and emitted
    # the second one twice. That is the same defect fixed in
    # `assemble.py:split_blocks`; this copy of it survived because the page
    # prompt used to ask for each marker exactly once, so no page ever had a
    # repeated label to trip it. Changing the prompt armed it.
    zones = [
        (name, body if name in VERBATIM_BLOCKS else flatten_small_caps(body))
        for name, body in zip(pieces[1::2], pieces[2::2], strict=True)
    ]
    zones = renumber_marginalia(zones)

    out = [pieces[0]]
    for name, body in zones:
        out.append(f"<<<{name}>>>")
        out.append(body)
    return "".join(out)
