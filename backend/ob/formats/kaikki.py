"""kaikki.org (wiktextract) JSONL importer.

Handles both the per-language dumps of the English Wiktionary
(``kaikki.org-dictionary-German.jsonl``) and the per-edition extracts
(``de-extract.jsonl.gz``) which contain every language of that edition;
pass ``lang`` to keep only one headword language.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator, List, Optional

from .. import languages
from .. import results as R
from . import open_text

MAX_SENSES = 40
MAX_EXAMPLES = 3


def _words(items) -> List[str]:
    out: List[str] = []
    for it in items or []:
        if isinstance(it, dict):
            w = it.get("word")
            if w:
                out.append(str(w))
        elif isinstance(it, str):
            out.append(it)
    return out


def convert(obj: dict, edition_lang: Optional[str] = None) -> Optional[dict]:
    word = obj.get("word")
    if not word:
        return None
    lang = languages.normalize(obj.get("lang_code")) or obj.get("lang_code") or edition_lang or ""
    senses: List[dict] = []
    syn_all = _words(obj.get("synonyms"))
    ant_all = _words(obj.get("antonyms"))
    for s in (obj.get("senses") or [])[:MAX_SENSES]:
        if not isinstance(s, dict):
            continue
        glosses = s.get("glosses") or s.get("raw_glosses") or []
        gloss = "; ".join(str(g) for g in glosses if g)
        if not gloss:
            continue
        examples = []
        for ex in (s.get("examples") or [])[:MAX_EXAMPLES]:
            if isinstance(ex, dict) and ex.get("text"):
                examples.append(str(ex["text"]))
        tags = [str(t) for t in (s.get("tags") or []) if t]
        sense = R.sense(gloss, examples=examples, synonyms=_words(s.get("synonyms")),
                        antonyms=_words(s.get("antonyms")), tags=tags)
        senses.append(sense)
    if not senses:
        return None
    if syn_all:
        senses[0]["synonyms"] = R.dedupe(senses[0]["synonyms"] + syn_all)
    if ant_all:
        senses[0]["antonyms"] = R.dedupe(senses[0]["antonyms"] + ant_all)
    translations: dict = {}
    for t in obj.get("translations") or []:
        if not isinstance(t, dict):
            continue
        code = languages.normalize(t.get("lang_code") or t.get("code")) or t.get("lang_code")
        w = t.get("word")
        if code and w:
            translations.setdefault(code, [])
            if w not in translations[code] and len(translations[code]) < 40:
                translations[code].append(str(w))
    forms = []
    for f in obj.get("forms") or []:
        if isinstance(f, dict) and f.get("form"):
            tags = f.get("tags") or []
            if "table-tags" in tags or "inflection-template" in tags:
                continue
            forms.append(str(f["form"]))
    pron = ""
    for snd in obj.get("sounds") or []:
        if isinstance(snd, dict) and snd.get("ipa"):
            pron = str(snd["ipa"])
            break
    extra = {}
    if obj.get("etymology_text"):
        extra["etymology"] = str(obj["etymology_text"])[:600]
    return {
        "word": str(word), "lang": lang, "pos": str(obj.get("pos") or ""), "pron": pron,
        "senses": senses, "translations": translations, "forms": forms[:60], "extra": extra,
    }


def iter_kaikki(path: Path, lang: Optional[str] = None, edition_lang: Optional[str] = None,
                **_options) -> Iterator[dict]:
    want = languages.normalize(lang) if lang else None
    with open_text(path) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            if not isinstance(obj, dict):
                continue
            if want:
                code = languages.normalize(obj.get("lang_code")) or obj.get("lang_code")
                if code != want:
                    continue
            entry = convert(obj, edition_lang)
            if entry:
                yield entry
