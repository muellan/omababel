"""Thesaurus.com – English synonyms and antonyms.

The page embeds its data as JSON (``"synonyms":[{"term":...}]``), so we
harvest every such blob first; the DOM (``data-type="synonym-list"`` /
``#meanings`` / ``#antonyms``) is the fallback.
"""

from __future__ import annotations

import json
import re
from typing import List, Optional, Tuple

from .. import http, htmlutil
from .. import results as R
from .base import Source, SourceError, register

URL = "https://www.thesaurus.com/browse/{word}"


@register
class ThesaurusCom(Source):
    driver = "thesauruscom"
    label = "Thesaurus.com"
    kind = "remote"
    types = ("thesaurus",)
    description = "English synonyms and antonyms from thesaurus.com."
    default_url = URL
    languages = ("en",)
    order = 20

    def thesaurus(self, word: str, lang: str) -> dict:
        word = word.strip()
        template = self.url if "{word}" in self.url else URL
        url = http.fill_template(template, word=word)
        try:
            markup = http.fetch(url).text
        except http.FetchError as e:
            if e.status == 404:
                return R.thesaurus([], [], url=url)
            raise SourceError(f"Thesaurus.com: {e}")
        groups = self.parse_groups(markup)
        return R.thesaurus([], [], url=url, groups=groups)

    # --------------------------------------------------------------- parse
    @classmethod
    def parse(cls, markup: str) -> Tuple[List[str], List[str]]:
        """Flat synonym / antonym lists (all meanings merged)."""
        groups = cls.parse_groups(markup)
        syn = [w for g in groups for w in g["synonyms"]]
        ant = [w for g in groups for w in g["antonyms"]]
        return R.dedupe(syn), R.dedupe(ant)

    @classmethod
    def parse_groups(cls, markup: str) -> List[dict]:
        """One group per meaning (``pos`` + ``definition``), like the site."""
        groups = cls._from_json(markup)
        if not groups:
            groups = cls._from_dom(markup)
        return [g for g in groups if g["synonyms"] or g["antonyms"]]

    @staticmethod
    def _terms(blob: str) -> List[str]:
        try:
            data = json.loads(blob)
        except ValueError:
            # JSON may be inside a JS string with escaped quotes
            try:
                data = json.loads(blob.replace('\\"', '"'))
            except ValueError:
                return []
        out: List[str] = []
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    term = item.get("term") or item.get("word") or item.get("targetTerm")
                    if isinstance(term, str):
                        out.append(term)
                elif isinstance(item, str):
                    out.append(item)
        return out

    _LABEL_KEYS = (re.compile(r'"definition"\s*:\s*"((?:[^"\\]|\\.)*)"'),
                   re.compile(r'"pos"\s*:\s*"((?:[^"\\]|\\.)*)"'))

    @classmethod
    def _from_json(cls, markup: str) -> List[dict]:
        """Harvest ``"synonyms":[…]`` / ``"antonyms":[…]`` blobs in document
        order; each synonyms blob opens a new meaning whose definition/pos are
        the nearest such keys just before it."""
        candidates = [markup]
        if '\\"synonyms\\"' in markup or '\\"antonyms\\"' in markup:
            # JSON embedded inside a JS string literal (Next.js flight data)
            candidates.append(markup.replace('\\"', '"'))
        for text in candidates:
            groups: List[dict] = []
            current: Optional[dict] = None
            pos_idx = 0
            while True:
                s_idx = text.find('"synonyms":', pos_idx)
                a_idx = text.find('"antonyms":', pos_idx)
                if s_idx < 0 and a_idx < 0:
                    break
                if a_idx < 0 or (0 <= s_idx < a_idx):
                    idx, key, is_syn = s_idx, '"synonyms":', True
                else:
                    idx, key, is_syn = a_idx, '"antonyms":', False
                blob = htmlutil.find_json_blob(text[idx:], key)
                pos_idx = idx + len(key) + (len(blob) if blob else 0)
                if not blob:
                    continue
                terms = cls._terms(blob)
                if is_syn or current is None:
                    window = text[max(0, idx - 600):idx]
                    label = ""
                    pos = ""
                    m = list(cls._LABEL_KEYS[0].finditer(window))
                    if m:
                        label = m[-1].group(1)
                    m = list(cls._LABEL_KEYS[1].finditer(window))
                    if m:
                        pos = m[-1].group(1)
                    current = R.group([], [], label=label.replace('\\"', '"'), pos=pos)
                    groups.append(current)
                if is_syn:
                    current["synonyms"] = R.dedupe(current["synonyms"] + terms)
                else:
                    current["antonyms"] = R.dedupe(current["antonyms"] + terms)
            groups = [g for g in groups if g["synonyms"] or g["antonyms"]]
            if groups:
                return groups
        return []

    _STOP = re.compile(r"(?i)^(related words|words? (related|nearby)|browse|trending|word of the day|"
                       r"example sentences|frequently asked|compare|on this page)")
    _STRENGTH = re.compile(r"(?i)^(strongest|strong|weak)(est)?( matches?)?$")

    @classmethod
    def _from_dom(cls, markup: str) -> List[dict]:
        """Walk the page in document order.

        thesaurus.com lists every meaning as "<pos> / <definition> / Synonyms /
        <strength> words… / Antonyms / <strength> words…", so a link belongs to
        whichever "Synonyms" or "Antonyms" label preceded it, and the two
        labels before "Synonyms" name the meaning.  Links before the first
        such label, in navigation chrome, and everything from "Related Words"
        on are ignored.
        """
        doc = htmlutil.parse(markup)
        groups: List[dict] = []
        syn_nodes = doc.find_all(attrs={"data-type": "synonym-list"})
        ant_nodes = doc.find_all(attrs={"data-type": "antonym-list"})
        if syn_nodes or ant_nodes:
            g = R.group([w for n in syn_nodes for w in cls._links(n)], [w for n in ant_nodes for w in cls._links(n)])
            return [g]

        current: Optional[dict] = None
        target: Optional[str] = None
        recent: List[str] = []       # short labels seen since the last word list
        last_label = ""              # nested wrappers repeat the same text
        for node in doc.elements():
            if node.tag in ("nav", "footer", "header", "script", "style"):
                continue
            if node.closest("nav") or node.closest("footer") or node.closest("header"):
                continue
            if node.tag == "a":
                if current is not None and target and "/browse/" in node.get("href", ""):
                    word = node.inline_text()
                    if word:
                        current[target].append(word)
                continue
            if node.tag in ("h1", "h2", "h3", "h4", "h5", "h6", "p", "strong", "span", "div", "button"):
                if any(c.tag in ("a", "ul", "ol", "div", "section") for c in node.children):
                    continue
                label = node.inline_text()
                if not label or len(label) > 60:
                    continue
                if label == last_label:
                    continue
                last_label = label
                low = label.lower()
                if cls._STOP.match(label):
                    break
                if cls._STRENGTH.match(label):
                    continue
                if low.startswith("synonym"):
                    pos = recent[-2] if len(recent) >= 2 else ""
                    definition = recent[-1] if recent else ""
                    if pos and not (len(pos) <= 12 and pos.isupper()) and not definition:
                        definition, pos = pos, ""
                    current = R.group([], [], label=definition, pos=pos.lower() if pos.isupper() else pos)
                    groups.append(current)
                    target = "synonyms"
                    recent = []
                elif low.startswith("antonym"):
                    if current is None:
                        current = R.group([], [])
                        groups.append(current)
                    target = "antonyms"
                    recent = []
                else:
                    recent.append(label)
                    recent = recent[-2:]
        for g in groups:
            g["synonyms"] = R.dedupe(g["synonyms"])
            g["antonyms"] = R.dedupe(g["antonyms"])
        return groups

    @staticmethod
    def _links(node) -> List[str]:
        return [a.inline_text() for a in node.find_all("a")
                if "/browse/" in a.get("href", "") and a.inline_text()]
