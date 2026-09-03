"""LEO (dict.leo.org) word translation.

LEO has no public API, but the query endpoint its own apps use returns XML
and is much easier to parse than the website.  We try that first and fall
back to scraping the HTML result page.  Only ``xx <-> de`` pairs exist.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import List, Optional, Tuple

from .. import http, htmlutil, languages
from .. import results as R
from .base import Source, SourceError, register

XML_URL = ("https://dict.leo.org/dictQuery/m-vocab/{lp}/query.xml?tolerMode=nof&lp={lp}"
           "&lang=de&rmWords=off&rmSearch=on&search={word}&searchLoc=0&resultOrder=basic"
           "&multiwordShowSingle=on&pos=0&sectLen=16&sectHdr=on&partial=show&spellToler=on")

HTML_PATHS = {
    "en": "englisch-deutsch", "fr": "französisch-deutsch", "es": "spanisch-deutsch",
    "it": "italienisch-deutsch", "zh": "chinesisch-deutsch", "ru": "russisch-deutsch",
    "pt": "portugiesisch-deutsch", "pl": "polnisch-deutsch",
}

SECTION_TITLES = {
    "subst": "Nouns", "verb": "Verbs", "adjadv": "Adjectives / Adverbs",
    "praep": "Prepositions", "phrase": "Phrases", "example": "Examples",
    "definition": "Definitions", "abbrev": "Abbreviations",
}


@register
class Leo(Source):
    driver = "leo"
    label = "LEO (dict.leo.org)"
    kind = "remote"
    types = ("translator",)
    description = "Word-by-word translations between German and English/French/Spanish/Italian/Chinese/Russian/Portuguese/Polish."
    default_url = "https://dict.leo.org/"
    translation_modes = ("word",)
    languages = ("de", "en", "fr", "es", "it", "zh", "ru", "pt", "pl")
    pairs = tuple([("de", x) for x in HTML_PATHS] + [(x, "de") for x in HTML_PATHS])
    order = 40

    # ---------------------------------------------------------------- api
    @staticmethod
    def pair_code(src: str, dst: str) -> Tuple[str, str]:
        """Return (lp, foreign) e.g. ('ende', 'en') for any de<->xx pair."""
        other = dst if src == "de" else src
        if "de" not in (src, dst) or other not in HTML_PATHS:
            raise SourceError("LEO only translates between German and " +
                              ", ".join(languages.name(c) for c in HTML_PATHS))
        return languages.leo_code(other) + "de", other

    def translate(self, text: str, src: str, dst: str) -> dict:
        lp, other = self.pair_code(src, dst)
        word = text.strip()
        page_url = f"https://dict.leo.org/{HTML_PATHS[other]}/{http.quote(word)}"
        errors: List[str] = []
        try:
            resp = http.fetch(http.fill_template(XML_URL, lp=lp, word=word))
            pairs = self.parse_xml(resp.text, src, dst)
            if pairs:
                return R.translation("word", pairs, url=page_url)
            errors.append("no XML results")
        except (http.FetchError, ET.ParseError) as e:
            errors.append(str(e))
        try:
            resp = http.fetch(page_url, accept_language="de,en;q=0.8")
            pairs = self.parse_html(resp.text, src, dst)
            if pairs:
                return R.translation("word", pairs, url=page_url)
        except http.FetchError as e:
            errors.append(str(e))
        if errors:
            raise SourceError("LEO: " + "; ".join(errors))
        return R.translation("word", [], url=page_url)

    # -------------------------------------------------------------- parse
    @staticmethod
    def _side_text(side: ET.Element) -> str:
        repr_el = side.find("repr")
        if repr_el is not None:
            txt = "".join(repr_el.itertext())
        else:
            txt = " ".join(w.text or "" for w in side.iter("word"))
        return R.clean(txt)

    @classmethod
    def parse_xml(cls, xml_text: str, src: str, dst: str) -> List[dict]:
        root = ET.fromstring(xml_text)
        src_leo = "de" if src == "de" else languages.leo_code(src)
        dst_leo = "de" if dst == "de" else languages.leo_code(dst)
        out: List[dict] = []
        for section in root.iter("section"):
            name = section.get("sctName", "")
            title = section.get("sctTitle") or SECTION_TITLES.get(name, name)
            for entry in section.iter("entry"):
                sides = entry.findall("side")
                if len(sides) < 2:
                    continue
                by_lang = {}
                for s in sides:
                    by_lang[s.get("lang", "")] = cls._side_text(s)
                a = by_lang.get(src_leo) or cls._side_text(sides[0])
                b = by_lang.get(dst_leo) or cls._side_text(sides[1])
                if a and b:
                    out.append(R.pair(a, b, pos=title))
        return out

    @classmethod
    def parse_html(cls, markup: str, src: str, dst: str) -> List[dict]:
        doc = htmlutil.parse(markup)
        src_leo = "de" if src == "de" else languages.leo_code(src)
        dst_leo = "de" if dst == "de" else languages.leo_code(dst)
        out: List[dict] = []
        for row in doc.find_all("tr", attrs={"data-dz-ui": "dictentry"}):
            cells = row.find_all("td", pred=lambda n: bool(n.get("lang")))
            texts = {}
            for c in cells:
                texts.setdefault(c.get("lang"), R.clean(c.inline_text()))
            a, b = texts.get(src_leo), texts.get(dst_leo)
            if not (a and b) and len(cells) >= 2:
                a, b = R.clean(cells[0].inline_text()), R.clean(cells[1].inline_text())
            if a and b:
                table = row.closest("table")
                title = ""
                if table is not None:
                    m = re.match(r"section-(\w+)", table.id or "")
                    if m:
                        title = SECTION_TITLES.get(m.group(1), m.group(1))
                out.append(R.pair(a, b, pos=title))
        return out
