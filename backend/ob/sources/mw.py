"""Merriam-Webster – English dictionary and thesaurus.

* With an API key (free at dictionaryapi.com; one key per reference):
  the Collegiate dictionary or Collegiate thesaurus JSON API.
* Without one: the public entry pages ``/dictionary/<word>`` and
  ``/thesaurus/<word>``.
"""

from __future__ import annotations

import re
from typing import List, Optional

from .. import http, htmlutil
from .. import results as R
from ..htmlutil import Node
from .base import Source, SourceError, register

DICT_URL = "https://www.merriam-webster.com/dictionary/{word}"
THES_URL = "https://www.merriam-webster.com/thesaurus/{word}"
API_DICT = "https://www.dictionaryapi.com/api/v3/references/collegiate/json/{word}?key={key}"
API_THES = "https://www.dictionaryapi.com/api/v3/references/thesaurus/json/{word}?key={key}"

_TOKEN = re.compile(r"\{[^}]*\}")


def strip_tokens(text: str) -> str:
    """Remove MW API markup tokens like ``{bc}``, ``{it}``, ``{a_link|word}``."""
    def repl(m: re.Match) -> str:
        body = m.group(0)[1:-1]
        if "|" in body:
            parts = body.split("|")
            if parts[0] in ("a_link", "d_link", "i_link", "et_link", "mat", "sx", "dxt"):
                return parts[1]
        return ""
    return R.clean(_TOKEN.sub(repl, text))


