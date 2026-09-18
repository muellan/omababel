"""Acronym and abbreviation dictionaries.

Three sites, one shape of answer: an acronym and the things it can stand
for, often with a subject category.  They are dictionary sources, so they
answer in *lookup* mode alongside Duden, Merriam-Webster and the rest.

They are only asked when the search term actually looks like an acronym
(see :func:`looks_like_acronym`) -- a short, capital-heavy token.  Every
ordinary word would otherwise cost three more requests and three more empty
cards, and none of these sites has anything to say about "Haus".

Each site gets a parser that follows its own markup, plus the shared
:func:`rows_from_tables` as a fallback, because the layout of a scraped
page is a promise nobody made us.
"""

from __future__ import annotations

import re
from typing import Iterable, List, Tuple

from .. import http, htmlutil
from .. import results as R
from .base import Source, SourceError, register

# The longest thing anyone would call an acronym, and the shortest.
MAX_ACRONYM = 12
# A cap on how many meanings one source contributes: "IT" has hundreds.
MAX_MEANINGS = 40

_ACRONYM_CHARS = re.compile(r"^[\w.&/-]+$", re.UNICODE)
_HEADER_KEY = re.compile(r"(?i)\b(acronym|abbreviation|abbr|term|short)\b")
_HEADER_VALUE = re.compile(r"(?i)\b(definition|meaning|stands for|expansion|full form|long form)\b")
# "NASA" and "N.A.S.A." and "nasa" are the same key.
_FOLD = re.compile(r"[^\w]", re.UNICODE)


def fold(text: str) -> str:
    return _FOLD.sub("", str(text or "")).casefold()


