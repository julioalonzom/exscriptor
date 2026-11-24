#!/usr/bin/env python3
"""Gate a reader's page readings before they become page files.

Every check is mechanical: a page passes, or it names what is wrong. A
weak agent never judges a page by reading it: it runs this, re-reads a
refused page with the reasons, and sends a page refused twice to
adjudication with the messages.

    python3 -m exscriptor.page_gate check works/<w> --run runs/read --pages 326-646 [--promote]
    python3 -m exscriptor.page_gate reread works/<w> --run runs/read --prompt-file works/<w>/reader-prompt.txt \\
        --model models/<name> --thinking <supported-level> [--max-attempts 2]

``check`` repairs what is mechanical (a stray glyph of another script, an
italic carried over a line break, a code fence around the page), checks the
rest, and writes ``<run>/gate.json`` ({page: [problems]}). ``--promote``
copies each passing page to the work's page-file directory, never over an
existing page file: once promoted, the page file is the source of truth and
fixes are edits. ``--title-after REGEX`` names heading lines (whole bold
lines) whose title must follow as one bold line, as the assembler takes it.

``reread`` reads each refused page again (synchronous API, a handful of
pages), with the gate's messages appended to the prompt and never the
refused text, so the reader reads the image again. The refused reading moves
to ``<run>/failed/pg-NNN.vK.md``. Paid route: ``--model`` is required, on a
job the owner authorized.
"""
from __future__ import annotations

import base64
import json
import re
import subprocess
import unicodedata
from pathlib import Path

import typer
from typing_extensions import Annotated

from exscriptor import check_markers as cm

app = typer.Typer(add_completion=False, help=__doc__)

OCR_BAND = (0.80, 1.20)  # page words / OCR-layer words
# Beyond Latin (Extended, Additional and -D: the medieval marks), combining marks and Greek, only these.
ALLOWED = set("⟦⟧⟪⟫–—‘’“”«»†‡§¶·ªºᵃᵉ…′″")
# gemini-3.8-flash replaces a space with one CJK glyph (« vel湯excellenter », Leonine tome V): a lone
# glyph between Latin text and a Latin letter is that glitch and becomes a space; a run of them is a
# loop that lost text, and the foreign-script check fails the page.
STRAY_GLYPH = re.compile(r"(?<=[^\W\d_]|[,.;:])[　-鿿](?=[A-Za-z])")
FENCE = re.compile(r"\A\s*```[a-z]*\n(.*?)\n```\s*\Z", re.S)
LAYER = re.compile(r"^<<<(END )?([A-Z0-9-]+)>>>$")


def _carry_italics(text: str) -> str:
    """An italic span the reader carried over a line break closes on its line and reopens on the
    next. Only a pair of odd lines at most four apart, in one paragraph, with even lines between: a
    lone stray asterisk is left for the check."""
    lines = text.split("\n")
    odd = lambda l: "**" not in l and l.count("*") % 2 == 1
    i = 0
    while i < len(lines):
        if odd(lines[i]):
            j = i + 1
            while j < len(lines) and j - i <= 4 and lines[j].strip() and not lines[j].startswith("<<<") \
                    and not odd(lines[j]):
                j += 1
            if j < len(lines) and j - i <= 4 and lines[j].strip() and odd(lines[j]):
                for k in range(i, j + 1):
                    lines[k] = ("*" if k > i else "") + lines[k] + ("*" if k < j else "")
                i = j + 1
                continue
        i += 1
    return "\n".join(lines)


def _join_intra_page_hyphens(text: str) -> str:
    """Join a word broken across a line break inside the same paragraph (``carẽ-\\ntibus``),
    leaving page-final hyphens (followed by a comment or EOF) and structural lines untouched."""
    return re.sub(
        r"([a-zſæœãẽĩõũāēīōūęꝰꝫ])-[ \t]*\n[ \t]*([a-zſæœãẽĩõũāēīōūę])",
        r"\1\2",
        text,
    )


def strip_duplicate_catchword(prev_text: str, text: str) -> tuple[str, str | None]:
    """If the previous page declared a catchword and already ended with that word/fragment
    (without a trailing hyphen), drop an exact duplicate copy at the start of this page."""
    cm = re.search(r"catchword:\s*([^\s;]+)", prev_text)
    if not cm or cm[1].lower() == "none":
        return text, None
    catch = cm[1]
    prev_body = re.sub(r"<!--.*?-->", "", prev_text, flags=re.S).strip()
    prev_words = prev_body.split()
    if not prev_words or prev_words[-1].endswith("-"):
        return text, None
    if not prev_words[-1].lower().rstrip(".,;:!?").endswith(catch.lower().rstrip(".,;:!?")):
        return text, None
    m = re.match(r"^(\s*(?:<<<[^>]+>>>\s*)?)(" + re.escape(catch) + r")([ \t]+)", text, flags=re.I)
    if not m:
        return text, None
    return m[1] + text[m.end():], catch


