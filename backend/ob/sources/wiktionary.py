"""Wiktionary over the web.

The downloadable Wiktionary datasets (kaikki.org dumps, see :mod:`ob.data`)
are hundreds of megabytes, so they are installed on demand -- and until one
is installed the corresponding row has nothing to answer with.  This driver
is what it falls back to: the same edition of Wiktionary, queried live.

The page is fetched through the MediaWiki API as *wikitext* rather than as
rendered HTML.  Wikitext is what the dumps are made from, it is an order of
magnitude smaller, and its structure (``==Language==`` /
``===Part of speech===`` / ``#`` definitions) is the structure we want,
while the rendered page buries it in presentation markup that each edition
themes differently.

Editions differ in how they mark a language section.  The English edition
spells the language out (``==German==``); the others use a template
(``{{Sprache|Deutsch}}``, ``{{langue|fr}}``, ``{{lengua|es}}``...).  Both
shapes are recognised, and an entry that has only one language section is
taken as that language.
"""

from __future__ import annotations

import re
import urllib.parse
from typing import Dict, List, Optional, Tuple

from .. import http, languages
from .. import results as R
from .base import Source, SourceError, register

API = "https://{edition}.wiktionary.org/w/api.php"
PAGE = "https://{edition}.wiktionary.org/wiki/{word}"

# Part-of-speech headings worth keeping, in the editions we care about.
# Everything else (Etymology, Pronunciation, References...) is skipped.
_POS_WORDS = {
    "noun", "verb", "adjective", "adverb", "pronoun", "preposition", "conjunction",
    "interjection", "numeral", "article", "determiner", "participle", "proper noun",
    "prefix", "suffix", "abbreviation", "acronym", "initialism", "phrase", "idiom",
    "proverb", "letter", "symbol", "character", "counter", "particle", "postposition",
    # German edition
    "substantiv", "adjektiv", "adverb", "verb", "pronomen", "präposition", "konjunktion",
    "interjektion", "numerale", "artikel", "partikel", "abkürzung", "redewendung",
    # French / Spanish / Portuguese / Italian editions
    "nom", "nom propre", "verbe", "adjectif", "adverbe", "pronom", "préposition",
    "conjonction", "interjection", "sustantivo", "verbo", "adjetivo", "adverbio",
    "pronombre", "preposición", "conjunción", "interjección", "locución",
}

_SECTION = re.compile(r"^(={2,6})\s*(.*?)\s*\1\s*$")
_REF = re.compile(r"(?is)<ref[^>]*?(?:/>|>.*?</ref>)")
_COMMENT = re.compile(r"(?s)<!--.*?-->")
_TAG = re.compile(r"(?s)<[^>]+>")
_WIKILINK = re.compile(r"\[\[([^\]\[|]*)\|?([^\]\[]*)\]\]")
_EXTLINK = re.compile(r"\[(?:https?|//)\S+\s+([^\]]*)\]")
_QUOTES = re.compile(r"'{2,5}")
# `{{t+|de|Haus|n}}` style rows inside a translation table.
_T_TEMPLATE = re.compile(r"\{\{\s*t[-+ø]*\s*\|([^|}]+)\|([^|}]+)")


def _split_template(body: str) -> List[str]:
    """Arguments of a template body, respecting one level of nesting."""
    args: List[str] = []
    depth = 0
    current: List[str] = []
    i = 0
    while i < len(body):
        ch = body[i]
        if body.startswith("{{", i) or body.startswith("[[", i):
            depth += 1
            current.append(body[i:i + 2])
            i += 2
            continue
        if body.startswith("}}", i) or body.startswith("]]", i):
            depth -= 1
            current.append(body[i:i + 2])
            i += 2
            continue
        if ch == "|" and depth == 0:
            args.append("".join(current))
            current = []
        else:
            current.append(ch)
        i += 1
    args.append("".join(current))
    return [a.strip() for a in args]


def iter_templates(text: str) -> List[Tuple[str, List[str]]]:
    """``(name, args)`` of every top-level template in ``text``."""
    out: List[Tuple[str, List[str]]] = []
    i = 0
    while True:
        start = text.find("{{", i)
        if start < 0:
            return out
        depth = 0
        j = start
        while j < len(text):
            if text.startswith("{{", j):
                depth += 1
                j += 2
                continue
            if text.startswith("}}", j):
                depth -= 1
                j += 2
                if depth == 0:
                    break
                continue
            j += 1
        if depth != 0:
            return out
        args = _split_template(text[start + 2:j - 2])
        out.append((args[0].strip().lower(), args[1:]))
        i = j


