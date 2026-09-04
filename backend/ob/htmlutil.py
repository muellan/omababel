"""A tiny DOM built on ``html.parser`` – just enough for scraping.

The stdlib has no HTML DOM, and pulling in lxml/BeautifulSoup would break
the "self-contained plugin" promise.  :func:`parse` returns a :class:`Node`
tree with the handful of query helpers the source drivers need: lookup by
tag / id / class, text extraction with sensible whitespace, and attribute
access.  It is lenient about unclosed tags the way browsers are.
"""

from __future__ import annotations

import html
import re
from html.parser import HTMLParser
from typing import Callable, Iterator, List, Optional

VOID = {
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
    "meta", "param", "source", "track", "wbr",
}
BLOCK = {
    "p", "div", "li", "ul", "ol", "dl", "dt", "dd", "br", "tr", "table",
    "section", "article", "header", "footer", "h1", "h2", "h3", "h4", "h5",
    "h6", "blockquote", "pre", "hr", "td", "th", "figure", "figcaption",
    "nav", "aside", "main", "form", "fieldset",
}
# Tags whose contents should never contribute to visible text.
SKIP_TEXT = {"script", "style", "noscript", "template", "svg", "head"}

# Boundary between two inline elements.  A browser inserts nothing there,
# but many pages rely on the markup alone to separate words, so the
# boundary is kept as a *soft* separator: it becomes a space unless it
# would tear a word apart ("by-" + "product" is one word, not two).
SOFT = "\x00"
# Characters that bind the two sides of a soft separator together.
JOINERS = "-‐‑‒–—/'’ʼ"
# Zero width and formatting characters that must never end up in a word.
INVISIBLE = "­​‌‍⁠﻿"


class Node:
    __slots__ = ("tag", "attrs", "children", "parent", "text")

    def __init__(self, tag: Optional[str], attrs: Optional[dict] = None, text: str = ""):
        self.tag = tag  # None for text nodes
        self.attrs = attrs or {}
        self.children: List["Node"] = []
        self.parent: Optional["Node"] = None
        self.text = text

    # ---- construction -------------------------------------------------
    def append(self, node: "Node") -> "Node":
        node.parent = self
        self.children.append(node)
        return node

    # ---- attributes ---------------------------------------------------
    def get(self, name: str, default: str = "") -> str:
        return self.attrs.get(name, default)

    @property
    def id(self) -> str:
        return self.attrs.get("id", "")

    @property
    def classes(self) -> List[str]:
        return self.attrs.get("class", "").split()

    def has_class(self, *names: str) -> bool:
        cls = set(self.classes)
        return any(n in cls for n in names)

    # ---- traversal ----------------------------------------------------
    def iter(self) -> Iterator["Node"]:
        stack = list(reversed(self.children))
        while stack:
            n = stack.pop()
            yield n
            stack.extend(reversed(n.children))

    def elements(self) -> Iterator["Node"]:
        for n in self.iter():
            if n.tag is not None:
                yield n

    def find_all(
        self,
        tag: Optional[str] = None,
        cls: Optional[str] = None,
        id: Optional[str] = None,
        attrs: Optional[dict] = None,
        pred: Optional[Callable[["Node"], bool]] = None,
        limit: Optional[int] = None,
    ) -> List["Node"]:
        out: List[Node] = []
        tags = None
        if tag:
            tags = set(tag.split(",")) if "," in tag else {tag}
        for n in self.elements():
            if tags and n.tag not in tags:
                continue
            if cls and not n.has_class(cls):
                continue
            if id and n.id != id:
                continue
            if attrs and any(n.attrs.get(k) != v for k, v in attrs.items()):
                continue
            if pred and not pred(n):
                continue
            out.append(n)
            if limit and len(out) >= limit:
                break
        return out

    def find(self, tag: Optional[str] = None, cls: Optional[str] = None,
             id: Optional[str] = None, attrs: Optional[dict] = None,
             pred: Optional[Callable[["Node"], bool]] = None) -> Optional["Node"]:
        res = self.find_all(tag, cls, id, attrs, pred, limit=1)
        return res[0] if res else None

    def ancestors(self) -> Iterator["Node"]:
        p = self.parent
        while p is not None:
            yield p
            p = p.parent

    def closest(self, tag: Optional[str] = None, cls: Optional[str] = None) -> Optional["Node"]:
        for a in self.ancestors():
            if a.tag is None:
                continue
            if tag and a.tag != tag:
                continue
            if cls and not a.has_class(cls):
                continue
            return a
        return None

    # ---- text -----------------------------------------------------------
    def get_text(self, sep: str = " ", strip: bool = True, block_sep: str = "\n") -> str:
        parts: List[str] = []

        def walk(n: Node) -> None:
            if n.tag is None:
                parts.append(n.text)
                return
            if n.tag in SKIP_TEXT:
                return
            if n.tag in BLOCK:
                parts.append(block_sep)
            for c in n.children:
                walk(c)
            if n.tag in BLOCK:
                parts.append(block_sep)
            elif sep == " ":
                parts.append(SOFT)
            elif sep:
                parts.append(sep)

        walk(self)
        text = "".join(parts)
        return clean_text(text) if strip else resolve_soft(text)

    def inline_text(self) -> str:
        """Text with every whitespace run collapsed to one space."""
        return re.sub(r"\s+", " ", self.get_text(block_sep=" ")).strip()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        if self.tag is None:
            return f"Text({self.text[:30]!r})"
        return f"<{self.tag} {self.attrs}>"


