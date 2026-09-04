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
    # Everything from these sections on is navigation, not thesaurus content.
    _THES_STOP = re.compile(r"(?i)^(phrases? containing|articles? related|thesaurus entries near|"
                            r"dictionary entries near|browse the|word history|examples? of|"
                            r"frequently asked|see definition|love words|share|test your)")
    _ANTONYM_HEAD = re.compile(r"(?i)^\s*(near\s+)?(antonyms?|opposites?)\b")
    _SYNONYM_HEAD = re.compile(r"(?i)^\s*(synonyms?|similar words|strongest matches?)\b")
    _JUNK_WORD = re.compile(r"(?i)^(definitions?|synonyms?|antonyms?|see more|show more)$")
    # A box holding a word list.  MW uses the *same* class for the synonym and
    # the antonym box of a sense, so the class alone can only ever be a hint.
    _LIST_CLS = re.compile(r"(?i)\b(?:thes-list(?:-content)?|(?:near[-_])?(?:syn|ant)(?:onyms?)?[-_]list)\b")
    _ANT_CLS = re.compile(r"(?i)\b(?:near[-_])?ant(?:onyms?)?[-_]list\b")
    _SYN_CLS = re.compile(r"(?i)\bsyn(?:onyms?)?[-_]list\b")
    # Containers MW wraps one meaning in.
    _SENSE_CLS = re.compile(r"(?i)\b(?:sense(?:-content)?|thesaurus-entry|sense-\d+)\b")

    @classmethod
    def _heading_kind(cls, text: str) -> str:
        if cls._ANTONYM_HEAD.match(text):
            return "antonyms"
        if cls._SYNONYM_HEAD.match(text):
            return "synonyms"
        return ""

    @staticmethod
    def _leading_text(node: Node, limit: int = 80) -> str:
        """The text a node starts with, stopping at the first word list – so a
        heading is still readable when it shares its element with the words."""
        out: List[str] = []
        for child in node.children:
            if child.tag is None:
                out.append(child.text)
            elif child.tag in ("ul", "ol", "dl", "table"):
                break
            elif child.tag == "a":
                break
            else:
                out.append(MerriamWebster._leading_text(child, limit))
            if sum(len(p) for p in out) > limit:
                break
        return R.clean("".join(out))[:limit]

    @classmethod
    def _box_kind(cls, node: Node) -> str:
        """Kind of a word box from a heading inside it (or the text it starts
        with).  Only positive evidence is reported – "" means "cannot tell"."""
        kind = cls._heading_kind(cls._leading_text(node))
        if kind:
            return kind
        for child in node.elements():
            if child.tag in ("ul", "ol", "li", "a"):
                continue
            t = cls._leading_text(child, 60)
            if t:
                kind = cls._heading_kind(t)
                if kind:
                    return kind
        return ""

    @classmethod
    def _words_in(cls, node: Node) -> List[str]:
        """The words of a box.  MW links every word to /thesaurus/<word>;
        "Definitions" and friends link back to the dictionary."""
        anchors = node.find_all("a")
        words = [a.inline_text() for a in anchors if "/thesaurus/" in a.get("href", "")]
        if not words:
            words = [a.inline_text() for a in anchors if "/dictionary/" not in a.get("href", "")]
        if not words and not anchors:
            words = [li.inline_text() for li in node.find_all("li")]
        return [w for w in words if w and len(w) < 60 and not cls._JUNK_WORD.match(w)]

    @classmethod
    def _repair_groups(cls, groups: List[dict]) -> List[dict]:
        """Last line of defence against an antonym box read as synonyms.

        MW repeats a sense's antonyms in the entry-wide "Antonyms & Near
        Antonyms" box, so a group whose synonyms are words another group of the
        same page already lists as antonyms – and that nothing lists as
        synonyms – is an antonym box that lost its heading.
        """
        if len(groups) < 2:
            return groups
        for i, g in enumerate(groups):
            words = g["synonyms"]
            if len(words) < 2 or g["antonyms"]:
                continue
            others = [o for j, o in enumerate(groups) if j != i]
            ants = {R.fold(w) for o in others for w in o["antonyms"]}
            syns = {R.fold(w) for o in others for w in o["synonyms"]}
            keys = [R.fold(w) for w in words]
            if not ants or any(k in syns for k in keys):
                continue
            if sum(1 for k in keys if k in ants) >= max(2, (len(keys) + 1) // 2):
                g["antonyms"], g["synonyms"] = words, []
        # An unlabelled antonyms-only box is MW's entry-wide "Antonyms & Near
        # Antonyms": it belongs to the meaning above it, not on a card of its own.
        out: List[dict] = []
        for g in groups:
            if not g["synonyms"] and not g["label"] and out and out[-1]["pos"] == g["pos"]:
                out[-1]["antonyms"] = R.dedupe(out[-1]["antonyms"] + g["antonyms"])
                continue
            out.append(g)
        return [g for g in out if g["synonyms"] or g["antonyms"]]

    @classmethod
    def parse_thesaurus_groups(cls, markup: str) -> List[dict]:
        """One group per meaning.

        MW labels a meaning "as in <word>" and then shows a "Synonyms & Similar
        Words" box and an "Antonyms & Near Antonyms" box – *both* carrying the
        synonym list class, so the class can never decide which is which.  The
        kind of a box is therefore taken from, in order: a heading inside it,
        the heading standing before it, an unambiguous *antonym* class, and its
        position in the meaning (MW puts the synonyms first).  A box that none
        of that can place is dropped rather than guessed at – listing antonyms
        as synonyms is much worse than losing a box.  Word lists after "Phrases
        Containing" and friends are page navigation and stop the walk.
        """
        doc = htmlutil.parse(markup)

        groups: List[dict] = []
        current: Optional[dict] = None       # group being filled
        current_sense = None                 # id() of its sense container
        pending_label = ""
        pending_pos = ""
        pending_kind = ""        # "Synonyms…" / "Antonyms…" heading seen since the last box
        handled = set()

        def sense_of(node: Node):
            for a in node.ancestors():
                if a.tag is not None and cls._SENSE_CLS.search(" ".join(a.classes)):
                    return id(a)
            return None

        for node in doc.elements():
            if any(id(a) in handled for a in node.ancestors()):
                continue
            classes = " ".join(node.classes)
            is_box = bool(classes) and bool(cls._LIST_CLS.search(classes))
            if not is_box:
                if node.tag not in ("p", "span", "h1", "h2", "h3", "h4", "h5", "div", "strong", "em", "label", "dt"):
                    continue
                text = cls._leading_text(node)
                if not text:
                    continue
                if cls._THES_STOP.match(text):
                    break
                if cls._AS_IN.match(text):
                    pending_label = text
                elif re.match(r"(?i)^synonyms? of\b|^synonyms?\s*\(", text):
                    m = re.search(r"\(([^)]+)\)", text)
                    if m:
                        pending_pos = m.group(1)
                    # "Synonyms of house" is the entry heading, not a box heading
                else:
                    kind = cls._heading_kind(text)
                    if kind:
                        pending_kind = kind
                continue

            handled.add(id(node))
            words = cls._words_in(node)
            if not words:
                continue
            sense = sense_of(node)
            new_sense = current is None or sense != current_sense or (pending_label and pending_label != current["label"])
            kind = cls._box_kind(node) or pending_kind
            pending_kind = ""
            if not kind and cls._ANT_CLS.search(classes):
                kind = "antonyms"
            elif not kind and new_sense:
                kind = "synonyms"                        # MW puts the synonyms first
            elif not kind and cls._SYN_CLS.search(classes):
                kind = "antonyms"                        # the second "synonym" box of a meaning
            if not kind:
                continue                                 # unplaceable: better dropped than guessed
            if kind == "synonyms":
                if new_sense or current["synonyms"]:
                    current = R.group(words, [], label=pending_label, pos=pending_pos)
                    current_sense = sense
                    groups.append(current)
                    pending_label = ""
                else:
                    current["synonyms"] = R.dedupe(current["synonyms"] + words)
            else:
                if new_sense:
                    current = R.group([], [], label=pending_label, pos=pending_pos)
                    current_sense = sense
                    groups.append(current)
                    pending_label = ""
                current["antonyms"] = R.dedupe(current["antonyms"] + words)
        groups = cls._repair_groups(groups)
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
                    target.extend(cls._words_in(lst))
            if syn or ant:
                groups.append(R.group(syn, ant))
        return [g for g in groups if g["synonyms"] or g["antonyms"]]