# Templates whose payload is visible text rather than a marker.
_TEXT_TEMPLATES = {"l", "m", "mention", "link", "w", "ll", "lang"}


def plain(text: str) -> str:
    """Wikitext -> the text a reader sees (near enough for a dictionary)."""
    text = _COMMENT.sub("", _REF.sub("", text or ""))

    def template(match: re.Match) -> str:
        parts = _split_template(match.group(1))
        name = parts[0].strip().lower()
        positional = [a for a in parts[1:] if "=" not in a]
        if name in _TEXT_TEMPLATES and len(positional) >= 2:
            return positional[1]
        if name in ("ux", "uxi", "usex", "ux-lite", "coi") and len(positional) >= 2:
            # example sentence, optionally followed by its translation
            return " – ".join(positional[1:3])
        if name in ("q", "qualifier", "i", "gloss", "gl"):
            return "(" + ", ".join(positional) + ")" if positional else ""
        if name in ("lb", "label", "context") and len(positional) > 1:
            return "(" + ", ".join(positional[1:]) + ")"
        return ""

    # Innermost first, so nested templates collapse from the inside out.
    previous = None
    while previous != text and "{{" in text:
        previous = text
        text = re.sub(r"\{\{([^{}]*)\}\}", template, text)
    text = _WIKILINK.sub(lambda m: (m.group(2) or m.group(1)).strip(), text)
    text = _EXTLINK.sub(lambda m: m.group(1), text)
    text = _QUOTES.sub("", text)
    text = _TAG.sub("", text)
    return R.clean(text)


def _words_from_list(line: str) -> List[str]:
    """Terms on a ``* {{l|de|a}}, [[b]]`` / ``:[1] a, b`` style line."""
    words: List[str] = []
    for name, args in iter_templates(line):
        if name in ("l", "m", "link", "mention", "syn", "ant", "synonyme", "s") and len(args) >= 2:
            words.extend(a for a in args[1:] if a and "=" not in a)
    if not words:
        text = plain(re.sub(r"^[*:#\s]*(\[\d+[^\]]*\])?", "", line))
        words = [w for w in re.split(r"[,;·/]| {2,}", text)]
    return [w for w in (R.word(w) for w in words) if w and len(w) <= 60]


class Section:
    """One ``==heading==`` block of a page."""

    __slots__ = ("level", "title", "lines")

    def __init__(self, level: int, title: str, lines: Optional[List[str]] = None):
        self.level = level
        self.title = title
        self.lines: List[str] = lines or []

    @property
    def text(self) -> str:
        return "\n".join(self.lines)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Section {self.level} {self.title!r} {len(self.lines)} lines>"


def sections(wikitext: str) -> List[Section]:
    out: List[Section] = [Section(0, "")]
    for line in (wikitext or "").splitlines():
        m = _SECTION.match(line)
        if m:
            out.append(Section(len(m.group(1)), m.group(2)))
        else:
            out[-1].lines.append(line)
    return out


def _heading_matches_language(title: str, lang: str) -> bool:
    info = languages.LANGUAGES.get(lang) or {}
    names = {str(info.get("kaikki") or ""), str(info.get("name") or ""),
             str(info.get("native") or "")}
    names = {n.casefold() for n in names if n}
    bare = plain(title).casefold().strip()
    if bare and bare in names:
        return True
    for _name, args in iter_templates(title):
        for arg in args:
            value = arg.strip().casefold()
            if value == lang or value == str(info.get("iso3") or "") or value in names:
                return True
    # `{{-de-}}`, used by a few editions
    return bool(re.search(r"\{\{-\s*%s\s*-\}\}" % re.escape(lang), title))


def language_section(wikitext: str, lang: str) -> List[Section]:
    """The sections belonging to ``lang``, heading first."""
    blocks = sections(wikitext)
    tops = [i for i, s in enumerate(blocks) if s.level == 2]
    chosen: Optional[int] = None
    for i in tops:
        if _heading_matches_language(blocks[i].title, lang):
            chosen = i
            break
    if chosen is None:
        if len(tops) != 1:
            return []
        chosen = tops[0]
    out = [blocks[chosen]]
    for s in blocks[chosen + 1:]:
        if s.level <= 2:
            break
        out.append(s)
    return out


def _pos_of(title: str) -> str:
    """The part of speech a heading names, or "" if it names something else."""
    label = plain(title)
    for _name, args in iter_templates(title):
        for arg in args:
            if arg.strip().casefold() in _POS_WORDS:
                label = arg.strip()
                break
    bare = re.sub(r"\s*\d+\s*$", "", label).strip(" :,")
    if bare.casefold() in _POS_WORDS:
        return bare
    return ""