def repair(text: str, title_after: str | None = None, vocab: set | None = None) -> tuple[str, int]:
    """Mechanical fixes, never judgement. Returns (text, stray glyphs replaced).

    With ``title_after``, a heading's title set as one italic or bold-italic line (as the print sets
    it: Bañez, 30 pages) becomes the bold line the assembler takes. With ``vocab``, a word kept
    mid-line with its line-end hyphen (with or without a space after the hyphen) is joined when the
    joined form is a known word."""
    if m := FENCE.match(text):
        text = m[1] + "\n"
    text = _carry_italics(text)
    text = _join_intra_page_hyphens(text)
    # Stray combining acute on enclitic q; (q́; -> q;) breaks expand's QUE_MARK rule.
    text = re.sub(r"q\u0301;", "q;", unicodedata.normalize("NFC", text))
    # Footnote opener missing stop after digits (^[71 text -> ^[71. text) and stray space before ^[.
    text = re.sub(r"\^\[(\d{1,3})[ \t]+(?!\.)", r"^[\1. ", text)
    text = re.sub(r"(?<=[^\s(\[—–])[ \t]+\^\[", "^[", text)
    # Two paragraphs on consecutive lines (a sentence end, then a capital: Bañez pg-400's two summary
    # paragraphs) are one paragraph to the assembler: the contract's blank line goes between them.
    text = re.sub(r"(?m)([.?!:]\*{0,2})\n(?=\*{0,2}[A-ZÆŒ])", r"\1\n\n", text)
    # the final comment on a line of its own (Bañez pg-326 glued it to the last word)
    text = re.sub(r"(?<=\S)[ \t]*(<!--(?:(?!<!--).)*-->\s*)\Z", r"\n\1", text, flags=re.S)
    text = re.sub(r"\n{3,}", "\n\n", text)
    # the contract's comment form, which the assembler requires
    text = re.sub(r"<!--(?!\s*notes:)\s*", "<!-- notes: ", text)
    if title_after:
        text = re.sub(rf"(?m)^(\*\*(?:{title_after})\*\*[ \t]*\n\s*)\*{{1,3}}([^*\n]+?)\*{{1,3}}[ \t]*$",
                      r"\1**\2**", text)
    if vocab:
        text = "\n".join(SPLIT.sub(lambda m: m[1] + m[2] if _joinable(m, vocab) else m[0], line)
                         for line in text.split("\n"))
    return STRAY_GLYPH.subn(" ", text)


SPLIT = re.compile(r"(?<![\w-])([^\W\d_]{2,})-[ \t]*([^\W\d_]{2,})(?![\w-])")


def _joinable(m: re.Match, vocab: set) -> bool:
    """Mid-line (a hyphen on the line's last word is the print's own seam), and a known word joined."""
    return (bool(m.string[m.end():].strip()) or " " in m[0] or "\t" in m[0]) \
        and fold(m[1] + m[2]) in vocab and not re.fullmatch(r"[IVXL]+", m[1])


def fold(word: str) -> str:
    """A form comparable across a diplomatic page and the (normalized) corpus lexicon."""
    w = unicodedata.normalize("NFD", word.lower().replace("ſ", "s"))
    w = "".join(c for c in w if not unicodedata.combining(c))
    return w.replace("æ", "ae").replace("œ", "oe").replace("ę", "ae").replace("v", "u").replace("j", "i")


def split_words(text: str, vocab: set) -> list[str]:
    """A word the print breaks at a line end, kept mid-line with its hyphen (« diſtin-ctio » or
    « carẽ- tibus »). A compound the print hyphenates is not a word in the vocabulary, and stays."""
    out = []
    for n, line in enumerate(text.splitlines(), 1):
        body = re.sub(r"\^\[[^\]]*\]|<!--.*", "", line).rstrip()
        for m in SPLIT.finditer(body):
            if (m.end() < len(body) or " " in m[0] or "\t" in m[0]) \
                    and fold(m[1] + m[2]) in vocab and not re.fullmatch(r"[IVXL]+", m[1]):
                out.append(f"line {n}: {m[0]!r} is a word broken at a line end in the print: "
                           f"write it whole, {m[1] + m[2]!r}")
    return out


