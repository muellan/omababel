"""Duden (duden.de) – German dictionary.

Entry pages live at ``/rechtschreibung/<slug>``.  If the guessed slug 404s
we run the site search and follow the first hit.  The parser looks for the
well-known ``division`` blocks (``#bedeutungen``, ``#synonyme`` ...) and
falls back to a generic title/text extraction so a redesign degrades
gracefully instead of returning nothing.
"""

from __future__ import annotations

import re
import unicodedata
from typing import List, Optional

from .. import http, htmlutil
from .. import results as R
from ..htmlutil import Node
from .base import Source, SourceError, register

ENTRY_URL = "https://www.duden.de/rechtschreibung/{slug}"
SEARCH_URL = "https://www.duden.de/suchen/dudenonline/{word}"

_SLUG_MAP = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "Ä": "Ae", "Ö": "Oe",
                           "Ü": "Ue", "ß": "sz", " ": "_"})


def slugify(word: str) -> str:
    return word.strip().translate(_SLUG_MAP)


def strip_marks(text: str) -> str:
    """Duden underlines stressed vowels with U+0332; drop combining marks
    that are not part of the actual spelling."""
    return "".join(ch for ch in unicodedata.normalize("NFC", text)
                   if unicodedata.category(ch) != "Mn" or ch in "̈")


