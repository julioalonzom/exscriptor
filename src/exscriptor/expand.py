#!/usr/bin/env python3
"""Diplomatic page files -> edition page files, every change on record.

An early print is transcribed DIPLOMATICALLY first: every abbreviation mark,
long s, ligature, u/v and i/j as printed. Reading and normalizing in one pass
measurably costs accuracy, and the diplomatic layer is the training data for
cheaper readers later. This module derives the edition layer from it, in the
order that keeps each decision as cheap and as safe as it can be.
abbreviations.tsv columns: ``pattern  expansion  kind  note  glyph`` (glyph:
the character the reader must emit, needed only for regex rows):

1. **Decisions** already taken by an editor (LLM with the scan, or a scan
   adjudication) for a token -- per occurrence, per page or everywhere.
2. **The edition's abbreviation table** (``abbreviations.tsv``, written at
   scouting from the sample pages): marks this fount uses with exactly one
   meaning. Rows: ``pattern<TAB>expansion<TAB>kind<TAB>note`` where kind is
   ``literal`` (substring anywhere), ``token`` (whole token) or ``regex``
   (Python regex over the token, ``\\1`` groups allowed). A position-dependent
   mark (``;`` after b = -bus, after q = -que) is a regex row.
3. **Safe built-in rules**: print accents dropped (``quòd``, ``à``; diaeresis
   kept), vowel-value V in capitals -> U (``SVMMARIVM``; Roman numerals
   kept), v after q / before a consonant / word-final -> u (``Qvibvs``),
   ``æ œ ę`` -> ae oe ae (case-aware), long s -> s
   (the diplomatic layer writes ``ſ`` only where the print has it), ``⁊`` and
   ``&`` -> et, ``&c.`` -> etc., typographic ligatures, consonantal j -> i.
4. **Lexicon decisions** for the nasal bar (a tilde/macron over a vowel = an
   omitted m OR n) and for u/v: every m/n and u/v reading of the token is
   generated and the corpus lexicon picks (``unique`` / ``frequency`` at
   DOMINANCE x / ``prefer``: the edition's own spelled-out habit). Case is
   kept (``QVOD`` -> ``QUOD``). A medial v is never varied (always a
   consonant). A form the lexicon does not know gets u -> v between vowels
   (method ``pattern``).
5. Anything still carrying a mark, a ``variant``/``none`` lexicon result, or
   a table expansion that yields a form the lexicon has never seen
   (``rule-oov``: ``ꝓcisam`` -> *procisam*, where the fount's p-bar was *prae*),
   goes to ``pending.tsv`` for the editor pass; the token is left as printed
   in the edition page so the orthography gate keeps failing until it is
   decided. The editor answers in ``decisions.tsv`` and the run is repeated.

A separate, non-blocking report, ``long-s.tsv``, lists tokens where reading
an ``f`` as a long s gives a known word: ``fed`` (unknown) vs ``sed`` is a
misread to fix in the diplomatic layer; ``fit`` vs ``sit`` (both known) is a
context question for the editor.

Every applied change is written to ``expansions.tsv`` (page, diplomatic,
edition, method, detail, count): the edition is reproducible from the
diplomatic layer, and each row is a training pair.

decisions.tsv columns: ``page  token  occurrence  edition  method  evidence``
(``page`` and ``occurrence`` may be ``*``; method ``editor`` or ``scan``).

Usage:

    python3 -m exscriptor.expand brief abbreviations.tsv     # the reading brief's mark list
    python3 -m exscriptor.expand run --pages 'diplomatic/*.md' --out-dir edition \\
        --table abbreviations.tsv --lexicon .cache/latin-lexicon.json \\
        --decisions decisions.tsv --record expansions.tsv

Exits 1 while anything is pending (``--allow-pending`` for a progress run).
"""
from __future__ import annotations

import glob as globmod
import itertools
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import typer
from typing_extensions import Annotated

from exscriptor import lexicon as lx
from exscriptor.orthography_screen import char_category, read_allow_file