def _section_words(blocks: List[Section], *titles: str) -> List[str]:
    """Words listed under a ``====Synonyms====`` style subsection."""
    wanted = {t.casefold() for t in titles}
    out: List[str] = []
    for s in blocks:
        if plain(s.title).casefold().strip() not in wanted:
            continue
        for line in s.lines:
            if line.strip().startswith(("*", ":")):
                out.extend(_words_from_list(line))
    return out


def _block_words(blocks: List[Section], *markers: str) -> List[str]:
    """Words under a German-edition ``{{Synonyme}}`` marker line."""
    wanted = {m.casefold() for m in markers}
    out: List[str] = []
    for s in blocks:
        collecting = False
        for line in s.lines:
            stripped = line.strip()
            templates = iter_templates(stripped)
            if templates and stripped.startswith("{{"):
                collecting = templates[0][0] in wanted
                continue
            if collecting and stripped.startswith(":"):
                out.extend(_words_from_list(stripped))
            elif collecting and not stripped:
                continue
            elif collecting:
                collecting = False
    return out


def parse_entries(wikitext: str, word: str, lang: str, url: str = "") -> List[dict]:
    """Dictionary entries for ``lang`` out of one page's wikitext."""
    blocks = language_section(wikitext, lang)
    if not blocks:
        return []
    entries: List[dict] = []
    # A German-edition page keeps its meanings in a `{{Bedeutungen}}` block
    # rather than in `#` lines, so both shapes feed the same sense list.
    for index, s in enumerate(blocks):
        pos = _pos_of(s.title)
        if not pos and index:
            continue
        senses = _senses(s)
        if not senses and index:
            continue
        scope = [s] + [b for b in blocks[index + 1:] if b.level > s.level]
        synonyms = R.dedupe(_section_words(scope, "synonyms", "synonym")
                            + _block_words(scope, "synonyme"))
        antonyms = R.dedupe(_section_words(scope, "antonyms", "antonym")
                            + _block_words(scope, "gegenwörter", "antonymes"))
        if not senses:
            continue
        if synonyms or antonyms:
            senses[0]["synonyms"] = R.dedupe(list(senses[0]["synonyms"]) + synonyms)
            senses[0]["antonyms"] = R.dedupe(list(senses[0]["antonyms"]) + antonyms)
        entries.append(R.entry(word, pos=pos, senses=senses, lang=lang, url=url))
    return entries


def _senses(section: Section) -> List[dict]:
    out: List[dict] = []
    collecting_meanings = False
    for line in section.lines:
        stripped = line.strip()
        if stripped.startswith("{{") and not stripped.startswith("{{{"):
            first = iter_templates(stripped)
            collecting_meanings = bool(first) and first[0][0] in ("bedeutungen",)
            continue
        if stripped.startswith("#") and not stripped.startswith(("#:", "#*", "##")):
            gloss, tags, syn, ant = _gloss(stripped.lstrip("#").strip())
            if gloss:
                out.append(R.sense(gloss, tags=tags, synonyms=syn, antonyms=ant))
            continue
        if stripped.startswith(("#:", "#*")) and out:
            example = plain(stripped.lstrip("#:*").strip())
            if example:
                out[-1]["examples"].append(example)
            for name, args in iter_templates(stripped):
                if name in ("syn", "synonyms") and len(args) > 1:
                    out[-1]["synonyms"] = R.dedupe(list(out[-1]["synonyms"]) + args[1:])
                elif name in ("ant", "antonyms") and len(args) > 1:
                    out[-1]["antonyms"] = R.dedupe(list(out[-1]["antonyms"]) + args[1:])
            continue
        if collecting_meanings and stripped.startswith(":"):
            gloss = plain(re.sub(r"^:*\s*(\[[^\]]*\])?", "", stripped))
            if gloss:
                out.append(R.sense(gloss))
    return out


def _gloss(text: str) -> Tuple[str, List[str], List[str], List[str]]:
    tags: List[str] = []
    syn: List[str] = []
    ant: List[str] = []
    for name, args in iter_templates(text):
        if name in ("lb", "label", "context") and len(args) > 1:
            tags.extend(a for a in args[1:] if a and "=" not in a)
        elif name in ("syn", "synonyms") and len(args) > 1:
            syn.extend(a for a in args[1:] if a and "=" not in a)
        elif name in ("ant", "antonyms") and len(args) > 1:
            ant.extend(a for a in args[1:] if a and "=" not in a)
    # The labels are carried as `tags`; leaving them in the gloss too would
    # print "(figurative) home" *and* a [figurative] chip next to it.
    body = re.sub(r"(?s)\{\{\s*(?:syn|ant|synonyms|antonyms|lb|label|context)\s*\|.*?\}\}", "", text)
    return plain(body), tags, R.dedupe(syn), R.dedupe(ant)


