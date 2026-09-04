"""Result shapes shared by every source driver.

Sources return plain dicts so they serialise straight to JSON for the QML
side.  These helpers keep the shapes consistent:

Lookup  -> ``entry(...)`` objects with ``senses``
Thesaurus -> ``{"synonyms": [...], "antonyms": [...]}``
Translate -> ``{"mode": "word"|"text", "pairs": [...], "text": "..."}``
"""

from __future__ import annotations

import re
import unicodedata
from typing import Iterable, List, Optional


def sense(gloss: str, examples: Optional[Iterable[str]] = None,
          synonyms: Optional[Iterable[str]] = None,
          antonyms: Optional[Iterable[str]] = None,
          tags: Optional[Iterable[str]] = None,
          label: str = "") -> dict:
    return {
        "gloss": clean(gloss),
        "examples": [clean(e) for e in (examples or []) if clean(e)],
        "synonyms": dedupe(synonyms or []),
        "antonyms": dedupe(antonyms or []),
        "tags": [t for t in (tags or []) if t],
        "label": label,
    }


def entry(headword: str, pos: str = "", senses: Optional[List[dict]] = None,
          pronunciation: str = "", lang: str = "", extra: Optional[dict] = None,
          url: str = "") -> dict:
    return {
        "headword": clean(headword),
        "pos": clean(pos),
        "pronunciation": clean(pronunciation),
        "lang": lang,
        "senses": senses or [],
        "extra": {k: v for k, v in (extra or {}).items() if v},
        "url": url,
    }


def pair(src: str, dst: str, pos: str = "", note: str = "") -> dict:
    return {"src": phrase(src), "dst": phrase(dst), "pos": phrase(pos), "note": phrase(note)}


def translation(mode: str, pairs: Optional[List[dict]] = None, text: str = "",
                detected: str = "", url: str = "", alternatives: Optional[List[str]] = None) -> dict:
    return {
        "mode": mode,
        "pairs": pairs or [],
        "text": strip_bars(text),
        "detected": detected,
        "url": url,
        "alternatives": [phrase(a) for a in (alternatives or []) if phrase(a)],
    }


def group(synonyms: Iterable[str], antonyms: Iterable[str] = (), label: str = "", pos: str = "") -> dict:
    """One meaning: the words that belong to it (thesaurus.com-style grouping)."""
    return {"label": clean(label), "pos": clean(pos), "synonyms": dedupe(synonyms), "antonyms": dedupe(antonyms)}


def thesaurus(synonyms: Iterable[str], antonyms: Iterable[str] = (), url: str = "",
              groups: Optional[List[dict]] = None) -> dict:
    """Thesaurus result: flat lists plus ``groups`` (words per meaning).

    When a source cannot tell meanings apart, ``groups`` holds the flat lists
    as one unlabelled group.
    """
    syn, ant = dedupe(synonyms), dedupe(antonyms)
    groups = [g for g in (groups or []) if g.get("synonyms") or g.get("antonyms")]
    if not groups and (syn or ant):
        groups = [group(syn, ant)]
    if groups and not syn and not ant:
        syn = dedupe(w for g in groups for w in g["synonyms"])
        ant = dedupe(w for g in groups for w in g["antonyms"])
    return {"synonyms": syn, "antonyms": ant, "url": url, "groups": groups}


def groups_from_senses(entries: Iterable[dict]) -> List[dict]:
    """One group per sense that carries synonyms/antonyms (label = gloss)."""
    out: List[dict] = []
    for e in entries:
        for s in e.get("senses", []):
            if s.get("synonyms") or s.get("antonyms"):
                out.append(group(s.get("synonyms", []), s.get("antonyms", []),
                                 label=s.get("gloss", ""), pos=e.get("pos", "")))
    return out


_WS = re.compile(r"\s+")
# Zero width / formatting characters that scraped markup drags along.
_INVISIBLE = re.compile("[­​‌‍⁠﻿]")
# A hyphen that sits against one word and has whitespace on the other side
# belongs to the word: "by- product" and "by -product" are "by-product".
# " - " (space on both sides) is left alone – there it separates.
_HYPHEN_GAP = re.compile(r"(?<=\w)([-‐‑‒–—])\s+(?=\w)|(?<=\w)\s+([-‐‑‒–—])(?=\w)")


def clean(text) -> str:
    if text is None:
        return ""
    text = _INVISIBLE.sub("", str(text).replace("\xa0", " "))
    return _WS.sub(" ", text).strip()


# LEO wraps inflected forms in bars ("account for sth. | accounted, accounted |")
# and leaves an empty pair behind when a column has none of them.
_BARS = re.compile(r"^[|\s]+|[|\s]+$")
_BAR_RUN = re.compile(r"\s*\|(\s*\|)+\s*")


def strip_bars(text) -> str:
    """Drop leading/trailing `|` separators (per line, so multi line
    translations keep their layout)."""
    if text is None:
        return ""
    lines = [_BARS.sub("", _BAR_RUN.sub(" | ", ln)) for ln in str(text).split("\n")]
    return "\n".join(lines).strip("\n")


def phrase(text) -> str:
    """`clean` for one translation cell: no stray separators at the ends."""
    return _BARS.sub("", _BAR_RUN.sub(" | ", clean(text)))


def word(text) -> str:
    """`clean` for a single term: also repairs words torn apart at a hyphen."""
    w = clean(text)
    if not w:
        return ""
    return _HYPHEN_GAP.sub(lambda m: m.group(1) or m.group(2), w)


def dedupe(words: Iterable[str]) -> List[str]:
    """Order-preserving, case-insensitive de-duplication with cleaning."""
    seen = set()
    out: List[str] = []
    for w in words:
        w = word(w)
        if not w:
            continue
        key = fold(w)
        if key in seen:
            continue
        seen.add(key)
        out.append(w)
    return out


def fold(word: str) -> str:
    """Case/accent-insensitive sort & compare key."""
    nfkd = unicodedata.normalize("NFKD", word)
    stripped = "".join(ch for ch in nfkd if not unicodedata.combining(ch))
    return stripped.casefold()


def sort_words(words: Iterable[str]) -> List[str]:
    return sorted(dedupe(words), key=lambda w: (fold(w), w))


def consolidate(parts: Iterable[dict]) -> dict:
    """Merge many thesaurus results: per-meaning groups (in source order) plus
    alphabetical all-synonym / all-antonym lists."""
    syn: List[str] = []
    ant: List[str] = []
    groups: List[dict] = []
    for p in parts:
        if not p:
            continue
        syn.extend(p.get("synonyms", []))
        ant.extend(p.get("antonyms", []))
        src = p.get("source") or {}
        for g in p.get("groups") or []:
            if g.get("synonyms") or g.get("antonyms"):
                groups.append({"source": src.get("name", ""), "source_id": src.get("id", ""),
                               "label": g.get("label", ""), "pos": g.get("pos", ""),
                               "synonyms": sort_words(g.get("synonyms", [])),
                               "antonyms": sort_words(g.get("antonyms", []))})
    syn_sorted = sort_words(syn)
    ant_keys = {fold(a) for a in ant}
    # A word can't sensibly be both; prefer the synonym reading.
    ant_sorted = [a for a in sort_words(ant) if fold(a) not in {fold(s) for s in syn_sorted}]
    return {"synonyms": syn_sorted, "antonyms": ant_sorted, "antonym_count_raw": len(ant_keys),
            "groups": groups}