TOKEN = re.compile(r"(?:[^\W\d_]|[̀-ͯ᷀-᷿︠-︯])+")
NASAL = {0x0303, 0x0304, 0x0305}
MAX_CANDIDATES = 256
BUILTIN_CHARS = {
    "ſ": "s", "ę": "ae", "Ę": "Ae", "⁊": "et",
    "ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl", "ﬅ": "st", "ﬆ": "st",
}
LIGATURES = {"æ": "ae", "œ": "oe", "Æ": "Ae", "Œ": "Oe"}
COMMENT = re.compile(r"<!--.*?-->", re.S)
EDITOR_NOTE = re.compile(r"^(?:\d+\.\s*)?Editor['’]s note", re.I)


def split_protected(text: str) -> list[tuple[bool, str]]:
    """(protected, segment) pieces. Comments and editor's notes are
    protected: copied verbatim, because an editor's note quotes the print
    ("the print reads iuuificantem"), and normalizing it would falsify that."""
    out: list[tuple[bool, str]] = []
    for part in re.split(r"(<!--.*?-->)", text, flags=re.S):
        if part.startswith("<!--"):
            out.append((True, part))
            continue
        start = i = 0
        while (j := part.find("^[", i)) >= 0:
            depth, k = 0, j + 1
            while k < len(part):
                depth += {"[": 1, "]": -1}.get(part[k], 0)
                if depth == 0:
                    break
                k += 1
            if EDITOR_NOTE.match(part[j + 2:k].strip()):
                out += [(False, part[start:j]), (True, part[j:k + 1])]
                start = k + 1
            i = k + 1
        out.append((False, part[start:]))
    return out


def recase(src: str, target: str) -> str:
    letters = [c for c in src if c.isalpha()]
    if len(letters) > 1 and all(c.isupper() for c in letters):
        return target.upper()
    if letters and letters[0].isupper():
        return target[:1].upper() + target[1:]
    return target


def has_mark(token: str) -> bool:
    return any(char_category(c) == "abbrev-mark" for c in token) or \
        any(ord(c) in NASAL | set(range(0x0363, 0x0370)) for c in unicodedata.normalize("NFD", token))


@dataclass
class Rule:
    pattern: str
    expansion: str
    kind: str
    rx: re.Pattern | None = None
    note: str = ""
    glyph: str = ""

    def apply(self, token: str) -> str:
        if self.kind == "literal":
            return token.replace(self.pattern, self.expansion)
        if self.kind == "token":
            return recase(token, self.expansion) if token.lower() == self.pattern.lower() else token
        return self.rx.sub(self.expansion, token)


def read_table(path: Path) -> list[Rule]:
    rules = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip() or line.startswith("#"):
            continue
        cols = line.split("\t")
        if cols[0] == "pattern" and n == 1:
            continue
        if len(cols) < 3 or cols[2] not in ("literal", "token", "regex", "text-regex"):
            raise ValueError(f"{path}:{n}: want pattern<TAB>expansion<TAB>literal|token|regex|text-regex")
        pattern = unicodedata.normalize("NFC", cols[0])
        rules.append(Rule(pattern, cols[1], cols[2],
                          re.compile(pattern) if cols[2] in ("regex", "text-regex") else None,
                          cols[3].strip() if len(cols) > 3 else "",
                          unicodedata.normalize("NFC", cols[4].strip()) if len(cols) > 4 else ""))
    return rules


@dataclass
class Decision:
    page: str
    token: str
    occurrence: str
    edition: str
    method: str
    evidence: str


def read_decisions(path: Path | None) -> list[Decision]:
    if not path or not path.exists():
        return []
    out = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        cols = line.split("\t")
        if not line.strip() or line.startswith("#") or (n == 1 and cols[0] == "page"):
            continue
        if len(cols) < 6 or not cols[5].strip() or cols[4] not in ("editor", "scan"):
            raise ValueError(f"{path}:{n}: want page, token, occurrence, edition, editor|scan, evidence")
        out.append(Decision(cols[0], unicodedata.normalize("NFC", cols[1]), cols[2], cols[3], cols[4], cols[5]))
    return out


