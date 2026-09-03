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
    return {"src": clean(src), "dst": clean(dst), "pos": clean(pos), "note": clean(note)}


def translation(mode: str, pairs: Optional[List[dict]] = None, text: str = "",
                detected: str = "", url: str = "", alternatives: Optional[List[str]] = None) -> dict:
    return {
        "mode": mode,
        "pairs": pairs or [],
        "text": text,
        "detected": detected,
        "url": url,
        "alternatives": alternatives or [],
    }


def thesaurus(synonyms: Iterable[str], antonyms: Iterable[str] = (), url: str = "") -> dict:
    return {"synonyms": dedupe(synonyms), "antonyms": dedupe(antonyms), "url": url}


_WS = re.compile(r"\s+")


def clean(text) -> str:
    if text is None:
        return ""
    text = str(text).replace("\xa0", " ")
    return _WS.sub(" ", text).strip()


def dedupe(words: Iterable[str]) -> List[str]:
    """Order-preserving, case-insensitive de-duplication with cleaning."""
    seen = set()
    out: List[str] = []
    for w in words:
        w = clean(w)
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
    """Merge many thesaurus results into alphabetical synonym/antonym lists."""
    syn: List[str] = []
    ant: List[str] = []
    for p in parts:
        if not p:
            continue
        syn.extend(p.get("synonyms", []))
        ant.extend(p.get("antonyms", []))
    syn_sorted = sort_words(syn)
    ant_keys = {fold(a) for a in ant}
    # A word can't sensibly be both; prefer the synonym reading.
    ant_sorted = [a for a in sort_words(ant) if fold(a) not in {fold(s) for s in syn_sorted}]
    return {"synonyms": syn_sorted, "antonyms": ant_sorted, "antonym_count_raw": len(ant_keys)}
