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
from typing import Iterable

# letters/digits/marks plus in-word apostrophes and hyphens; CJK runs count
# as one token (they have no spaces anyway).
_TOKEN = re.compile(r"[\w][\w'’­-]*", re.UNICODE)


def word_href(word: str) -> str:
    return "w:" + urllib.parse.quote(word, safe="")


def href_word(href: str) -> str:
    if href.startswith("w:"):
        return urllib.parse.unquote(href[2:])
    return ""


def linkify(text: str, css_class: str = "") -> str:
    """Escape ``text`` and wrap each word in a link."""
    if not text:
        return ""
    out = []
    pos = 0
    for m in _TOKEN.finditer(text):
        out.append(html.escape(text[pos:m.start()]))
        word = m.group(0).strip("-'’")
        token = html.escape(m.group(0))
        if word:
            out.append(f'<a href="{word_href(word)}">{token}</a>')
        else:
            out.append(token)
        pos = m.end()
    out.append(html.escape(text[pos:]))
    return "".join(out).replace("\n", "<br>")


def _join(words: Iterable[str]) -> str:
    return ", ".join(linkify(w) for w in words)


def decorate_lookup(result: dict) -> None:
    for r in result.get("results", []):
        for e in r.get("entries", []):
            e["headword_html"] = linkify(e.get("headword", ""))
            for s in e.get("senses", []):
                s["gloss_html"] = linkify(s.get("gloss", ""))
                s["examples_html"] = [linkify(x) for x in s.get("examples", [])]
                s["synonyms_html"] = _join(s.get("synonyms", []))
                s["antonyms_html"] = _join(s.get("antonyms", []))
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