ACCENTS = {0x0300, 0x0301, 0x0302}  # grave, acute, circumflex; diaeresis is kept
CAPS_V = re.compile(r"(?<=Q)V|V(?=[^AEIOUY])|V$")
# A consonantal v is always followed by a vowel, and q is always followed by
# u: so v after q, before a consonant or at a word's end is the vowel u
# (small capitals transcribed in lower case: Qvibvs, vbiqve -> Quibus, ubique).
LOWER_V = re.compile(r"v(?=[^aeiouyAEIOUY\W\d_])|v$")
QV = re.compile(r"(?<=[qQ])[vV]")
# Fallback for forms the lexicon does not know: u between vowels is a
# consonant (concursiua, suauis, euentus). Recorded as method 'pattern'.
VUV = re.compile(r"(?<=[aeiouy])u(?=[aeiouy])")
# The other places a u is certainly a consonant in a form the lexicon does not
# know: word-initial before a vowel (uenerabilium), and after a verbal prefix
# (conuocasse, inuitantibus).
INITIAL_V = re.compile(r"^u(?=[aeio])")
PREFIX_V = re.compile(r"^((?:re|e|de|pre)?(?:con|in|ad|ob|sub|per|inter|trans))u(?=[aeio])")


def uv_pattern(low: str) -> str:
    return VUV.sub("v", PREFIX_V.sub(r"\1v", INITIAL_V.sub("v", low)))
# A well-formed Roman numeral is never a word to normalize: lib. iv, cap. xv
# (the v rules would read them as iu, xu). vlli is not well-formed, so it still
# becomes ulli.
ROMAN = re.compile(r"m{0,4}(cm|cd|d?c{0,3})(xc|xl|l?x{0,3})(ix|iv|v?i{0,3})", re.I)


def strip_accents(token: str) -> str:
    out = []
    for ch in token:
        base, *marks = unicodedata.normalize("NFD", ch)
        if base.lower() in "aeiouy" and {ord(m) for m in marks} & ACCENTS:
            rest = "".join(m for m in marks if ord(m) not in ACCENTS)
            out.append(unicodedata.normalize("NFC", base + rest))
        else:
            out.append(ch)
    return "".join(out)


DIPLOMATIC_RULES = """\
Transcribe DIPLOMATICALLY: copy what is printed, letter for letter. Do not
expand, normalize, modernize or correct anything; a later, deterministic step
does that from your page. In particular:

- long s: write ſ (U+017F) wherever the print has a long s; never s, never f.
  Look twice at every f/ſ: they differ only by the crossbar.
- u/v and i/j exactly as printed (vt, prauorum, iam, eius).
- æ œ & as printed. Print accents (quòd, à) as printed.
- A tilde or macron over a vowel: write the vowel with the mark (õ ã ẽ ũ ā ē ī
  ō ū), never the m or n it stands for.
- Every abbreviation mark below: write exactly the character shown, never
  its expansion. A mark that is NOT in this list: write ⟦mark: <describe it>⟧
  and go on; never guess its meaning.
"""


def brief(rules: list[Rule]) -> str:
    """The reading-brief section for a diplomatic transcription, generated
    from the edition's abbreviation table so the two cannot drift apart."""
    lines = [DIPLOMATIC_RULES, "Marks this print uses (copy the character exactly):", ""]
    for r in rules:
        glyph = r.glyph or (r.pattern if r.kind != "regex" else "")
        if not glyph:
            continue
        cps = " ".join(f"U+{ord(c):04X}" for c in glyph if not c.isascii() or not c.isalnum())
        note = f" -- {r.note}" if r.note else ""
        lines.append(f"- `{glyph}` ({cps or 'ASCII'}){note}")
    return "\n".join(lines) + "\n"


def builtin(token: str, keep_uv: bool = False) -> str:
    token = strip_accents(token)
    letters = [c for c in token if c.isalpha()]
    if not keep_uv:
        if len(letters) >= 3 and all(c.isupper() for c in letters) \
                and not re.fullmatch(r"[IVXLCDM]+", token):
            token = CAPS_V.sub("U", token)
        token = LOWER_V.sub("u", token)
        token = QV.sub(lambda m: "U" if m.group(0) == "V" else "u", token)
    out = []
    for c in token:
        if c in LIGATURES:
            out.append(LIGATURES[c])
        else:
            out.append(BUILTIN_CHARS.get(c, c))
    t = "".join(out)
    t = t.replace("j", "i").replace("J", "I")
    return recase(token, t) if t != token and token.isupper() else t