def parse_translations(wikitext: str, lang: str, target: str) -> List[dict]:
    """``{{trans-top}}`` rows of the ``lang`` section that point at ``target``."""
    blocks = language_section(wikitext, lang)
    info = languages.LANGUAGES.get(target) or {}
    codes = {target, str(info.get("iso3") or "")}
    if target == "zh":
        codes.update({"cmn", "zh"})
    names = {str(info.get("name") or "").casefold(), str(info.get("kaikki") or "").casefold()}
    names.discard("")
    pairs: List[dict] = []
    gloss = ""
    for s in blocks:
        for line in s.lines:
            stripped = line.strip()
            for name, args in iter_templates(stripped):
                if name in ("trans-top", "trans-top-also", "checktrans-top"):
                    gloss = plain(args[0]) if args else ""
            if not stripped.startswith("*"):
                continue
            label = plain(stripped.split(":")[0].lstrip("*: ")).casefold() if ":" in stripped else ""
            hits = [(code, term) for code, term in _T_TEMPLATE.findall(stripped)
                    if code.strip() in codes]
            if not hits and label and label in names:
                hits = [(target, t) for _c, t in _T_TEMPLATE.findall(stripped)]
            for _code, term in hits:
                term = R.word(plain(term))
                if term:
                    pairs.append(R.pair(gloss or "", term, note=gloss))
    return pairs


@register
class Wiktionary(Source):
    driver = "wiktionary"
    label = "Wiktionary (web)"
    kind = "remote"
    types = ("dictionary", "thesaurus", "translator")
    description = ("Wiktionary queried live through the MediaWiki API. Used automatically when "
                   "the downloadable Wiktionary dataset of a row is not installed yet.")
    default_url = API.replace("{edition}", "en")
    translation_modes = ("word",)
    order = 15

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        self.edition = self._edition_from(self.url) or "en"

    @staticmethod
    def _edition_from(url: str) -> str:
        host = urllib.parse.urlsplit(str(url or "")).hostname or ""
        head = host.split(".")[0].lower()
        return head if re.fullmatch(r"[a-z]{2,3}(-[a-z]+)?", head or "") else ""

    # ----------------------------------------------------------------- web
    def page_url(self, word: str) -> str:
        return PAGE.replace("{edition}", self.edition).replace(
            "{word}", urllib.parse.quote(word.replace(" ", "_"), safe=""))

    def wikitext(self, word: str) -> str:
        query = urllib.parse.urlencode({
            "action": "parse", "page": word, "prop": "wikitext",
            "format": "json", "formatversion": "2", "redirects": "1",
        })
        url = API.replace("{edition}", self.edition) + "?" + query
        try:
            data = http.fetch(url, headers={"Accept": "application/json"}).json()
        except http.FetchError as e:
            if e.status == 404:
                return ""
            raise SourceError(f"{self.name}: {e}")
        except ValueError as e:
            raise SourceError(f"{self.name}: the API did not answer with JSON ({e})")
        if isinstance(data, dict) and data.get("error"):
            code = str((data["error"] or {}).get("code") or "")
            if code in ("missingtitle", "nosuchpageid", "invalidtitle"):
                return ""
            raise SourceError(f"{self.name}: {code or 'the API refused the request'}")
        parse = (data or {}).get("parse") or {}
        return str(parse.get("wikitext") or "")

    # ---------------------------------------------------------------- work
    def lookup(self, word: str, lang: str) -> dict:
        word = word.strip()
        if not word:
            return {"entries": [], "url": ""}
        url = self.page_url(word)
        entries = parse_entries(self.wikitext(word), word, lang, url=url)
        return {"entries": entries, "url": url}

    def thesaurus(self, word: str, lang: str) -> dict:
        word = word.strip()
        if not word:
            return R.thesaurus([], [])
        url = self.page_url(word)
        entries = parse_entries(self.wikitext(word), word, lang, url=url)
        return self.thesaurus_from_entries(entries, url=url)

    def translate(self, text: str, src: str, dst: str) -> dict:
        text = text.strip()
        if not text:
            return R.translation("word")
        url = self.page_url(text)
        pairs = parse_translations(self.wikitext(text), src, dst)
        for p in pairs:
            p["src"] = text
        return R.translation("word", pairs, url=url)