def looks_like_acronym(text: str) -> bool:
    """Whether a search term is worth asking an acronym dictionary about.

    One token, short, and mostly capitals or digits: ``NASA``, ``PhD``,
    ``B2B``, ``Wi-Fi`` yes; ``Haus``, ``nasa``, ``house price`` no.  Typing
    an acronym in capitals is how everybody writes one anyway, and it is
    also what tells the AI sources to explain an acronym rather than a word.
    """
    term = str(text or "").strip()
    if not term or len(term) > MAX_ACRONYM or any(ch.isspace() for ch in term):
        return False
    if not _ACRONYM_CHARS.match(term):
        return False
    letters = [ch for ch in term if ch.isalnum()]
    if len(letters) < 2:
        return False
    strong = sum(1 for ch in letters if ch.isupper() or ch.isdigit())
    return strong >= max(2, (len(letters) + 1) // 2)


def is_all_caps(text: str) -> bool:
    """An all-uppercase single token -- the strongest acronym signal."""
    term = str(text or "").strip()
    if not term or any(ch.isspace() for ch in term):
        return False
    letters = [ch for ch in term if ch.isalpha()]
    return bool(letters) and all(ch.isupper() for ch in letters) and len(term) <= MAX_ACRONYM


# --------------------------------------------------------------- extraction

def _cells(row: htmlutil.Node) -> List[str]:
    return [c.inline_text() for c in row.find_all("td,th")]


def rows_from_tables(root: htmlutil.Node, acronym: str) -> List[Tuple[str, str]]:
    """``(meaning, category)`` pairs out of any acronym-shaped table.

    A table qualifies when its header names an acronym column and a meaning
    column, or -- for pages that ship no header -- when its first column
    repeats the term we asked about.
    """
    key = fold(acronym)
    out: List[Tuple[str, str]] = []
    for table in root.find_all("table"):
        rows = table.find_all("tr")
        if not rows:
            continue
        header = _cells(rows[0])
        term_col, meaning_col = 0, 1
        titled = False
        if len(header) >= 2 and any(_HEADER_KEY.search(h) for h in header) \
                and any(_HEADER_VALUE.search(h) for h in header):
            term_col = next(i for i, h in enumerate(header) if _HEADER_KEY.search(h))
            meaning_col = next(i for i, h in enumerate(header) if _HEADER_VALUE.search(h))
            titled = True
        for row in (rows[1:] if titled else rows):
            cells = _cells(row)
            if len(cells) <= max(term_col, meaning_col):
                continue
            if fold(cells[term_col]) != key:
                continue
            meaning = cells[meaning_col].strip()
            if not meaning:
                continue
            rest = [c.strip() for i, c in enumerate(cells)
                    if i not in (term_col, meaning_col) and c.strip()]
            out.append((meaning, _category(rest)))
    return out


# A rating column ("*****", "97 votes") is not a subject category.
_NOT_A_CATEGORY = re.compile(r"(?i)^([*\u2605\u2606\s]+|\d[\d,.\s]*(votes?|ratings?)?|rate it|new search)$")


def _category(candidates: Iterable[str]) -> str:
    for value in candidates:
        if len(value) > 40 or _NOT_A_CATEGORY.match(value):
            continue
        return value
    return ""


def clean_meaning(text: str) -> str:
    """One expansion, without the site's decorations."""
    value = R.clean(text)
    value = re.sub(r"(?i)\s*\((?:also|see|redirected from)[^)]*\)\s*$", "", value)
    value = value.strip(" -–—·|")
    return value


def to_entries(acronym: str, rows: Iterable[Tuple[str, str]], url: str = "") -> List[dict]:
    """One entry whose senses are the things the acronym can stand for."""
    senses: List[dict] = []
    seen = set()
    for meaning, category in rows:
        meaning = clean_meaning(meaning)
        if not meaning or len(meaning) > 200:
            continue
        key = meaning.casefold()
        if key in seen:
            continue
        seen.add(key)
        # `acronym` is what makes the panel print the initials in bold.
        senses.append(R.sense(meaning, tags=[category] if category else [], acronym=acronym))
        if len(senses) >= MAX_MEANINGS:
            break
    if not senses:
        return []
    return [R.entry(acronym, pos="acronym", senses=senses, url=url)]


# ------------------------------------------------------------------ drivers

class AcronymSource(Source):
    """Shared plumbing: fetch the page, parse it, build the one entry."""

    kind = "remote"
    types = ("dictionary",)
    order = 30
    # Acronyms are not a language's property; the sites are English-language
    # but list international ones, so the row is not pinned to a language.
    languages = ()

    def page_url(self, word: str) -> str:
        template = self.url if "{word}" in self.url else self.default_url
        return http.fill_template(template, word=word)

    @classmethod
    def parse(cls, markup: str, acronym: str) -> List[Tuple[str, str]]:
        raise NotImplementedError

    def lookup(self, word: str, lang: str) -> dict:
        word = word.strip()
        if not looks_like_acronym(word):
            # Not a refusal: this source simply has nothing for a word.
            return {"entries": [], "url": ""}
        url = self.page_url(word)
        try:
            markup = http.fetch(url).text
        except http.FetchError as e:
            if e.status in (404, 410):
                return {"entries": [], "url": url}
            raise SourceError(f"{self.name}: {e}")
        rows = self.parse(markup, word)
        return {"entries": to_entries(word, rows, url=url), "url": url}


@register
class FreeDictionaryAcronyms(AcronymSource):
    driver = "tfd-acronyms"
    label = "Acronym Finder (TheFreeDictionary)"
    description = ("Acronyms and abbreviations from acronyms.thefreedictionary.com "
                   "(the Acronym Finder / Abbreviations database).")
    default_url = "https://acronyms.thefreedictionary.com/{word}"
    order = 30

    @classmethod
    def parse(cls, markup: str, acronym: str) -> List[Tuple[str, str]]:
        root = htmlutil.parse(markup)
        rows: List[Tuple[str, str]] = []
        # The acronym tables carry `class="AcrList"`; each row is
        # <td>ACRONYM</td><td>meaning</td>[<td>category</td>].
        for table in root.find_all("table", cls="AcrList"):
            for tr in table.find_all("tr"):
                cells = _cells(tr)
                if len(cells) < 2 or fold(cells[0]) != fold(acronym):
                    continue
                rows.append((cells[1], _category(cells[2:])))
        if not rows:
            rows = rows_from_tables(root, acronym)
        return rows


@register
class AcronymFinder(AcronymSource):
    driver = "acronymfinder"
    label = "Acronym Finder"
    description = "Acronyms and abbreviations from acronymfinder.com."
    default_url = "https://www.acronymfinder.com/{word}.html"
    order = 31

    _MEANING_CLASS = re.compile(r"(?i)meaning|definition")
    _ACRONYM_CLASS = re.compile(r"(?i)acronym")
    _CATEGORY_CLASS = re.compile(r"(?i)category|cat\b")

    @classmethod
    def parse(cls, markup: str, acronym: str) -> List[Tuple[str, str]]:
        root = htmlutil.parse(markup)
        rows: List[Tuple[str, str]] = []
        # `result-list__body__acronym` / `result-list__body__meaning` cells.
        for tr in root.find_all("tr"):
            cells = tr.find_all("td,div")
            term = ""
            meaning = ""
            category = ""
            for cell in cells:
                classes = " ".join(cell.classes)
                if not classes:
                    continue
                if not term and cls._ACRONYM_CLASS.search(classes):
                    term = cell.inline_text()
                elif not meaning and cls._MEANING_CLASS.search(classes):
                    meaning = cell.inline_text()
                elif not category and cls._CATEGORY_CLASS.search(classes):
                    category = cell.inline_text()
            if meaning and (not term or fold(term) == fold(acronym)):
                rows.append((meaning, _category([category])))
        if not rows:
            rows = rows_from_tables(root, acronym)
        return rows


@register
class AllAcronyms(AcronymSource):
    driver = "allacronyms"
    label = "All Acronyms"
    description = "Acronyms and abbreviations from allacronyms.com."
    default_url = "https://www.allacronyms.com/{word}"
    order = 32

    @classmethod
    def parse(cls, markup: str, acronym: str) -> List[Tuple[str, str]]:
        root = htmlutil.parse(markup)
        rows: List[Tuple[str, str]] = []
        # Every meaning is a link back to /<ACRONYM>/<The_Full_Form>, which
        # is the one part of the page that is not styling.
        wanted = re.compile(r"^/%s/([^/?#]+)/?$" % re.escape(acronym), re.IGNORECASE)
        for a in root.find_all("a"):
            m = wanted.match(a.get("href").split("?")[0])
            if not m:
                continue
            text = a.inline_text()
            meaning = text if len(text.split()) > 1 else m.group(1).replace("_", " ")
            if fold(meaning) == fold(acronym):
                continue
            # `/NASA/abbreviated`, `/NASA/full-form` and friends are the
            # site's own navigation, not something the acronym stands for;
            # an expansion is several words, or at least a capitalised one.
            if len(meaning.split()) < 2 and not meaning[:1].isupper():
                continue
            rows.append((meaning, _category([_nearby_category(a)])))
        if not rows:
            rows = rows_from_tables(root, acronym)
        return rows


def _nearby_category(node: htmlutil.Node) -> str:
    """A subject label sitting next to a meaning, if the row carries one."""
    row = node.closest(cls="tr") or node.closest("tr") or node.closest("li")
    if row is None:
        return ""
    for tag in row.find_all("span,em,small"):
        text = tag.inline_text()
        if text and len(text) <= 40 and tag is not node:
            return text
    return ""


def acronym_drivers() -> List[str]:
    """The built-in acronym rows, in the order the panel shows them."""
    return [FreeDictionaryAcronyms.driver, AcronymFinder.driver, AllAcronyms.driver]
