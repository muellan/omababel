"""Thesaurus.com – English synonyms and antonyms.

The page embeds its data as JSON (``"synonyms":[{"term":...}]``), so we
harvest every such blob first; the DOM (``data-type="synonym-list"`` /
``#meanings`` / ``#antonyms``) is the fallback.
"""

from __future__ import annotations

import json
import re
from typing import List, Tuple

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
        syn, ant = self.parse(markup)
        return R.thesaurus(syn, ant, url=url)

    # --------------------------------------------------------------- parse
    @classmethod
    def parse(cls, markup: str) -> Tuple[List[str], List[str]]:
        syn, ant = cls._from_json(markup)
        if not syn and not ant:
            syn, ant = cls._from_dom(markup)
        return R.dedupe(syn), R.dedupe(ant)

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

    @classmethod
    def _from_json(cls, markup: str) -> Tuple[List[str], List[str]]:
        syn: List[str] = []
        ant: List[str] = []
        candidates = [markup]
        if '\\"synonyms\\"' in markup or '\\"antonyms\\"' in markup:
            # JSON embedded inside a JS string literal (Next.js flight data)
            candidates.append(markup.replace('\\"', '"'))
        for text in candidates:
            for key, target in (('"synonyms":', syn), ('"antonyms":', ant)):
                start = 0
                while True:
                    idx = text.find(key, start)
                    if idx < 0:
                        break
                    blob = htmlutil.find_json_blob(text[idx:], key)
                    if blob:
                        target.extend(cls._terms(blob))
                        start = idx + len(key) + len(blob)
                    else:
                        start = idx + len(key)
            if syn or ant:
                break
        return syn, ant

    @staticmethod
    def _from_dom(markup: str) -> Tuple[List[str], List[str]]:
        doc = htmlutil.parse(markup)
        syn: List[str] = []
        ant: List[str] = []

        def links(node) -> List[str]:
            return [a.inline_text() for a in node.find_all("a")
                    if "/browse/" in a.get("href", "") and a.inline_text()]

        for node in doc.find_all(attrs={"data-type": "synonym-list"}):
            syn.extend(links(node))
        for node in doc.find_all(attrs={"data-type": "antonym-list"}):
            ant.extend(links(node))
        if not syn:
            m = doc.find(id="meanings")
            if m is not None:
                syn.extend(links(m))
        if not ant:
            a = doc.find(id="antonyms")
            if a is not None:
                ant.extend(links(a))
        if not syn:
            # Last resort: every browse link outside nav/footer, grouped by
            # the heading text above it.
            for a in doc.find_all("a", pred=lambda n: "/browse/" in n.get("href", "")):
                if a.closest("nav") or a.closest("footer") or a.closest("header"):
                    continue
                syn.append(a.inline_text())
        return syn, ant