LONG_S_FLOOR = 20  # an s-reading rarer than this in the corpus is noise
UV_DOMINANCE = 5  # u/v is near-deterministic in a v-consonant corpus


def _slots(token: str) -> list[tuple[str, list[str]]] | None:
    """(kind, options) per character: 'nasal' (m/n), 'uv' (u/v) or 'fixed'.
    None if the token carries a mark other than a nasal bar."""
    slots = []
    for pos, ch in enumerate(unicodedata.normalize("NFC", token.lower())):
        base, *marks = unicodedata.normalize("NFD", ch)
        codes = {ord(m) for m in marks}
        if codes & NASAL:
            if base not in "aeiouy" or codes - NASAL:
                return None
            slots.append(("nasal", [base + "m", base + "n"]))
        elif char_category(ch) == "abbrev-mark":
            return None
        elif ch == "u" or (ch == "v" and pos == 0):
            # Early prints write v at a word's start and u inside it, whatever
            # the sound. So an initial v may be a vowel (vt -> ut) and a medial
            # u a consonant (prauorum -> pravorum), but a medial v is always a
            # consonant: never vary it, or volvit "corrects" to voluit.
            slots.append(("uv", ["u", "v"]))
        else:
            slots.append(("fixed", [ch]))
    return slots


def candidates(token: str) -> list[str] | None:
    """Every m/n reading of each nasal bar and u/v reading of each u/v.
    None if the token carries another mark or there is nothing to vary."""
    slots = _slots(token)
    if slots is None or all(k == "fixed" for k, _ in slots):
        return None
    combos = 1
    for _, opts in slots:
        combos *= len(opts)
    if combos > MAX_CANDIDATES:
        return None
    return ["".join(c) for c in itertools.product(*(o for _, o in slots))]


def _pick(scores: dict, prefer: dict, dominance: int) -> tuple[str, object]:
    known = sorted((k for k in scores if scores[k]), key=lambda k: -scores[k])
    if len(known) == 1:
        return "unique", known[0]
    if not known:
        return "none", None
    top, second = known[0], known[1]
    if scores[top] >= dominance * scores[second]:
        return "frequency", top
    if prefer.get(top, 0) != prefer.get(second, 0):
        return "prefer", max(known[:2], key=lambda k: prefer.get(k, 0))
    return "variant", None


def decide(token: str, lexicon: Counter, prefer: Counter | None = None) -> tuple[str, str | None]:
    """(status, choice) for a token by the lexicon; choice is lower-case.

    Two questions, decided in turn: which m/n each nasal bar stands for
    (scored over all u/v spellings, so a corpus that writes both does not
    split the vote), then which u/v spelling of that reading."""
    cands = candidates(token)
    if cands is None:
        return ("other-marks" if has_mark(token) else "none"), None
    prefer = prefer or Counter()
    slots = _slots(token)
    nasal_idx = [i for i, (k, _) in enumerate(slots) if k == "nasal"]
    combos = list(itertools.product(*(o for _, o in slots)))
    status = "unique"
    if nasal_idx:
        sig_score: Counter = Counter()
        sig_pref: Counter = Counter()
        for c in combos:
            sig = tuple(c[i] for i in nasal_idx)
            sig_score[sig] += lexicon.get("".join(c), 0)
            sig_pref[sig] += prefer.get("".join(c), 0)
        for sig in {tuple(c[i] for i in nasal_idx) for c in combos}:
            sig_score.setdefault(sig, 0)
        status, sig = _pick(sig_score, sig_pref, lx.DOMINANCE)
        if sig is None:
            return status, None
        combos = [c for c in combos if tuple(c[i] for i in nasal_idx) == sig]
    forms = {"".join(c): lexicon.get("".join(c), 0) for c in combos}
    uv_status, choice = _pick(forms, prefer, UV_DOMINANCE)
    if choice is None:
        return uv_status, None
    order = ["unique", "frequency", "prefer"]
    return order[max(order.index(status), order.index(uv_status))], choice


@dataclass
class Result:
    text: str
    changes: list[tuple[str, str, str, str]] = field(default_factory=list)  # dip, ed, method, detail
    pending: list[tuple[str, int, str, str]] = field(default_factory=list)  # token, occ, status, cands