@register
class MerriamWebster(Source):
    driver = "mw"
    label = "Merriam-Webster"
    kind = "remote"
    types = ("dictionary", "thesaurus")
    description = "English definitions (and synonyms/antonyms in thesaurus rows) from merriam-webster.com; optional dictionaryapi.com key."
    default_url = DICT_URL
    supports_key = True
    key_hint = "dictionaryapi.com key (collegiate or thesaurus, optional)"
    languages = ("en",)
    order = 11

    # ------------------------------------------------------------- lookup
    def lookup(self, word: str, lang: str) -> dict:
        word = word.strip()
        url = http.fill_template(DICT_URL, word=word)
        if self.api_key:
            return {"entries": self._api_lookup(word), "url": url}
        template = self.url if "{word}" in self.url else DICT_URL
        try:
            markup = http.fetch(http.fill_template(template, word=word)).text
        except http.FetchError as e:
            if e.status == 404:
                return {"entries": [], "url": url}
            raise SourceError(f"Merriam-Webster: {e}")
        return {"entries": self.parse_dictionary(markup, url), "url": url}

    def thesaurus(self, word: str, lang: str) -> dict:
        word = word.strip()
        url = http.fill_template(THES_URL, word=word)
        if self.api_key:
            return self._api_thesaurus(word, url)
        template = self.url if ("{word}" in self.url and "thesaurus" in self.url) else THES_URL
        try:
            markup = http.fetch(http.fill_template(template, word=word)).text
        except http.FetchError as e:
            if e.status == 404:
                return R.thesaurus([], [], url=url)
            raise SourceError(f"Merriam-Webster thesaurus: {e}")
        return R.thesaurus([], [], url=url, groups=self.parse_thesaurus_groups(markup))

    # ---------------------------------------------------------------- api
    def _api_get(self, template: str, word: str):
        try:
            resp = http.fetch(template.replace("{word}", http.quote(word)).replace("{key}", http.quote(self.api_key)),
                              headers={"Accept": "application/json"})
            return resp.json()
        except http.FetchError as e:
            raise SourceError(f"Merriam-Webster API: {e}")
        except ValueError:
            raise SourceError("Merriam-Webster API: invalid JSON (bad key?)")

    def _api_lookup(self, word: str) -> List[dict]:
        data = self._api_get(API_DICT, word)
        return self.parse_api_dictionary(data, word)

    def _api_thesaurus(self, word: str, url: str) -> dict:
        data = self._api_get(API_THES, word)
        syn, ant = self.parse_api_thesaurus(data, word)
        return R.thesaurus(syn, ant, url=url)

    @staticmethod
    def parse_api_dictionary(data, word: str) -> List[dict]:
        entries: List[dict] = []
        if not isinstance(data, list):
            return entries
        for item in data:
            if not isinstance(item, dict):
                continue  # spelling suggestions come back as bare strings
            hw = str(item.get("hwi", {}).get("hw", "")).replace("*", "")
            if word and R.fold(hw) != R.fold(word) and not R.fold(word).startswith(R.fold(hw)):
                # keep only entries for the looked-up headword family
                if not hw.startswith(word.lower()):
                    continue
            prs = item.get("hwi", {}).get("prs") or []
            pron = prs[0].get("mw", "") if prs and isinstance(prs[0], dict) else ""
            senses: List[dict] = []
            for d in item.get("def") or []:
                for sseq in d.get("sseq") or []:
                    for sense_pair in sseq:
                        if not (isinstance(sense_pair, list) and len(sense_pair) == 2):
                            continue
                        kind, body = sense_pair
                        if kind not in ("sense", "sen", "bs") or not isinstance(body, dict):
                            if kind == "bs" and isinstance(body, dict):
                                body = body.get("sense", {})
                            else:
                                continue
                        gloss_parts, examples = [], []
                        for dt in body.get("dt") or []:
                            if not (isinstance(dt, list) and len(dt) == 2):
                                continue
                            if dt[0] == "text":
                                gloss_parts.append(strip_tokens(dt[1]))
                            elif dt[0] == "vis" and isinstance(dt[1], list):
                                examples.extend(strip_tokens(v.get("t", "")) for v in dt[1] if isinstance(v, dict))
                        gloss = " ".join(p for p in gloss_parts if p)
                        if gloss:
                            senses.append(R.sense(gloss, examples=examples, label=str(body.get("sn", ""))))
            if not senses:
                senses = [R.sense(s) for s in item.get("shortdef") or []]
            if senses:
                entries.append(R.entry(hw or word, pos=str(item.get("fl", "")), senses=senses,
                                       pronunciation=pron, lang="en"))
        return entries

    @staticmethod
    def parse_api_thesaurus(data, word: str):
        syn: List[str] = []
        ant: List[str] = []
        if isinstance(data, list):
            for item in data:
                if not isinstance(item, dict):
                    continue
                meta = item.get("meta", {})
                for group in meta.get("syns") or []:
                    syn.extend(group)
                for group in meta.get("ants") or []:
                    ant.extend(group)
        return R.dedupe(syn), R.dedupe(ant)

    # -------------------------------------------------------------- scrape
    @classmethod
    def parse_dictionary(cls, markup: str, url: str = "") -> List[dict]:
        doc = htmlutil.parse(markup)
        containers = doc.find_all(cls="entry-word-section-container")
        if not containers:
            containers = [doc]
        entries: List[dict] = []
        for c in containers:
            hw_el = c.find(cls="hword")
            headword = hw_el.inline_text() if hw_el else ""
            pos_el = c.find(cls="parts-of-speech") or c.find(cls="fl")
            pos = pos_el.inline_text() if pos_el else ""
            pos = re.sub(r"\s*\(\d+ of \d+\)\s*$", "", pos)
            pr_el = c.find(cls="pr") or c.find(cls="mw")
            pron = pr_el.inline_text() if pr_el else ""
            senses: List[dict] = []
            for dt in c.find_all(cls="dtText"):
                gloss = dt.inline_text()
                gloss = re.sub(r"^:\s*", "", gloss)
                sense_el = dt.closest(cls="sense") or dt.closest("div")
                label = ""
                examples: List[str] = []
                if sense_el is not None:
                    sn = sense_el.find(cls="sn")
                    if sn is not None:
                        label = sn.inline_text()
                    examples = [e.inline_text() for e in sense_el.find_all(cls="ex-sent")]
                    if not label:
                        item = sense_el.closest(cls="vg-sseq-entry-item")
                        if item is not None:
                            lab = item.find(cls="vg-sseq-entry-item-label")
                            if lab is not None:
                                label = lab.inline_text()
                if gloss:
                    senses.append(R.sense(gloss, examples=examples, label=label))
            if not senses:
                continue
            # "Synonyms" box on the dictionary page, if present
            syn_box = c.find(id="synonyms") or doc.find(id="synonyms")
            if syn_box is not None and c is containers[0]:
                syns = [a.inline_text() for a in syn_box.find_all("a")
                        if "/dictionary/" in a.get("href", "") or "/thesaurus/" in a.get("href", "")]
                if syns:
                    senses[0]["synonyms"] = R.dedupe(syns)
            entries.append(R.entry(headword, pos=pos, senses=senses, pronunciation=pron,
                                   lang="en", url=url))
        return entries

    @classmethod
    def parse_thesaurus(cls, markup: str):
        """Flat synonym / antonym lists (all meanings merged)."""
        groups = cls.parse_thesaurus_groups(markup)
        return (R.dedupe(w for g in groups for w in g["synonyms"]),
                R.dedupe(w for g in groups for w in g["antonyms"]))

    _AS_IN = re.compile(r"(?i)^as in\b")

    @classmethod
    def parse_thesaurus_groups(cls, markup: str) -> List[dict]:
        """One group per meaning.  MW labels meanings "as in <word>"; the
        label preceding a synonym list names the group, an antonym list joins
        the group opened by the synonym list before it."""
        doc = htmlutil.parse(markup)

        def words_in(node: Node) -> List[str]:
            # "Definitions" is MW's link back to the dictionary entry, not a word.
            anchors = [a for a in node.find_all("a") if "/dictionary/" not in a.get("href", "")]
            out = [a.inline_text() for a in anchors]
            if not out and not node.find_all("a"):
                out = [li.inline_text() for li in node.find_all("li")]
            return [w for w in out if w and len(w) < 60 and not re.match(r"(?i)^definitions?$", w)]

        def heading_kind(text: str) -> str:
            low = text.strip().lower()
            if low.startswith("antonym") or low.startswith("near antonym") or low.startswith("opposite"):
                return "antonyms"
            if low.startswith("synonym") or low.startswith("similar"):
                return "synonyms"
            return ""

        groups: List[dict] = []
        current: Optional[dict] = None
        pending_label = ""
        pending_pos = ""
        pending_kind = ""        # "Synonyms…" / "Antonyms…" heading seen since the last list
        handled = set()
        for node in doc.elements():
            if any(id(a) in handled for a in node.ancestors()):
                continue
            cls_ = " ".join(node.classes)
            text = node.inline_text() if node.tag in ("p", "span", "h2", "h3", "h4", "div", "strong", "em") else ""
            if text and len(text) < 80 and cls._AS_IN.match(text) and not node.find("a"):
                pending_label = text
                continue
            if text and len(text) < 60 and re.match(r"(?i)^synonyms? of\b|^synonyms?\s*\(", text) and not node.find("a"):
                m = re.search(r"\(([^)]+)\)", text)
                if m:
                    pending_pos = m.group(1)
                continue
            if text and len(text) < 60 and not node.find("a") and heading_kind(text):
                pending_kind = heading_kind(text)
                continue
            if not cls_:
                continue
            is_syn_cls = bool(re.search(r"\b(synonyms_list|syn-list|synonym-list)\b", cls_))
            is_ant_cls = bool(re.search(r"\b(antonyms_list|ant-list|antonym-list)\b", cls_)) and "near" not in cls_
            if not (is_syn_cls or is_ant_cls):
                continue
            handled.add(id(node))
            words = words_in(node)
            # A heading inside the list box ("Antonyms & Near Antonyms") or the
            # last heading before it decides; the class is only the fallback –
            # MW uses the synonym list class for antonym boxes too.
            inner = ""
            for child in node.elements():
                t = child.inline_text() if child.tag in ("span", "p", "h2", "h3", "h4", "div", "strong") else ""
                if t and len(t) < 60 and not child.find("a") and heading_kind(t):
                    inner = heading_kind(t)
                    break
            kind = inner or pending_kind or ("antonyms" if is_ant_cls else "synonyms")
            pending_kind = ""
            if not words:
                continue
            if kind == "synonyms":
                current = R.group(words, [], label=pending_label, pos=pending_pos)
                groups.append(current)
                pending_label = ""
            else:
                if current is None or (pending_label and pending_label != current["label"]):
                    current = R.group([], [], label=pending_label, pos=pending_pos)
                    groups.append(current)
                    pending_label = ""
                current["antonyms"] = R.dedupe(current["antonyms"] + words)
        if not groups:
            # Newer layout: headings "Synonyms of X" / "Antonyms of X" followed by lists.
            syn: List[str] = []
            ant: List[str] = []
            for h in doc.find_all("h2,h3,p", pred=lambda n: bool(re.match(r"(?i)^(synonyms|antonyms)\b", n.inline_text()))):
                target = syn if h.inline_text().lower().startswith("syn") else ant
                sib = h.parent
                if sib is None:
                    continue
                lst = None
                seen_h = False
                for ch in sib.children:
                    if ch is h:
                        seen_h = True
                        continue
                    if seen_h and ch.tag in ("ul", "div", "ol"):
                        lst = ch
                        break
                if lst is not None:
                    target.extend(words_in(lst))
            if syn or ant:
                groups.append(R.group(syn, ant))
        return [g for g in groups if g["synonyms"] or g["antonyms"]]
