#!/usr/bin/env python3
"""Witness collation: parse a digital edition's chunked HTML into
per-chapter reference texts and titles.

A digital witness tells you where the transcription deserves a second
look; nothing is ever copied from it into the output — the scanned page
is the source, the witness only adjudicates.

Configuration (env):
  WITNESS_DIR           directory holding the HTML chunks (default: .)
  WITNESS_GLOB          filename pattern; `{lib}` is substituted
  WITNESS_HEADER_REGEX  record-header regex; groups: id, title, liber, caps, tit|n

Legacy CT_* env names are honored as fallbacks.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import typer
from typing_extensions import Annotated

WITNESS_DIR = Path(os.environ.get("WITNESS_DIR") or os.environ.get("CT_DIR") or ".")

# Filename pattern for witness chunk files; override for other editions.
WITNESS_GLOB = os.environ.get("WITNESS_GLOB") or os.environ.get("CT_GLOB") or "scg{lib}???.html"
# Record-header regex; groups: [id, title, liber, caps, tit|n].
WITNESS_HEADER_REGEX = (os.environ.get("WITNESS_HEADER_REGEX")
                        or os.environ.get("CT_HEADER_REGEX")
                        or r"\[(\d+)\] [A-Za-z .']+, lib\. (\d) cap\. ([\d\-]+)\s*(tit|n)\.")

# Backwards-compatible aliases (CT_* names are historical).
CT_DIR = WITNESS_DIR
CT_GLOB = WITNESS_GLOB
CT_HEADER_REGEX = WITNESS_HEADER_REGEX

_TAG = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"\s+")
_REF = re.compile(r"\[\d+\]\s*$")


def _clean(s: str) -> str:
    s = _TAG.sub(" ", s)
    s = s.replace("&nbsp;", " ").replace("&copy;", "©")
    s = _SPACE.sub(" ", s)
    return s.strip()


def load(lib: int) -> dict[int, dict]:
    """Return {cap: {"title": str, "text": str}} for one liber of the witness.

    Some digital editions group several printed chapters under one record
    (a numbering artifact where caps 5 and 6 print as one continuous text,
    for example). Those compound records are split across the member
    chapters: the record's text is attached to the FIRST cap of the group
    and the record dict carries `caps` so callers can collate the joined
    text against the joined gold.
    """
    chapters: dict[int, dict] = {}
    for f in sorted(WITNESS_DIR.glob(WITNESS_GLOB.format(lib=lib))):
        html = f.read_text(encoding="utf-8", errors="replace")
        # split into per-paragraph records: [id] <Title>, lib. L cap. N[-M] tit./n. M <text>
        parts = re.split(WITNESS_HEADER_REGEX, html)
        cur: dict | None = None
        for i in range(1, len(parts), 5):
            if i + 4 >= len(parts):
                break
            cap_s = parts[i + 2]
            kind = parts[i + 3]
            seg = _clean(parts[i + 4])
            if "© 2019" in seg or "Iura omnia asservantur" in seg:
                # trailing copyright line rides on the LAST record of a file —
                # strip it instead of dropping the whole record
                seg = re.split(r"&copy; 2019|© 2019", seg)[0].strip()
                if not seg:
                    continue
            if "-" in cap_s:
                lo, hi = (int(x) for x in cap_s.split("-"))
                caps = list(range(lo, hi + 1))
            else:
                caps = [int(cap_s)]
            cap = caps[0]
            if kind == "tit":
                cur = {"title": seg, "text": "", "caps": caps}
                for c in caps:
                    chapters.setdefault(c, cur)
            elif cap not in chapters:
                # no 'tit' record for this chapter (some chapters start
                # directly at n. 1) — create it on the fly; a later 'tit'
                # record will not clobber it (setdefault semantics)
                cur = {"title": "", "text": seg, "caps": caps}
                for c in caps:
                    chapters.setdefault(c, cur)
            elif cur is not None:
                cur = chapters[cap]
                cur["text"] = (cur["text"] + " " + seg).strip()
    return chapters


def word_set(text: str) -> set[str]:
    return set(re.findall(r"[a-zæ]+", text.lower()))


def collate(ours: str, gold: str) -> dict:
    """Report both-direction word disagreements plus length ratio."""
    ow = set(re.findall(r"[a-zæ]+", ours.lower()))
    gw = word_set(gold)
    only_ours = sorted(ow - gw)
    only_gold = sorted(gw - ow)
    ratio = len(re.findall(r"[a-zæ]+", ours.lower())) / max(1, len(re.findall(r"[a-zæ]+", gold.lower())))
    return {"only_ours": only_ours, "only_gold": only_gold, "ratio": round(ratio, 3)}


def main(
    lib: Annotated[int, typer.Argument(help="Book number the witness chunks are keyed by")] = 1,
):
    """Summarize the witness chapters for one liber."""
    ch = load(lib)
    print(f"liber {lib}: {len(ch)} chapters")
    for c in sorted(ch)[:3]:
        print(f"  cap {c}: {ch[c]['title'][:70]} ({len(ch[c]['text'].split())} words)")


app = typer.Typer()
app.command()(main)


if __name__ == "__main__":
    app()