def expand_text(text: str, page: str, *, rules: list[Rule], decisions: list[Decision],
                lexicon: Counter | None, prefer: Counter | None = None,
                keep: set[str] | None = None, keep_uv: bool = False,
                prev_tail: str | None = None, next_head: str | None = None) -> Result:
    """keep_uv: the print's u/v already follows the house rule (a modern print):
    no u/v rule runs and the lexicon decides only nasal bars.

    prev_tail / next_head: the other half of a word hyphenated across the
    page break (the previous page's last fragment, the next page's first
    token). The lexicon decides u/v on the joined word: iu- + stitiam keeps
    iu, uir- + tutem becomes vir-."""
    res = Result("")
    text = unicodedata.normalize("NFC", text)
    # Marks that are not letters (&, the Tironian et, a table's ';'-style
    # signs) never form part of a token: expand them in the running text.
    text_rules = [("&c.", "etc.", "builtin"), ("&", "et", "builtin"), ("⁊", "et", "builtin")]
    text_rules += [(r.pattern, r.expansion, f"table:{r.pattern}") for r in rules
                   if r.kind == "literal" and not any(c.isalpha() for c in r.pattern)]
    body = split_protected(text)
    for pat, rep, detail in text_rules:
        n = sum(s.count(pat) for keep_, s in body if not keep_)
        if n:
            body = [(k, s if k else s.replace(pat, rep)) for k, s in body]
            res.changes += [(pat, rep, "rule", detail)] * n
    # Context-dependent punctuation belongs to an edition's explicit text
    # rules, before word tokenization (which intentionally excludes stops).
    for rule in rules:
        if rule.kind != "text-regex":
            continue
        def text_repl(match):
            replacement = match.expand(rule.expansion)
            if replacement != match[0]:
                res.changes.append((match[0], replacement, "rule", f"table:{rule.pattern}"))
            return replacement
        body = [(k, part if k else rule.rx.sub(text_repl, part)) for k, part in body]
    rules = [r for r in rules if r.kind != "text-regex" and not (r.kind == "literal" and not any(c.isalpha() for c in r.pattern))]
    seen: Counter = Counter()
    by_key = {(d.page, d.token, d.occurrence): d for d in decisions}

    # Comments (the notes layer) and editor's notes are copied, never
    # expanded; a note's words still count toward occurrence numbers, so
    # decisions keyed by occurrence do not move.
    out_parts = []
    for protected, part in body:
        if protected:
            if not part.startswith("<!--"):
                for tok in TOKEN.findall(part):
                    seen[tok] += 1
            out_parts.append(part)
            continue

        def repl(m: re.Match) -> str:
            tok = m.group(0)
            seen[tok] += 1
            occ = str(seen[tok])
            d = (by_key.get((page, tok, occ)) or by_key.get((page, tok, "*"))
                 or by_key.get(("*", tok, "*")))
            if keep and tok in keep or ROMAN.fullmatch(tok):
                return tok
            if d:
                if d.edition != tok:
                    res.changes.append((tok, d.edition, d.method, d.evidence))
                return d.edition
            cur, method = tok, None
            for r in rules:
                nxt = r.apply(cur)
                if nxt != cur:
                    cur, method = nxt, f"table:{r.pattern}"
            nxt = builtin(cur, keep_uv)
            if nxt != cur:
                cur, method = nxt, method or "builtin"
            detail = method
            # A word cut at a hyphen is decided on the joined word, never alone
            # (iu- of iu-stitiam is not iv).
            fragment = m.string[m.end():m.end() + 1] == "-"
            at_end = fragment and next_head and not m.string[m.end() + 1:].strip()
            at_start = prev_tail and sum(seen.values()) == 1
            if (at_end or at_start) and lexicon is not None and not keep_uv:
                left, right = (cur, builtin(next_head)) if at_end else (builtin(prev_tail), cur)
                joined = left + right
                if candidates(joined) is not None and not any(k == "nasal" for k, _ in _slots(joined)):
                    status, choice = decide(joined, lexicon, prefer)
                    if choice is None and status == "none" and uv_pattern(joined.lower()) != joined.lower():
                        status, choice = "pattern", uv_pattern(joined.lower())
                    if choice is not None:
                        new = recase(cur, choice[:len(left)] if at_end else choice[len(left):])
                        if new != tok:
                            res.changes.append((tok, new, "lexicon", f"seam {status}"))
                        return new
                fragment = True
            if lexicon is not None and not fragment and candidates(cur) is not None \
                    and not (keep_uv and not any(k == "nasal" for k, _ in _slots(cur))):
                status, choice = decide(cur, lexicon, prefer)
                if choice is not None and ROMAN.fullmatch(choice):
                    choice = None  # u is no numeral: Lu (Lucas) is not lv
                if choice is not None and recase(cur, choice) != cur:
                    if recase(cur, choice) != tok:
                        res.changes.append((tok, recase(cur, choice), "lexicon", status))
                    return recase(cur, choice)
                if status == "none" and not keep_uv and not has_mark(cur) \
                        and uv_pattern(cur.lower()) != cur.lower():
                    nxt = recase(cur, uv_pattern(cur.lower()))
                    res.changes.append((tok, nxt, "pattern", "consonantal u"))
                    return nxt
                if status in ("variant", "none") and has_mark(cur):
                    res.pending.append((tok, seen[tok], status,
                                        " ".join(f"{c}:{lexicon.get(c, 0)}" for c in candidates(cur))))
                    return tok
            if has_mark(cur):
                res.pending.append((tok, seen[tok], "other-marks", ""))
                return tok
            if lexicon is not None and method and method.startswith("table:") \
                    and lexicon.get(cur.lower(), 0) == 0:
                # a mark rule that yields a non-word read the mark wrongly
                # (p-loop vs p-bar: procisam / praecisam): the editor decides
                res.pending.append((tok, seen[tok], "rule-oov", cur))
                return tok
            if cur != tok:
                res.changes.append((tok, cur, "rule", detail))
            return cur

        out_parts.append(TOKEN.sub(repl, part))
    res.text = "".join(out_parts)
    return res