def check(text: str, ocr_words: int | None = None, vocab: set | None = None,
          title_after: str | None = None) -> list[str]:
    """The problems of one reading (after ``repair``); [] when it passes."""
    problems = []
    if "```" in text:
        problems.append("code fence in the reading")
    if not re.search(r"<!-- notes:.*-->\s*\Z", text, re.S):
        problems.append("no final comment: the last line is « <!-- notes: … --> »")
    elif not re.search(r"joins-next:\s*(space|hyphen|para)\b", text):
        problems.append("the final comment has no « joins-next: space|hyphen|para »")
    open_ = None
    for n, line in enumerate(text.splitlines(), 1):
        if mk := LAYER.match(line.strip()):
            end, name = bool(mk[1]), mk[2]
            if end and open_ != name:
                problems.append(f"line {n}: END {name} closes {open_ or 'nothing'}")
            elif not end and open_:
                problems.append(f"line {n}: {name} opens inside {open_}")
            open_ = None if end else name
    if open_:
        problems.append(f"layer {open_} never closed")
    if title_after:
        for m in re.finditer(rf"(?m)^\*\*(?:{title_after})\*\*[ \t]*\n\s*(\S.*)$", text):
            if not re.fullmatch(r"\*\*[^*]+\*\*", m[1].strip()):
                problems.append(f"the title under {m[0].splitlines()[0]!r} is not one bold line: {m[1][:60]!r}; "
                                "set the whole title as **…** on one line")
    body = re.sub(r"<!--.*?-->", " ", text, flags=re.S)
    foreign = sorted({c for c in body if ord(c) > 0x024F and not (0x0370 <= ord(c) <= 0x03FF
                      or 0x1E00 <= ord(c) <= 0x1FFF or 0x0300 <= ord(c) <= 0x036F
                      or 0xA720 <= ord(c) <= 0xA7FF) and c not in ALLOWED})
    if foreign:
        problems.append(f"characters of another script: {' '.join(foreign)}")
    problems += [x.split(": ", 1)[-1] for x in cm.comment_issues(text, "page") + cm.markup_issues(text, "page")
                 + cm.wrap_issues(text, "page")]
    if vocab:
        problems += split_words(body, vocab)
    if ocr_words:
        # ponytail: under 150 words either side the ratio is noise (a page's tail, an OCR layer that
        # sees only the running head), so a short page is not counted.
        words = len(re.findall(r"\w+", re.sub(r"(?m)^<<<.*>>>$", "", body)))
        ratio = words / ocr_words
        if min(words, ocr_words) >= 150 and not OCR_BAND[0] <= ratio <= OCR_BAND[1]:
            problems.append(f"word count {words} is {ratio:.2f} of the OCR layer's {ocr_words}: text lost or repeated")
    return problems


def ocr_word_count(pdf: Path, page: int) -> int:
    out = subprocess.run(["pdftotext", "-f", str(page), "-l", str(page), "-layout", str(pdf), "-"],
                         capture_output=True, text=True).stdout
    return len(re.findall(r"\w+", out))


def _work(work: Path) -> dict:
    return json.loads((work / "work.json").read_text())


def _pages(spec: str) -> list[int]:
    out = []
    for part in spec.split(","):
        lo, _, hi = part.partition("-")
        out += range(int(lo), int(hi or lo) + 1)
    return out


@app.command("check")
def check_cmd(work: Path,
              pages: Annotated[str, typer.Option(help="e.g. 326-646 or 326,400")],
              run: Annotated[str, typer.Option(help="The reading run, under the work")] = "runs/read",
              promote: Annotated[bool, typer.Option(help="Copy passing pages to the page-file directory")] = False,
              title_after: Annotated[str, typer.Option(help="Regex of heading lines whose title follows as one bold line")] = "",
              lexicon: Annotated[Path, typer.Option(help="Corpus lexicon JSON, for words split at a line end")] = None):
    w = _work(work)
    pdf = work / w["source_pdf"] if w.get("source_pdf") else None
    offset = int(w.get("pages", {}).get("pdf_offset", 0))
    pf = work / w.get("page_files", {}).get("dir", "diplomatic")
    vocab = {fold(x) for x in json.loads(lexicon.read_text())["forms"]} if lexicon else set()
    vocab |= {fold(x) for f in pf.glob("pg-*.md") for x in re.findall(r"[^\W\d_]+", re.sub(r"\w-\s*\w", " ", f.read_text()))}
    rd, report = work / run, {}
    prev_text = ""
    for p in _pages(pages):
        f, dest = rd / f"pg-{p:03d}.md", pf / f"pg-{p:03d}.md"
        if promote and dest.exists():
            report[p] = []  # promoted: the page file is the source of truth; audit it with --run <dir>
            prev_text = dest.read_text()
            continue
        if not f.exists():
            report[p] = ["no reading"]
            prev_text = ""
            continue
        text, n_glyphs = repair(f.read_text(), title_after or None, vocab)
        dup_catch = None
        if prev_text:
            text, dup_catch = strip_duplicate_catchword(prev_text, text)
        ocr_n = ocr_word_count(pdf, p + offset) if pdf and pdf.exists() else None
        report[p] = check(text, ocr_n, vocab, title_after or None)
        if promote and not report[p]:
            pf.mkdir(exist_ok=True)
            dest.write_text(text)
            if n_glyphs or dup_catch:
                entry = {"page": p}
                if n_glyphs:
                    entry["stray_glyphs_to_space"] = n_glyphs
                if dup_catch:
                    entry["duplicate_catchword_stripped"] = dup_catch
                with (rd / "repairs.jsonl").open("a") as fh:
                    fh.write(json.dumps(entry) + "\n")
        prev_text = text
    (rd / "gate.json").write_text(json.dumps(report, indent=1, ensure_ascii=False))
    bad = {p: v for p, v in report.items() if v}
    for p, v in bad.items():
        typer.echo(f"pg-{p:03d}: " + " | ".join(v))
    typer.echo(f"{len(report) - len(bad)} pages pass, {len(bad)} fail")
    raise typer.Exit(1 if bad else 0)