@register
class Duden(Source):
    driver = "duden"
    label = "Duden"
    kind = "remote"
    types = ("dictionary",)
    description = "German spelling, meanings, grammar, origin and synonyms from duden.de."
    default_url = ENTRY_URL
    languages = ("de",)
    order = 10

    def lookup(self, word: str, lang: str) -> dict:
        word = word.strip()
        template = self.url if "{slug}" in self.url or "{word}" in self.url else ENTRY_URL
        url = template.replace("{slug}", http.quote(slugify(word))).replace("{word}", http.quote(word))
        markup: Optional[str] = None
        try:
            markup = http.fetch(url, accept_language="de").text
        except http.FetchError as e:
            if e.status != 404:
                raise SourceError(f"Duden: {e}")
        if markup is None or not self._looks_like_entry(markup):
            url = self._search(word)
            if not url:
                return {"entries": [], "url": http.fill_template(SEARCH_URL, word=word)}
            try:
                markup = http.fetch(url, accept_language="de").text
            except http.FetchError as e:
                raise SourceError(f"Duden: {e}")
        entries = self.parse_entry(markup, url)
        return {"entries": entries, "url": url}

    def thesaurus(self, word: str, lang: str) -> dict:
        res = self.lookup(word, lang)
        return self.thesaurus_from_entries(res["entries"], url=res.get("url", ""))

    # -------------------------------------------------------------- search
    @staticmethod
    def _looks_like_entry(markup: str) -> bool:
        return "lemma__main" in markup or 'id="bedeutung' in markup

    def _search(self, word: str) -> Optional[str]:
        try:
            markup = http.fetch(http.fill_template(SEARCH_URL, word=word), accept_language="de").text
        except http.FetchError as e:
            raise SourceError(f"Duden search: {e}")
        return self.parse_search(markup, word)

    @staticmethod
    def parse_search(markup: str, word: str = "") -> Optional[str]:
        doc = htmlutil.parse(markup)
        links = doc.find_all("a", cls="vignette__link")
        if not links:
            links = doc.find_all("a", pred=lambda n: n.get("href", "").startswith("/rechtschreibung/"))
        best = None
        for a in links:
            href = a.get("href")
            if not href.startswith("/rechtschreibung/"):
                continue
            title = strip_marks(a.inline_text())
            if word and R.fold(title) == R.fold(word):
                return "https://www.duden.de" + href
            best = best or href
        return "https://www.duden.de" + best if best else None

    # --------------------------------------------------------------- parse
    @classmethod
    def parse_entry(cls, markup: str, url: str = "") -> List[dict]:
        doc = htmlutil.parse(markup)
        head = doc.find(cls="lemma__main") or doc.find("h1")
        headword = strip_marks(head.inline_text()) if head else ""
        extra = {}
        pos = ""
        for dl in doc.find_all("dl", cls="tuple"):
            key = ""
            for child in dl.children:
                if child.tag == "dt":
                    key = child.inline_text().rstrip(":")
                elif child.tag == "dd" and key:
                    val = child.inline_text()
                    if key.lower().startswith("wortart"):
                        pos = pos or val
                    elif key.lower() not in ("häufigkeit", "haufigkeit") and val:
                        extra.setdefault(key, val)
                    key = ""
        senses = cls._parse_senses(doc)
        synonyms = cls._parse_synonyms(doc)
        if synonyms:
            if senses:
                senses[0]["synonyms"] = R.dedupe(senses[0]["synonyms"] + synonyms)
            else:
                senses.append(R.sense("", synonyms=synonyms))
        for div_id, label in (("herkunft", "Herkunft"), ("grammatik", "Grammatik"),
                              ("aussprache", "Aussprache"), ("rechtschreibung", "Rechtschreibung")):
            div = doc.find(id=div_id)
            if div is None:
                continue
            txt = cls._division_text(div)
            if txt:
                extra.setdefault(label, txt)
        pron = ""
        pg = doc.find(cls="pronunciation-guide__text") or doc.find(cls="ipa")
        if pg is not None:
            pron = pg.inline_text()
        if not senses and not extra:
            # Generic fallback for a redesigned page: every titled block.
            for div in doc.find_all(cls="division"):
                title_el = div.find("h2") or div.find("h3")
                title = title_el.inline_text() if title_el else div.id
                txt = cls._division_text(div)
                if txt:
                    senses.append(R.sense(txt, label=title))
        if not headword and not senses:
            return []
        return [R.entry(headword, pos=pos, senses=senses, pronunciation=pron, lang="de",
                        extra=extra, url=url)]

    @staticmethod
    def _division_text(div: Node) -> str:
        parts: List[str] = []
        for child in div.children:
            if child.tag in ("header", "h2", "h3", "figure", "button", "script", "style"):
                continue
            if child.tag is None:
                continue
            txt = child.get_text()
            if txt:
                parts.append(txt)
        text = "\n".join(parts)
        return re.sub(r"\n{2,}", "\n", text).strip()

    @classmethod
    def _parse_senses(cls, doc: Node) -> List[dict]:
        senses: List[dict] = []
        block = doc.find(id="bedeutungen")
        if block is not None:
            top = block.find("ol", cls="enumeration") or block.find("ol")
            if top is not None:
                cls._walk_enumeration(top, senses, "")
        if not senses:
            single = doc.find(id="bedeutung")
            if single is not None:
                senses.extend(cls._sense_from_container(single, "1"))
        return senses

    @classmethod
    def _walk_enumeration(cls, ol: Node, senses: List[dict], prefix: str) -> None:
        idx = 0
        for li in (c for c in ol.children if c.tag == "li"):
            idx += 1
            label = f"{prefix}{idx}" if not prefix else f"{prefix}{chr(96 + idx)}"
            sub = None
            for c in li.children:
                if c.tag == "ol":
                    sub = c
                    break
            text_el = li.find(cls="enumeration__text")
            gloss = text_el.inline_text() if text_el is not None else ""
            notes = cls._collect_notes(li, stop_at=sub)
            examples = notes.pop("Beispiele", []) + notes.pop("Beispiel", [])
            syns = notes.pop("Synonyme", [])
            tags = [v for k, vals in notes.items() for v in vals if k in ("Gebrauch", "Grammatik")]
            others = {k: v for k, v in notes.items() if k not in ("Gebrauch", "Grammatik")}
            if gloss or examples or syns:
                s = R.sense(gloss, examples=examples, synonyms=syns, tags=tags, label=label)
                if others:
                    s["notes"] = {k: "; ".join(v) for k, v in others.items()}
                senses.append(s)
            if sub is not None:
                cls._walk_enumeration(sub, senses, label if gloss else prefix)

    @classmethod
    def _sense_from_container(cls, container: Node, label: str) -> List[dict]:
        gloss_parts = []
        for c in container.children:
            if c.tag in ("p", "div") and not c.has_class("note") and not c.find("dl", cls="note"):
                t = c.inline_text()
                if t:
                    gloss_parts.append(t)
        notes = cls._collect_notes(container)
        examples = notes.pop("Beispiele", []) + notes.pop("Beispiel", [])
        syns = notes.pop("Synonyme", [])
        gloss = " ".join(gloss_parts)
        if not gloss and not examples:
            return []
        return [R.sense(gloss, examples=examples, synonyms=syns, label=label,
                        tags=[v for k, vals in notes.items() for v in vals if k == "Gebrauch"])]

    @staticmethod
    def _collect_notes(container: Node, stop_at: Optional[Node] = None) -> dict:
        """``<dl class="note"><dt>Beispiele</dt><dd>...</dd></dl>`` blocks that belong
        to this sense (not to nested sub-senses)."""
        notes: dict = {}
        for dl in container.find_all("dl", cls="note"):
            # skip notes nested inside a deeper enumeration item
            owner = dl.closest("li")
            if container.tag == "li" and owner is not container:
                continue
            if stop_at is not None and any(a is stop_at for a in dl.ancestors()):
                continue
            title_el = dl.find("dt")
            title = title_el.inline_text() if title_el is not None else "Anmerkung"
            body = dl.find("dd")
            if body is None:
                continue
            items = [li.inline_text() for li in body.find_all("li")]
            if not items:
                items = [body.inline_text()]
            if title in ("Synonyme",):
                items = _split_synonyms(items)
            notes.setdefault(title, []).extend(i for i in items if i)
        return notes

    @staticmethod
    def _parse_synonyms(doc: Node) -> List[str]:
        block = doc.find(id="synonyme")
        if block is None:
            return []
        items = [li.inline_text() for li in block.find_all("li")]
        if not items:
            items = [a.inline_text() for a in block.find_all("a")]
        if not items:
            body = Duden._division_text(block)
            items = [body] if body else []
        return _split_synonyms(items)


def _split_synonyms(items: List[str]) -> List[str]:
    out: List[str] = []
    for it in items:
        it = re.sub(r"\((?:[^()]*)\)", "", it)  # drop usage remarks in parentheses
        for part in re.split(r"[,;]\s*", it):
            part = part.strip(" .")
            if part and len(part) < 60:
                out.append(part)
    return R.dedupe(out)