def seam_tail(text: str) -> str | None:
    """The fragment a page ends on when it ends with a hyphen (``iu-``)."""
    m = re.search(rf"({TOKEN.pattern})-$", COMMENT.sub("", text).rstrip())
    return m.group(1) if m else None


def seam_head(text: str) -> str | None:
    m = TOKEN.search(COMMENT.sub(" ", text))
    return m.group(0) if m else None


def long_s_report(texts: list[str], lexicon: Counter, pages: list[str] | None = None,
                  decisions: list[Decision] = ()) -> list[tuple[str, int, str, int, str]]:
    """(token, count, s-reading, its lexicon count, kind) for f/long-s doubts.

    Empty when no page has a long s: the print has none, so an f is an f.
    An occurrence the editor decided (decisions.tsv, the same keys as
    expand_text, an identity decision included) is no longer a doubt."""
    if not any("ſ" in t for t in texts):
        return []
    dec = {(d.page, d.token, d.occurrence) for d in decisions}
    toks: Counter = Counter()
    for page, text in zip(pages or [""] * len(texts), texts):
        seen: Counter = Counter()
        for t in TOKEN.findall(COMMENT.sub(" ", unicodedata.normalize("NFC", text))):
            seen[t] += 1
            if "f" in t.lower() and not {(page, t, str(seen[t])), (page, t, "*"), ("*", t, "*")} & dec:
                toks[t.lower()] += 1
    out = []
    for tok, n in toks.items():
        idx = [i for i, c in enumerate(tok) if c == "f"]
        for i in idx:
            alt = tok[:i] + "s" + tok[i + 1:]
            a, f = lexicon.get(alt, 0), lexicon.get(tok, 0)
            if a < LONG_S_FLOOR or a * lx.DOMINANCE < f:
                continue  # the s-reading is rare, or negligible next to the f-reading
            kind = "misread" if f * lx.DOMINANCE < a else "context"
            out.append((tok, n, alt, lexicon[alt], kind))
    return sorted(out, key=lambda r: (r[4], -r[1]))


app = typer.Typer(add_completion=False, help="Diplomatic -> edition pages, and the reading brief.")