@app.command()
def reread(work: Path,
           prompt_file: Annotated[Path, typer.Option(help="The reader prompt")],
           model: Annotated[str, typer.Option(help="Model resource name, models/<name>; no default")],
           run: Annotated[str, typer.Option()] = "runs/read",
           max_attempts: Annotated[int, typer.Option()] = 2,
           thinking: Annotated[str, typer.Option(help="Thinking setting; 3.8 Flash requires explicit low, medium, or high")] = "off"):
    from exscriptor.gemini_batch_run import call, make_config
    config = make_config(thinking=thinking, model=model)
    rd = work / run
    images = work / _work(work).get("page_files", {}).get("scans", "pages")
    gate = json.loads((rd / "gate.json").read_text())
    failed = rd / "failed"
    failed.mkdir(exist_ok=True)
    escalate = {}
    for page, problems in sorted(gate.items(), key=lambda kv: int(kv[0])):
        if not problems or problems == ["no reading"]:
            continue
        name = f"pg-{int(page):03d}"
        tries = len(list(failed.glob(f"{name}.v*.md")))
        if tries >= max_attempts:
            escalate[page] = problems
            continue
        (rd / f"{name}.md").rename(failed / f"{name}.v{tries + 1}.md")
        feedback = ("\n\n# This page was read before, and the reading was refused for these reasons:\n"
                    + "\n".join(f"- {p}" for p in problems)
                    + "\nRead the page again from the image, following every rule above.")
        req = {"contents": [{"role": "user", "parts": [
                   {"text": prompt_file.read_text() + feedback},
                   {"inline_data": {"mime_type": "image/jpeg",
                                    "data": base64.b64encode((images / f"{name}.jpg").read_bytes()).decode()}}]}],
               "generationConfig": {**config, "maxOutputTokens": 32000,
                                    # a second refusal changes the input too: the same image at the same
                                    # resolution looped twice (Leonine pg-071)
                                    "mediaResolution": "MEDIA_RESOLUTION_HIGH" if tries == 0 else "MEDIA_RESOLUTION_MEDIUM"}}
        r = call(f"{model}:generateContent", req, method="POST", timeout=600)
        cand = (r.get("candidates") or [{}])[0]
        um = r.get("usageMetadata", {})
        with (rd / "usage.jsonl").open("a") as fh:
            fh.write(json.dumps({"page": int(page), "finish": cand.get("finishReason"), "reread": tries + 1, "sync": True,
                                 "prompt_tokens": um.get("promptTokenCount"),
                                 "candidates_tokens": um.get("candidatesTokenCount"),
                                 "thoughts_tokens": um.get("thoughtsTokenCount")}) + "\n")
        if cand.get("finishReason") != "STOP":
            typer.echo(f"{name}: finishReason {cand.get('finishReason')}, not written")
            continue
        (rd / f"{name}.md").write_text("".join(p.get("text", "") for p in cand["content"]["parts"]
                                               if not p.get("thought")) + "\n")
        typer.echo(f"{name}: read again (attempt {tries + 1})")
    (rd / "escalate.json").write_text(json.dumps(escalate, indent=1, ensure_ascii=False))
    if escalate:
        typer.echo(f"{len(escalate)} page(s) refused {max_attempts} times: {rd / 'escalate.json'}")


if __name__ == "__main__":
    app()
