"""Turn plain result text into the rich-text the panel renders.

Every word becomes an ``<a href="w:<word>">`` link so the QML side can
resolve which word sits under the mouse pointer (``Text.linkAt``) and
implement *Ctrl+click → new search* / *Alt+click → copy*.  Doing this in
Python keeps the tokenisation testable and Unicode-aware.
"""

from __future__ import annotations

import html
import re
import urllib.parse
from typing import Iterable, List, Optional, Set

# letters/digits/marks plus in-word apostrophes and hyphens; CJK runs count
# as one token (they have no spaces anyway).
_TOKEN = re.compile(r"[\w][\w'’­-]*", re.UNICODE)


def word_href(word: str) -> str:
    return "w:" + urllib.parse.quote(word, safe="")


def href_word(href: str) -> str:
    if href.startswith("w:"):
        return urllib.parse.unquote(href[2:])
    return ""


def linkify(text: str, css_class: str = "", bold: Optional[Set[int]] = None) -> str:
    """Escape ``text`` and wrap each word in a link.

    ``bold`` holds character offsets to print in bold -- the letters an
    acronym is built from (see :func:`acronym_bold`).  They are wrapped
    *inside* the link so a click still hits the whole word.
    """
    if not text:
        return ""
    bold = bold or set()
    out = []
    pos = 0
    for m in _TOKEN.finditer(text):
        out.append(html.escape(text[pos:m.start()]))
        word = m.group(0).strip("-'’")
        token = _emphasise(text, m.start(), m.end(), bold)
        if word:
            out.append(f'<a href="{word_href(word)}">{token}</a>')
        else:
            out.append(token)
        pos = m.end()
    out.append(html.escape(text[pos:]))
    return "".join(out).replace("\n", "<br>")


def _emphasise(text: str, start: int, end: int, bold: Set[int]) -> str:
    """The escaped slice ``text[start:end]`` with ``bold`` offsets in ``<b>``."""
    if not any(i in bold for i in range(start, end)):
        return html.escape(text[start:end])
    out = []
    for i in range(start, end):
        char = html.escape(text[i])
        out.append(f"<b>{char}</b>" if i in bold else char)
    return "".join(out)


# A letter of an acronym may start a word, or sit inside one at a capital
# ("HyperText Transfer Protocol" spells HTTP with two letters from one word).
_WORD_START = re.compile(r"(?<![\w'’])[\w]", re.UNICODE)


def acronym_bold(expansion: str, acronym: str) -> Set[int]:
    """Where ``acronym``'s letters sit in ``expansion``.

    Greedy, left to right, and all or nothing: if the expansion does not
    actually spell the acronym out (a site's "see also" row, an expansion in
    another word order) nothing is highlighted rather than something wrong.
    """
    letters = [ch for ch in str(acronym or "") if ch.isalnum()]
    if not letters or not expansion:
        return set()
    candidates = [m.start() for m in _WORD_START.finditer(expansion)]
    candidates += [i for i, ch in enumerate(expansion)
                   if i and ch.isupper() and expansion[i - 1].isalpha()]
    candidates = sorted(set(candidates))
    found: List[int] = []
    at = 0
    for letter in letters:
        target = letter.casefold()
        while at < len(candidates) and expansion[candidates[at]].casefold() != target:
            at += 1
        if at >= len(candidates):
            return set()
        found.append(candidates[at])
        at += 1
    return set(found)


def _join(words: Iterable[str]) -> str:
    return ", ".join(linkify(w) for w in words)


def decorate_lookup(result: dict) -> None:
    for r in result.get("results", []):
        for e in r.get("entries", []):
            e["headword_html"] = linkify(e.get("headword", ""))
            for s in e.get("senses", []):
                # An acronym sense prints the letters its expansion is built
                # from in bold: "**N**ational **A**eronautics and ...".
                s["gloss_html"] = linkify(s.get("gloss", ""),
                                          bold=acronym_bold(s.get("gloss", ""), s.get("acronym", "")))
                s["examples_html"] = [linkify(x) for x in s.get("examples", [])]
                s["synonyms_html"] = _join(s.get("synonyms", []))
                s["antonyms_html"] = _join(s.get("antonyms", []))
                # Tags are scraped ("Gebrauch", "Grammatik" notes from Duden)
                # or read out of a downloaded dictionary, and the panel puts
                # them inside a rich-text run.  They are not links – a usage
                # note is not a word to look up – but they do have to be
                # escaped, or an `<img src=…>` in one would make the panel
                # fetch a URL of the page's choosing.
                s["tags_html"] = [html.escape(str(t)) for t in s.get("tags", []) if t]
            extra = e.get("extra") or {}
            e["extra_html"] = [{"key": html.escape(str(k)), "value": linkify(str(v))}
                               for k, v in extra.items()]


def decorate_translation(result: dict) -> None:
    for r in result.get("results", []):
        if r.get("text"):
            r["text_html"] = linkify(r["text"])
        r["alternatives_html"] = [linkify(a) for a in r.get("alternatives", [])]
        for p in r.get("pairs", []):
            p["src_html"] = linkify(p.get("src", ""))
            p["dst_html"] = linkify(p.get("dst", ""))
            p["note_html"] = linkify(p.get("note", ""))


def decorate(result: dict) -> dict:
    mode = result.get("mode")
    if mode == "lookup":
        decorate_lookup(result)
    elif mode == "translate":
        decorate_translation(result)
    return result