@app.command("brief")
def brief_cmd(table: Annotated[Path, typer.Argument(help="The edition's abbreviations.tsv")]):
    """Print the diplomatic-reading brief section generated from the table."""
    print(brief(read_table(table)), end="")


@app.command("run")
def main(
    pages: Annotated[list[str], typer.Option(help="Diplomatic page files (globs, repeatable)")],
    out_dir: Annotated[Path, typer.Option(help="Directory for the edition page files")],
    record: Annotated[Path, typer.Option(help="expansions.tsv to write")],
    table: Annotated[Path | None, typer.Option(help="The edition's abbreviations.tsv")] = None,
    lexicon: Annotated[Path | None, typer.Option(help="Corpus lexicon JSON (nasal bars, u/v, long s)")] = None,
    decisions: Annotated[Path | None, typer.Option(help="decisions.tsv from the editor pass")] = None,
    allow_file: Annotated[Path | None, typer.Option(help="Tokens copied verbatim (the orthography allow-file)")] = None,
    allow_pending: Annotated[bool, typer.Option(help="Exit 0 even with pending tokens")] = False,
    keep_uv: Annotated[bool, typer.Option(help="The print's u/v already follows the house rule (modern print): leave it")] = False,
):
    """Derive edition pages from diplomatic pages; record every change."""
    paths = sorted({Path(p) for g in pages for p in (globmod.glob(g) or [g]) if Path(p).is_file()})
    if not paths:
        raise typer.BadParameter("no page files matched")
    rules = read_table(table) if table else []
    decs = read_decisions(decisions)
    lex = lx.load(lexicon) if lexicon else None
    raw = {p: p.read_text(encoding="utf-8") for p in paths}
    prefer = lx.build(list(raw.values()))
    keep = read_allow_file(allow_file) if allow_file else set()
    agg: Counter = Counter()
    pending = []
    out_dir.mkdir(parents=True, exist_ok=True)
    texts = list(raw.values())
    for i, (p, text) in enumerate(raw.items()):
        prev = seam_tail(texts[i - 1]) if i else None
        nxt = seam_head(texts[i + 1]) if i + 1 < len(texts) and seam_tail(text) else None
        r = expand_text(text, p.stem, rules=rules, decisions=decs, lexicon=lex, prefer=prefer,
                        keep=keep, keep_uv=keep_uv, prev_tail=prev, next_head=nxt)
        (out_dir / p.name).write_text(r.text, encoding="utf-8")
        for change in r.changes:
            agg[(p.stem,) + change] += 1
        pending += [(p.stem,) + row for row in r.pending]
    lines = ["page\tdiplomatic\tedition\tmethod\tdetail\tcount"]
    lines += [f"{k[0]}\t{k[1]}\t{k[2]}\t{k[3]}\t{k[4]}\t{n}" for k, n in sorted(agg.items())]
    record.write_text("\n".join(lines) + "\n", encoding="utf-8")
    pend_path = record.with_name("pending.tsv")
    pend_path.write_text("page\ttoken\toccurrence\tstatus\tcandidates\n" +
                         "".join(f"{a}\t{b}\t{c}\t{d}\t{e}\n" for a, b, c, d, e in pending), encoding="utf-8")
    by_method = Counter()
    for k, n in agg.items():
        by_method[k[3]] += n
    print(f"{len(paths)} pages -> {out_dir}; changes: " +
          ", ".join(f"{m}={n}" for m, n in by_method.most_common()) + f"; pending={len(pending)}")
    if lex is not None:
        ls = long_s_report(list(raw.values()), lex, [p.stem for p in raw], decs)
        ls_path = record.with_name("long-s.tsv")
        ls_path.write_text("token\tcount\ts_reading\ts_count\tkind\n" +
                           "".join("\t".join(map(str, r)) + "\n" for r in ls), encoding="utf-8")
        kinds = Counter(r[4] for r in ls)
        print(f"long-s doubts: {kinds.get('misread', 0)} likely misreads, "
              f"{kinds.get('context', 0)} context questions -> {ls_path}")
    if pending:
        print(f"{len(pending)} token(s) pending an editor decision -> {pend_path}")
        if not allow_pending:
            raise typer.Exit(1)


if __name__ == "__main__":
    app()