_SOFT_RUN = re.compile(SOFT + "+")
_SOFT_AFTER_JOINER = re.compile(f"(?<=[{re.escape(JOINERS)}]){SOFT}")
_SOFT_BEFORE_JOINER = re.compile(f"{SOFT}(?=[{re.escape(JOINERS)}])")


def resolve_soft(text: str) -> str:
    """Turn inline element boundaries into spaces – except where they would
    split a hyphenated or apostrophised word ("by-" + "product")."""
    if SOFT not in text:
        return text
    text = _SOFT_RUN.sub(SOFT, text)
    text = _SOFT_AFTER_JOINER.sub("", text)
    text = _SOFT_BEFORE_JOINER.sub("", text)
    return text.replace(SOFT, " ")


def clean_text(text: str) -> str:
    text = resolve_soft(text).replace("\xa0", " ")
    for ch in INVISIBLE:
        text = text.replace(ch, "")
    lines = [re.sub(r"[ \t\r\f\v]+", " ", ln).strip() for ln in text.split("\n")]
    return "\n".join(ln for ln in lines if ln).strip()


class _TreeBuilder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node("document")
        self.cur = self.root
        self._raw_tag: Optional[str] = None
        self._raw_buf: List[str] = []

    # html.parser already gives us CDATA-mode for script/style contents,
    # but we keep them as a single text child so JSON blobs stay intact.
    def handle_starttag(self, tag: str, attrs) -> None:
        node = Node(tag, {k: (v if v is not None else "") for k, v in attrs})
        self.cur.append(node)
        if tag in VOID:
            return
        # implicit closes browsers apply
        if tag in ("li",) and self.cur.tag == "li":
            self.cur = self.cur.parent or self.root
            node.parent.children.remove(node)
            self.cur.append(node)
        elif tag in ("p",) and self.cur.tag == "p":
            self.cur = self.cur.parent or self.root
            node.parent.children.remove(node)
            self.cur.append(node)
        self.cur = node

    def handle_startendtag(self, tag: str, attrs) -> None:
        self.cur.append(Node(tag, {k: (v if v is not None else "") for k, v in attrs}))

    def handle_endtag(self, tag: str) -> None:
        if tag in VOID:
            return
        n: Optional[Node] = self.cur
        while n is not None and n is not self.root and n.tag != tag:
            n = n.parent
        if n is None or n is self.root:
            return  # stray end tag – ignore
        self.cur = n.parent or self.root

    def handle_data(self, data: str) -> None:
        if not data:
            return
        self.cur.append(Node(None, text=data))

    def handle_comment(self, data: str) -> None:
        pass


def parse(markup: str) -> Node:
    builder = _TreeBuilder()
    builder.feed(markup)
    builder.close()
    return builder.root


def strip_tags(markup: str) -> str:
    """Quick text extraction without building a full tree."""
    markup = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", markup)
    markup = re.sub(r"(?i)<br\s*/?>", "\n", markup)
    markup = re.sub(r"(?i)</(p|div|li|tr|h[1-6]|dd|dt)>", "\n", markup)
    markup = re.sub(r"<[^>]+>", " ", markup)
    return clean_text(html.unescape(markup))


def unescape(text: str) -> str:
    return html.unescape(text)


def find_json_blob(markup: str, marker: str) -> Optional[str]:
    """Return the JSON object/array that follows ``marker`` in ``markup``.

    Used for pages that embed their state in ``<script>`` tags
    (``window.__PRELOADED_STATE__ = {...}``, ``"synonyms":[...]``).  Brackets
    inside strings are handled.
    """
    idx = markup.find(marker)
    if idx < 0:
        return None
    i = idx + len(marker)
    n = len(markup)
    while i < n and markup[i] in " \t\r\n=:":
        i += 1
    if i >= n or markup[i] not in "[{":
        return None
    open_ch = markup[i]
    close_ch = "]" if open_ch == "[" else "}"
    depth = 0
    in_str = False
    esc = False
    j = i
    while j < n:
        ch = markup[j]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        else:
            if ch == '"':
                in_str = True
            elif ch == open_ch:
                depth += 1
            elif ch == close_ch:
                depth -= 1
                if depth == 0:
                    return markup[i:j + 1]
        j += 1
    return None
