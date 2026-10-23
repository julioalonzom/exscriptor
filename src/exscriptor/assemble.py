#!/usr/bin/env python3
"""Assemble page files into section texts, failing closed on every seam.

One assembler for every work. Per-work assemblers each re-implemented the same
page loop and each rediscovered the same defects: a sentence split into two
paragraphs at a page break, a footnote whose second half became a body
paragraph, a heading welded onto the previous paragraph, an unterminated
comment that published the notes layer, a missing page joined straight across,
the commented author's text published under the commentator's name. Each is
handled here once, and each failure stops the build rather than printing a
warning someone has to notice.

Pipeline, in order:

1. **Load** the page files of a range. A missing page in the range is an
   error (never joined across). Each page's comment layer, markup and line
   structure are checked (``check_markers``); ``<!-- notes: ... -->`` (or a
   template's ``opens`` / ``formatting`` / ``catchword`` / ``folio`` comment)
   comments are harvested into the report and stripped.
2. **Join** the pages. A hyphen at a page's foot joins the word (also across
   an emphasis marker: ``testimo-*`` / ``*nio``); a page that opens on a
   heading starts a paragraph; a page that ends mid-sentence or whose next
   page opens lowercase continues the paragraph; otherwise a paragraph break.
   A page may declare ``joins-next: hyphen|space|para`` in its notes; the
   mechanical decision wins and a disagreement is reported. With
   ``--join-decisions joins.json``, scan-adjudicated decisions win, bound to
   both input page hashes, and any remaining declared mismatch refuses. A
   hyphen decision may set ``printed_hyphen: false`` when the scan confirms
   adjacent fragments with no printed hyphen.
   **Foot notes between the halves:** when a page ends in a run of ``^[...]``
   note blocks and the paragraph continues on the next page, the continuation
   rejoins the paragraph above the notes and the notes follow it (they never
   absorb the continuation's prose). An inline note after a page-final
   hyphen stays with the completed word: ``spiri-^[...]`` / ``tum`` becomes
   ``spiritum^[...]``, retaining note order and word emphasis.
   **Footnote continuations:** a note cut at a page's foot carries
   ``⟦NOTE-CONTINUES⟧`` at the cut, and its continuation on the next page is a
   block opening ``⟦CONTINUED-NOTE⟧``; the continuation is fused into the note.
   An unmatched sentinel is an error.
   Optionally (``--seam-duplets``) a syllable the print repeats on both sides
   of a page break is dropped, and reported.
3. **Drop layers** the project does not publish (``layer_zones``:
   ``<<<NAME>>>`` ... ``<<<END NAME>>>``). Lines matching ``--keep`` patterns
   (the edition's own words caught inside a dropped zone) are hoisted out in
   place and reported.
4. **Edition rules** (optional): a work's ``edition_rules.py`` exposing
   ``edition(text)`` or ``apply(text)``.
5. **Split** into sections by ``structure.json`` (see below). The split is
   checked to round-trip: section bodies plus removed heading lines rebuild
   the assembled text exactly, so nothing is lost or duplicated.
6. **Publish rubrics**: ``^[⟦M⟧⟦R⟧ Summary]`` moves to the owning
   paragraph's start as ``*Summary*.— `` (after a bold paragraph numeral).
   Ordinary marginal notes keep their anchors and lose only the M marker.
   Multiple rubric items stay separate in print order. A directly attached
   ``^[⟦R-NOTE⟧ Editor's note: ...]`` travels with its title; untagged editor
   notes keep their body anchors. Renumber footnotes 1..N across sections
   after removing the rubric notes.
7. **Invariants** per section: non-empty; no sentinel ``⟦...⟧``, ``<<<``,
   ``<!--`` or ``</content>``; no soft hyphen; ``seams.seam_violations`` clean.

structure.json (the TOC, written at scouting before transcription)::

    {
      "headings": {"quaestio": "^\\*\\*QUAESTIO\\b", "articulus": "^\\*\\*ARTICULUS\\b"},
      "title_line": true,            # a bold line after a heading is its title, also removed
      "pre": "prooemium",            # section that owns text before the first heading
      "sections": [{"key": "q1", "type": "quaestio", ...}, ...]
    }

Sections whose ``type`` has a heading pattern are matched to heading lines by
type in document order; a heading that would skip a structure entry is an
error (the heading is missing from the transcription, or the map is wrong).
``"node_types": ["liber", "pars"]`` declares section types that may have no text of
their own (a book or part whose heading is followed at once by its first chapter): an
empty body is then no error and writes no file. ``"implicit_first": {"distinctio": "caput"}`` declares that the first child of
that type has no heading line of its own (a print that opens the first chapter
straight after the distinction's heading): the text after the parent's heading
belongs to that child, and the parent is a node without text. When the child's
heading follows the parent's at once, the child is matched as usual.
A range may cover part of the structure; sections outside it are not
required. Without ``--structure`` the whole range is one text.

Usage:

    python3 -m exscriptor.assemble --pages 'transcription/pg-{n:03d}.md' \\
        --range 12-85 --structure structure.json --out-dir assembled \\
        [--edition-rules edition_rules.py] [--drop-layer THOMAS] \\
        [--keep 'Conclusio\\b[^.\\n]*\\.'] [--seam-duplets]

A scan-adjudicated join file is an object keyed by input page stems::

    {"pg-012->pg-013": {"join": "space", "left_sha256": "...",
      "right_sha256": "...", "evidence": "Flush-left continuation on the scan."}}

For a word split across pages without a printed hyphen, use ``"join":
"hyphen"`` with ``"printed_hyphen": false``. The field is valid only for
hyphen joins and is bound to the same page hashes and evidence as other
decisions.

Use the page hashes reported by ``ASSEMBLY.json``; changed input pages require
fresh adjudication. The decision must match the corrected ``joins-next``
declaration, and its evidence is saved in the new assembly record.

Writes ``<out-dir>/<key>.md`` per section (or ``<out-dir>/assembled.md``) and
``<out-dir>/ASSEMBLY.json`` (pages with sha256, sections, report). Exits 1 on
any failure; nothing is written then.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import typer
from typing_extensions import Annotated

from exscriptor import check_markers, layer_zones, seams

NOTE_CONTINUES = "⟦NOTE-CONTINUES⟧"
CONTINUED_NOTE = "⟦CONTINUED-NOTE⟧"
MARGINAL = "⟦M⟧"   # printed marginal note; optional R role publishes it as a run-in rubric
RUBRIC = "⟦R⟧"
RUBRIC_NOTE = "⟦R-NOTE⟧"
EDITOR_PREFIX = re.compile(r"(?:\d+\.\s*)?Editor['’]s note\b", re.I)
NOTES_COMMENT = re.compile(rf"<!--\s*(?:{'|'.join(check_markers.COMMENT_KEYS)}):\s*(.*?)-->", re.S)
ANY_COMMENT = re.compile(r"<!--.*?-->", re.S)
JOINS = re.compile(r"joins-next:\s*(hyphen|space|para)\b")
FN_ANY = re.compile(r"\^\[(?:\d+\.\s*(?:Editor's note:\s)?|Editor's note:\s)")
TERMINAL = re.compile(r"[.!?…]\s*['\"”’»)\]*_]*\s*$")
LIST_MARK = re.compile(r"[*_]*[a-zα-ωά-ώ]\)[*_]*\s")
RESIDUE = {
    "sentinel ⟦…⟧": re.compile(r"⟦[^⟧]*⟧"),
    "zone marker <<<": re.compile(r"<<<"),
    "HTML comment": re.compile(r"<!--"),
    "wrapper tag": re.compile(r"</?content>"),
    "soft hyphen": re.compile("­"),
}
COMMON_WORDS = {
    "et", "non", "cum", "quam", "quod", "quia", "sed", "ut", "ad", "in", "est",
    "esse", "sunt", "tamen", "enim", "aut", "vel", "nec", "per", "ex", "de",
    "hoc", "haec", "hanc", "hic", "huic", "id", "ita", "sic", "si", "nam", "qui",
    "quae", "que", "etiam", "unde", "ergo", "autem", "atque", "nisi", "quasi",
    "tanquam", "velut", "sicut", "item", "idem",
}


class AssemblyError(Exception):
    """The build refuses: the message lists every reason."""


@dataclass
class Page:
    name: str
    n: int
    path: Path
    body: str
    notes: list[str] = field(default_factory=list)
    declared: str | None = None
    sha256: str = ""


def page_paths(pattern: str, first: int, last: int) -> tuple[list[tuple[int, Path]], list[int]]:
    """(n, path) for each existing page in the range, and the missing numbers.
    ``pattern`` is a format string over ``n``: ``'pages/p{n:03d}.md'``."""
    found, missing = [], []
    for n in range(first, last + 1):
        p = Path(pattern.format(n=n))
        (found.append((n, p)) if p.exists() else missing.append(n))
    return found, missing


def load_page(path: Path, n: int, *, check_wrap: bool = True) -> tuple[Page, list[str]]:
    raw = path.read_text(encoding="utf-8")
    name = path.stem
    problems = check_markers.comment_issues(raw, name) + check_markers.markup_issues(raw, name)
    if check_wrap:
        problems += check_markers.wrap_issues(raw, name)
    notes = [m.group(1).strip() for m in NOTES_COMMENT.finditer(raw)]
    declared = None
    for note in notes:
        m = JOINS.search(note)
        if m:
            declared = m.group(1)
    body = ANY_COMMENT.sub("", raw).strip()
    page = Page(name, n, path, body, notes, declared,
                hashlib.sha256(raw.encode("utf-8")).hexdigest())
    return page, problems


def _first_letter(s: str) -> str:
    for c in s:
        if c.isalpha():
            return c
    return ""


def _trailing_inline_notes(text: str) -> tuple[str, str]:
    """Separate balanced final inline notes, retaining their order and nested brackets."""
    end = boundary = len(text.rstrip())
    while boundary and text[boundary - 1] == "]":
        depth, start = 1, boundary - 2
        while start >= 0 and depth:
            depth += {"]": 1, "[": -1}.get(text[start], 0)
            start -= 1
        if depth or start < 0 or text[start] != "^":
            break
        boundary = start
        while boundary and text[boundary - 1].isspace():
            boundary -= 1
    return text[:boundary].rstrip(), text[boundary:end].lstrip()


def join_kind(prev: str, nxt: str) -> str:
    """'hyphen' | 'space' | 'para' for a page boundary."""
    tail, head = prev.rstrip(), nxt.lstrip()
    if not tail or not head:
        return "para"
    if re.search(r"[A-Za-zÀ-ÿſ]-[*_]*$", _trailing_inline_notes(tail)[0]):
        return "hyphen"
    if head.startswith("#"):
        return "para"
    if head.startswith("**") and not head.startswith("***"):
        first_bold_letter = _first_letter(head[2:])
        if not (first_bold_letter and first_bold_letter.islower()):
            return "para"
    if LIST_MARK.match(head):
        return "para"
    first = _first_letter(head)
    if first and first.islower():
        return "space"
    stripped = re.sub(r"\^\[[^\]]*\]\s*$", "", tail).rstrip() or tail
    # A saint initial belongs to the name continued on the next page.
    if re.search(r"\bS\.$", stripped):
        return "space"
    if not TERMINAL.search(stripped) and not stripped.endswith(":"):
        return "space"
    return "para"


def _seam_duplet(prev: str, nxt: str) -> tuple[str, str | None]:
    """Drop a fragment of 4+ letters the print repeats across the break."""
    tail = re.findall(r"([^\W\d_]{4,})\s*[.,;:]?\s*$", prev.rstrip())
    head = re.match(r"\s*([^\W\d_]{4,})", nxt)
    if tail and head and tail[-1].lower() == head.group(1).lower() \
            and tail[-1].lower() not in COMMON_WORDS:
        return nxt[head.end(1):].lstrip(), head.group(1)
    return nxt, None


def _strip_leading_notes(block: str) -> str:
    """Remove leading ^[...] note spans from a block (bracket-depth aware);
    return the remainder. Notes can contain [...] inside, so scan by depth."""
    s = block.lstrip()
    while s.startswith("^["):
        depth = 0
        i = 0
        for i, c in enumerate(s):
            if c == "[":
                depth += 1
            elif c == "]":
                depth -= 1
                if depth == 0:
                    break
        else:
            return ""  # unbalanced: treat whole block as notes
        s = s[i + 1 :].lstrip()
    return s


def _trailing_notes(text: str) -> tuple[str, str]:
    """Split ``text`` into (body, notes): the maximal run of trailing blocks
    that open ``^[`` (a page's foot apparatus). ``notes`` is empty when the
    text does not end in such a run or is nothing but notes. A trailing
    block that fuses note spans with body prose counts as body, not notes:
    holding it past the next page's continuation would move body text."""
    blocks = re.split(r"\n\s*\n", text.rstrip())
    k = len(blocks)
    while k > 0 and blocks[k - 1].lstrip().startswith("^["):
        if _strip_leading_notes(blocks[k - 1]):
            break
        k -= 1
    if k == 0 or k == len(blocks):
        return text.rstrip(), ""
    return "\n\n".join(blocks[:k]), "\n\n".join(blocks[k:])


def join_pages(pages: list[Page], *, duplets: bool = False,
               join_decisions: dict | None = None) -> tuple[str, list[str], list[str]]:
    """Join page bodies. Returns (text, report lines, errors)."""
    report: list[str] = []
    errors: list[str] = []
    out = ""
    prev: Page | None = None
    for page in pages:
        body = page.body
        blocks = [b.strip() for b in re.split(r"\n\s*\n", body) if b.strip()]
        conts = [i for i, b in enumerate(blocks) if b.startswith(CONTINUED_NOTE)]
        for i in reversed(conts):
            cont = blocks.pop(i)[len(CONTINUED_NOTE):].strip()
            if NOTE_CONTINUES not in out:
                errors.append(f"{page.name}: {CONTINUED_NOTE} with no {NOTE_CONTINUES} before it")
                continue
            cut = out.rfind(NOTE_CONTINUES)
            prefix = out[:cut].rstrip()
            joiner = " "
            if prefix.endswith("-"):
                prefix = prefix[:-1]
                joiner = ""
            rest = out[cut + len(NOTE_CONTINUES):].lstrip(" ")
            # The note has one closing bracket. A transcriber may write it on
            # both halves (after the cut and at the continuation's end): keep the
            # continuation's, drop the duplicate after the cut. A final « ] »
            # that closes a bracket of the continuation's own (« … [Editor's
            # note: …] ») is not the note's.
            if cont.endswith("]") and cont.count("]") > cont.count("[") and rest.startswith("]"):
                rest = rest[1:]
            out = prefix + joiner + cont + rest
            report.append(f"{page.name}: footnote continuation fused into the note on the previous page")
        body = "\n\n".join(blocks)
        if prev is None or not out.strip():
            out = body
            prev = page
            continue
        if duplets:
            body, frag = _seam_duplet(out, body)
            if frag:
                report.append(f"{prev.name}->{page.name}: repeated seam fragment {frag!r} dropped")
        boundary = f"{prev.name}->{page.name}"
        chosen = None
        if join_decisions is not None:
            if not isinstance(join_decisions, dict):
                errors.append("join decisions must be an object keyed by page boundary")
            else:
                decision = join_decisions.get(boundary)
                if boundary in join_decisions:
                    if not isinstance(decision, dict) or decision.get("join") not in ("hyphen", "space", "para"):
                        errors.append(f"{boundary}: invalid join decision")
                    elif "printed_hyphen" in decision and type(decision["printed_hyphen"]) is not bool:
                        errors.append(f"{boundary}: printed_hyphen must be a boolean")
                    elif "printed_hyphen" in decision and decision["join"] != "hyphen":
                        errors.append(f"{boundary}: printed_hyphen is only valid for a hyphen join")
                    elif not isinstance(decision.get("evidence"), str) or not decision["evidence"].strip():
                        errors.append(f"{boundary}: join decision needs evidence")
                    elif not prev.sha256 or not page.sha256 or (
                            decision.get("left_sha256") != prev.sha256 or
                            decision.get("right_sha256") != page.sha256):
                        errors.append(f"{boundary}: stale join decision page hash")
                    elif prev.declared and decision["join"] != prev.declared:
                        errors.append(f"{boundary}: join decision conflicts with declared {prev.declared}")
                    elif decision["join"] == "hyphen" and decision.get("printed_hyphen", True) is False and re.search(
                            r"-[*_]*$", _trailing_inline_notes(_trailing_notes(out)[0])[0]):
                        errors.append(f"{boundary}: printed_hyphen false conflicts with printed trailing hyphen")
                    elif decision["join"] == "hyphen" and decision.get("printed_hyphen", True) is not False and not re.search(
                            r"-[*_]*$", _trailing_inline_notes(_trailing_notes(out)[0])[0]):
                        errors.append(f"{boundary}: hyphen join requires a printed trailing hyphen")
                    else:
                        chosen = decision["join"]
                        report.append(f"{boundary}: adjudicated {chosen}: {decision['evidence']}")
        held = ""
        seam_tail = out
        if not body.lstrip().startswith("^["):
            main, notes = _trailing_notes(out)
            if notes:
                seam_tail = main
            if notes and (chosen or join_kind(main, body)) in ("space", "hyphen"):
                # The page ended in its foot notes and the paragraph goes on
                # on the next page: the continuation rejoins the paragraph
                # above the notes, and the notes follow it.
                out, held = main, notes
                report.append(f"{prev.name}->{page.name}: page-foot notes held until the "
                              f"continued paragraph ends")
        kind = chosen or join_kind(seam_tail, body)
        if re.match(r"<<<", body.lstrip()) or re.match(
                r"^\s*<<<.*>>>\s*$", out.rstrip().rsplit("\n", 1)[-1]):
            # A page that opens on, or follows, a layer-marker line (an omitted
            # plate, a dropped zone): never glue text onto the marker, or the
            # marker stops matching ^...$ and the zone survives the drop.
            if chosen and chosen != "para":
                errors.append(f"{boundary}: join decision cannot glue a layer marker")
            kind = "para"
        tail = out.rstrip()
        rest = ""
        if held:
            body, _, rest = body.lstrip().partition("\n\n")
        if kind == "hyphen":
            tail, inline_notes = _trailing_inline_notes(tail)
            m = re.search(r"-([*_]*)$", tail)
            if m:
                closing = m.group(1)
                tail = tail[:m.start()]
            else:
                # A scan-adjudicated unprinted-hyphen join can still have
                # page-local emphasis delimiters around the joined word.
                m = re.search(r"([*_]+)$", tail)
                closing = m.group(1) if m and body.lstrip().startswith(m.group(1)) else ""
                if closing:
                    tail = tail[:-len(closing)]
            head = body.lstrip()
            if closing and head.startswith(closing):
                head = head[len(closing):]
            if inline_notes:
                fragment = re.match(r"(?:[^\W\d_]|[\u0300-\u036f])+", head)
                if fragment:
                    # A note anchored at the print's split belongs after the whole word.
                    head = head[:fragment.end()] + inline_notes + head[fragment.end():]
                else:
                    errors.append(f"{boundary}: inline-note hyphen needs a word continuation")
                    head = inline_notes + head
            out = tail + head
        elif kind == "space":
            out = tail + " " + body.lstrip()
        else:
            out = tail + "\n\n" + body.lstrip()
        if held:
            out = out + "\n\n" + held + (("\n\n" + rest) if rest else "")
        if prev.declared and prev.declared != kind:
            report.append(f"{boundary}: declared {prev.declared}, joined as {kind}")
            if join_decisions is not None:
                errors.append(f"{boundary}: declared {prev.declared}, inferred {kind}; adjudication required")
        prev = page
    if isinstance(join_decisions, dict):
        boundaries = {f"{a.name}->{b.name}" for a, b in zip(pages, pages[1:])}
        for boundary in join_decisions.keys() - boundaries:
            errors.append(f"unknown join decision boundary: {boundary}")
    if NOTE_CONTINUES in out:
        errors.append(f"{out.count(NOTE_CONTINUES)} {NOTE_CONTINUES} with no continuation on the next page")
    return out, report, errors


_GAP = "\x00GAP\x00"  # placeholder for one dropped zone span


def _gap_zones(text: str, zones: tuple[str, ...]) -> tuple[str, list[str], int]:
    """Replace each balanced marked span with a GAP placeholder line.

    Returns (text, zone names in order, dropped nonblank line count).
    Unbalanced markers are left in place for filter_layers to report.
    """
    markers = [(z, layer_zones._marker_re(z)) for z in zones]
    out: list[str] = []
    gaps: list[str] = []
    buf: list[str] = []
    open_name: str | None = None
    dropped = 0
    for line in text.split("\n"):
        hit = next(((z, m) for z, rx in markers if (m := rx.match(line))), None)
        if hit:
            if hit[1].group("kind"):  # close marker
                if open_name == hit[0]:
                    out.append(_GAP)
                    gaps.append(hit[0])
                    dropped += sum(1 for b in buf if b.strip())
                    buf, open_name = [], None
                else:  # stray close: leave it for filter_layers to report
                    out.extend(buf)
                    buf, open_name = [], None
                    out.append(line)
            elif open_name is None:
                open_name, buf = hit[0], [line]
            else:  # nested open: flush, leave it for filter_layers to report
                out.extend(buf)
                buf, open_name = [line], hit[0]
            continue
        if open_name is None:
            out.append(line)
        else:
            buf.append(line)
    out.extend(buf)  # unclosed span: left in place, reported downstream
    return "\n".join(out), gaps, dropped


def _join_gaps(text: str, gaps: list[str]) -> tuple[str, list[str]]:
    """Join the text around each dropped-zone placeholder with join_kind.

    A dropped zone is transparent: the neighbours join as if adjacent, so a
    sentence running across omitted plates stays one paragraph. Joins are
    reported; paragraph breaks stay breaks.
    """
    parts = text.split(_GAP)
    out = parts[0]
    report: list[str] = []
    for name, following in zip(gaps, parts[1:]):
        kind = join_kind(out, following)
        tail, head = out.rstrip(), following.lstrip()
        if kind == "hyphen":
            m = re.search(r"-([*_]*)$", tail)
            closing = m.group(1) if m else ""
            tail = tail[:m.start()] if m else tail
            if closing and head.startswith(closing):
                head = head[len(closing):]
            out = tail + head
            report.append(f"hyphen-joined across dropped {name}")
        elif kind == "space":
            out = tail + " " + head
            report.append(f"joined across dropped {name}")
        else:
            out = tail + "\n\n" + head
    return out, report


def drop_layers(text: str, zones: tuple[str, ...], keep: tuple[str, ...] = ()) -> tuple[str, list[str], list[str]]:
    """Drop marked zones; lines matching a ``keep`` pattern inside a zone are
    hoisted out in place. Returns (text, report, errors)."""
    if not zones:
        return text, [], []
    keep_res = [re.compile(k) for k in keep]
    hoisted: list[str] = []
    if keep_res:
        lines, open_name = [], None
        markers = [(z, layer_zones._marker_re(z)) for z in zones]
        for line in text.split("\n"):
            hit = next(((z, m) for z, rx in markers if (m := rx.match(line))), None)
            if hit:
                open_name = None if hit[1].group("kind") else hit[0]
                lines.append(line)
                continue
            if open_name:
                found = [m.group(0).strip() for rx in keep_res for m in rx.finditer(line)]
                if found:
                    # close the zone, emit the edition's words, reopen
                    lines += [f"<<<END {open_name}>>>", "", *found, "", f"<<<{open_name}>>>"]
                    hoisted += found
                    rest = line
                    for f in found:
                        rest = rest.replace(f, "")
                    if rest.strip():
                        lines.append(rest)
                    continue
            lines.append(line)
        text = "\n".join(lines)
    text, gaps, n_gap = _gap_zones(text, zones)
    res = layer_zones.filter_layers(text, zones)
    errors = [f"layer markers: {u}" for u in res["unbalanced"]]
    report = [f"dropped {n_gap + len(res['dropped_nonblank'])} lines of {', '.join(zones)}"]
    report += [f"hoisted out of a dropped zone: {h[:70]}" for h in hoisted]
    kept = re.sub(r"\n{3,}", "\n\n", res["kept"])
    kept, joins = _join_gaps(kept, gaps)
    report += joins
    return kept, report, errors


def publish_rubrics(text: str) -> str:
    """Move an explicitly classified marginal rubric to its owning paragraph.

    Each rubric keeps its words and print order. A directly following
    R-NOTE editorial note explicitly belongs to that title and travels with it.
    Nested notes remain unsupported rather than guessing their attachment.
    """
    blocks = re.split(r"(\n\s*\n)", text)
    for index, block in enumerate(blocks):
        if RUBRIC not in block and RUBRIC_NOTE not in block:
            continue
        notes, i = [], 0
        while (i := block.find("^[", i)) >= 0:
            depth, end = 1, i + 2
            while end < len(block) and depth:
                depth += {"[": 1, "]": -1}.get(block[end], 0)
                end += 1
            note = block[i + 2:end - 1] if not depth else block[i + 2:]
            if RUBRIC in note:
                prefix = MARGINAL + RUBRIC
                if depth or not note.startswith(prefix) or "[" in note or "]" in note:
                    raise AssemblyError("rubric: incomplete, nested or misplaced role marker")
                title = note.removeprefix(prefix).strip()
                if title.count("*") % 2 or "⟦" in title or "⟧" in title:
                    raise AssemblyError("rubric: incomplete emphasis or unresolved marker")
                title = title.replace("*", "").strip().removesuffix(".").rstrip()
                if not title:
                    raise AssemblyError("rubric: empty title")
                if EDITOR_PREFIX.match(title):
                    raise AssemblyError("rubric: editorial note is not printed summary text")
                notes.append((i, end, title, ""))
            elif RUBRIC_NOTE in note:
                attached = note.removeprefix(RUBRIC_NOTE).lstrip()
                if (depth or not note.startswith(RUBRIC_NOTE) or "[" in note or "]" in note
                        or not EDITOR_PREFIX.match(attached) or not notes or notes[-1][1] != i):
                    raise AssemblyError("rubric: R-NOTE must directly follow its title and contain an editorial note")
                begin, _, title, attachments = notes[-1]
                notes[-1] = (begin, end, title, attachments + "^[" + attached + "]")
            i = end
        if not notes or block.count(RUBRIC) != len(notes):
            raise AssemblyError("rubric: misplaced role marker")
        body = block
        for begin, end, _, _ in reversed(notes):
            body = body[:begin] + body[end:]
        body = body.strip()
        if not body:
            raise AssemblyError("rubric: no owning paragraph body")
        numeral = re.match(r"\*\*(?:\d+|[IVXLCDM]+)[.]?\*\*(?=\s|\^\[|$)", body)
        at = numeral.end() if numeral else 0
        if numeral:
            # Notes anchored to the numeral must stay attached to it.
            while body.startswith("^[", at):
                depth, at = 1, at + 2
                while at < len(body) and depth:
                    depth += {"[": 1, "]": -1}.get(body[at], 0)
                    at += 1
                if depth:
                    raise AssemblyError("rubric: incomplete note anchored to paragraph numeral")
            while at < len(body) and body[at].isspace():
                at += 1
        prefix = body[:at].rstrip() + " " if at else ""
        titles = "".join(f"*{title}*{attachments}.— " for _, _, title, attachments in notes)
        blocks[index] = prefix + titles + body[at:]
    return "".join(blocks)


def renumber_footnotes(text: str, *, numbered_author_notes: bool = True, start: int = 0) -> str:
    counter = start

    def repl(m: re.Match) -> str:
        nonlocal counter
        counter += 1
        if "Editor's note" in m.group(0):
            return f"^[{counter}. Editor's note: "
        return f"^[{counter}. "

    # With unnumbered author notes, a leading numeral belongs to the citation.
    pattern = FN_ANY if numbered_author_notes else re.compile(r"\^\[(?:\d+\.\s*)?Editor's note:\s*")
    return pattern.sub(repl, text)


def load_edition_rules(path: Path):
    spec = importlib.util.spec_from_file_location(f"edition_rules_{abs(hash(str(path)))}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    fn = getattr(mod, "edition", None) or getattr(mod, "apply", None)
    if fn is None:
        raise AssemblyError(f"{path}: defines neither edition(text) nor apply(text)")
    return fn


def split_sections(text: str, structure: dict) -> tuple[dict[str, str], list[str]]:
    """Cut the text at heading lines matched to structure entries in order.
    Returns ({key: body}, errors). Round-trips by construction and by check."""
    patterns = {t: re.compile(p, re.M) for t, p in (structure.get("headings") or {}).items()}
    if not patterns:
        raise AssemblyError("structure.json has no 'headings' patterns")
    ordered = [s for s in structure["sections"] if s.get("type") in patterns]
    title_line = structure.get("title_line", False)
    heads = []
    for m in re.finditer(r"^.*$", text, re.M):
        line = m.group(0)
        typ = next((t for t, rx in patterns.items() if rx.match(line)), None)
        if typ is None:
            continue
        end = m.end()
        if line.startswith("**"):
            # A page join can glue body text onto a bold heading's line
            # ("**Cap. XXII. ...** lationes ..."). The heading ends at its
            # closing "**"; anything after that is body and must stay in
            # the section, or it is silently lost from the assembly.
            close = line.find("**", 2)
            if close != -1 and line[close + 2 :].strip():
                end = m.start() + close + 2
        if title_line:
            t = re.match(r"\n\s*\n?(\*\*[^\n]+\*\*)[ \t]*(?=\n|$)", text[end:])
            if t:
                end += t.end()
        heads.append((m.start(), end, typ, line.strip()))
    errors: list[str] = []
    out: dict[str, str] = {}
    pieces: list[str] = []
    first = heads[0][0] if heads else len(text)
    pre = text[:first]
    pointer = 0
    if pre.strip():
        key = structure.get("pre")
        if not key:
            errors.append(f"{len(pre.split())} words before the first heading and no 'pre' section")
        else:
            out[key] = pre.strip()
            keys = [s["key"] for s in ordered]
            if key in keys:
                pointer = keys.index(key) + 1
    pieces.append(pre)
    for i, (start, end, typ, label) in enumerate(heads):
        found = next((j for j in range(pointer, len(ordered)) if ordered[j]["type"] == typ), None)
        if found is None:
            errors.append(f"no structure entry left for heading {label[:60]!r}")
            break
        if found > pointer and out:
            skipped = [s["key"] for s in ordered[pointer:found]]
            errors.append(f"heading {label[:60]!r} matched {ordered[found]['key']!r} but skips {skipped}")
        stop = heads[i + 1][0] if i + 1 < len(heads) else len(text)
        key = ordered[found]["key"]
        body = text[end:stop]
        pieces += [text[start:end], body]
        child = ordered[found + 1] if found + 1 < len(ordered) else None
        if (child and body.strip() and child.get("parent") == key
                and child["type"] == (structure.get("implicit_first") or {}).get(typ)):
            # The print gives the first child no heading of its own: the text
            # after the parent's heading is the child's (the parent is a node).
            key, pointer = child["key"], found + 2
        else:
            pointer = found + 1
            if not body.strip() and (typ in (structure.get("implicit_first") or {})
                                     or typ in (structure.get("node_types") or [])
                                     or ordered[found].get("node")):
                continue  # a parent that is only a node: its first child follows at once
        out[key] = (out[key] + "\n\n" if key in out else "") + body.strip()
    if not errors and "".join(pieces) != text:
        errors.append("split does not round-trip: text lost or duplicated")
    return out, errors


def invariants(key: str, body: str, allow_open_tail: bool = False) -> list[str]:
    """Shape defects in one section's text. ``allow_open_tail`` suppresses
    TAIL-TERMINAL: the section is cut by the range, not by the print (see
    ``truncated_tail``)."""
    errs = []
    if not body.strip():
        errs.append(f"{key}: empty section")
    for label, rx in RESIDUE.items():
        n = len(rx.findall(body))
        if n:
            errs.append(f"{key}: {n} × {label}")
    for idx, kind, snip in seams.seam_violations(body):
        if kind == "TAIL-TERMINAL" and allow_open_tail:
            continue
        errs.append(f"{key}: seam {kind} at block {idx}: {snip[:90]!r}")
    return errs


def truncated_tail(sections: dict[str, str], structure: dict | None,
                   pages: list[Page]) -> str | None:
    """The last section key the range cuts in the middle, if any.

    Wave-by-wave reading assembles a growing prefix: the range then ends
    inside a section, and that section's text stops mid-sentence because the
    pages after it are not read yet — not because the print stops there. Two
    measured signals say so, and either is enough:

    - the range's last page declares ``joins-next: space`` or ``hyphen``: it
      hands its paragraph to a page the range does not have; and
    - the structure's ``printed_end`` for that section lies beyond the range's
      last page.

    At the end of a whole work neither holds, so the open-tail check is not
    weakened: a section that runs past the last read page is never the last
    section of the work.
    """
    if not sections or not pages:
        return None
    last = max(pages, key=lambda p: p.n)
    key = list(sections)[-1]
    if (last.declared or "").strip().lower() in ("space", "hyphen"):
        return key
    if structure:
        by_key = {s["key"]: s for s in structure.get("sections", []) if "key" in s}
        end = by_key.get(key, {}).get("printed_end")
        if isinstance(end, int) and end > last.n:
            return key
    return None


@dataclass
class Assembly:
    sections: dict[str, str]
    pages: list[Page]
    report: list[str]
    errors: list[str]
    # the last section the range cut in the middle, whose open tail is not a
    # defect (None when the range ends where the structure says a section ends)
    truncated_tail: str | None = None


def assemble(pages: list[Page], *, structure: dict | None = None, zones: tuple[str, ...] = (),
             keep: tuple[str, ...] = (), edition=None, duplets: bool = False,
             numbered_author_notes: bool = True, join_decisions: dict | None = None) -> Assembly:
    text, report, errors = join_pages(pages, duplets=duplets, join_decisions=join_decisions)
    text, r, e = drop_layers(text, zones, keep)
    report += r
    errors += e
    if edition is not None:
        text = edition(text)
    text = re.sub(r"(?m)([ \t]+)\n", lambda m: m[0] if m[1].endswith("  ") else "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"
    if structure:
        sections, e = split_sections(text, structure)
        errors += e
    else:
        sections = {"assembled": text.strip()}
    cut = truncated_tail(sections, structure, pages)
    note_count = 0
    for key, body in sections.items():
        try:
            body = publish_rubrics(body)
        except AssemblyError as exc:
            errors.append(f"{key}: {exc}")
        body = re.sub(r"\^\[" + MARGINAL + r"\s*", "^[", body)
        body = renumber_footnotes(body, numbered_author_notes=numbered_author_notes, start=note_count)
        note_count += len(FN_ANY.findall(body)) if numbered_author_notes else len(
            re.findall(r"\^\[\d+\. Editor's note: ", body))
        sections[key] = body
        errors += invariants(key, body, allow_open_tail=(key == cut))
    return Assembly(sections, pages, report, errors, cut)


def parse_range(spec: str) -> tuple[int, int]:
    a, _, b = spec.partition("-")
    return int(a), int(b or a)


def main(
    pages: Annotated[str, typer.Option(help="Page path pattern over n, e.g. 'transcription/pg-{n:03d}.md'")],
    range_: Annotated[str, typer.Option("--range", help="First-last page number, e.g. 12-85")],
    out_dir: Annotated[Path, typer.Option(help="Directory for section files and ASSEMBLY.json")],
    structure: Annotated[Path | None, typer.Option(help="structure.json (TOC with heading patterns)")] = None,
    edition_rules: Annotated[Path | None, typer.Option(help="Python file exposing edition(text)")] = None,
    drop_layer: Annotated[list[str], typer.Option(help="Zone name to drop (repeatable)")] = None,
    keep: Annotated[list[str], typer.Option(help="Regex of edition text to hoist out of dropped zones")] = None,
    seam_duplets: Annotated[bool, typer.Option(help="Drop a fragment repeated across a page break")] = False,
    unnumbered_author_notes: Annotated[bool, typer.Option(help="Preserve leading citation numerals; renumber only editor notes")] = False,
    no_wrap_check: Annotated[bool, typer.Option(help="Skip the hard-wrap check (verse, tables)")] = False,
    join_decisions: Annotated[Path | None, typer.Option(help="Hash-bound scan join decisions; refuse unadjudicated declared mismatches")] = None,
):
    """Assemble page files into section texts; refuse on any seam or shape defect."""
    first, last = parse_range(range_)
    found, missing = page_paths(pages, first, last)
    errors = [f"missing page {n}: {pages.format(n=n)}" for n in missing]
    loaded = []
    for n, p in found:
        page, problems = load_page(p, n, check_wrap=not no_wrap_check)
        loaded.append(page)
        errors += problems
    if not loaded:
        errors.append("no page files in range")
    result = None
    decisions = None
    if join_decisions is not None:
        try:
            decisions = json.loads(join_decisions.read_text(encoding="utf-8"))
            if not isinstance(decisions, dict):
                errors.append("join decisions must be an object keyed by page boundary")
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"invalid join decisions: {exc}")
    if not errors:
        try:
            result = assemble(
                loaded,
                structure=json.loads(structure.read_text(encoding="utf-8")) if structure else None,
                zones=tuple(drop_layer or ()), keep=tuple(keep or ()),
                edition=load_edition_rules(edition_rules) if edition_rules else None,
                duplets=seam_duplets, numbered_author_notes=not unnumbered_author_notes,
                join_decisions=decisions)
        except AssemblyError as exc:
            errors.append(str(exc))
        else:
            errors += result.errors
    if result:
        for line in result.report:
            print("  ", line)
        for page in result.pages:
            for note in page.notes:
                print(f"   note {page.name}: {note[:110]}")
    if errors:
        print(f"ASSEMBLY REFUSED: {len(errors)} problem(s)")
        for e in errors:
            print("  ", e)
        raise typer.Exit(1)
    out_dir.mkdir(parents=True, exist_ok=True)
    for key, body in result.sections.items():
        (out_dir / f"{key}.md").write_text(body.strip() + "\n", encoding="utf-8")
    record = {
        "pages": [{"name": p.name, "path": str(p.path), "sha256": p.sha256} for p in result.pages],
        "sections": {k: {"words": len(v.split()),
                         "sha256": hashlib.sha256(v.strip().encode("utf-8")).hexdigest()}
                     for k, v in result.sections.items()},
        "report": result.report,
    }
    if result.truncated_tail:
        record["truncated_tail"] = result.truncated_tail
    if join_decisions is not None:
        record["join_decisions"] = decisions
    (out_dir / "ASSEMBLY.json").write_text(json.dumps(record, ensure_ascii=False, indent=1) + "\n",
                                           encoding="utf-8")
    words = sum(s["words"] for s in record["sections"].values())
    print(f"assembled {len(result.pages)} pages -> {len(result.sections)} section(s), {words} words -> {out_dir}")
    if result.truncated_tail:
        print(f"note: the range ends inside '{result.truncated_tail}': its open tail is "
              f"the range's edge (its last page hands the text on, or the structure "
              f"puts the section's end beyond page {max(p.n for p in result.pages)})")


app = typer.Typer(add_completion=False)
app.command()(main)


if __name__ == "__main__":
    app()
