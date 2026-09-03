"""Simple hand-made formats: TSV and JSON entry lists.

TSV::

    word<TAB>definition[<TAB>part of speech]
    # comment lines start with '#'

JSON: a list of entry dicts in the store format, e.g.::

    [{"word": "Haus", "lang": "de", "pos": "noun",
      "senses": [{"gloss": "Gebäude", "synonyms": ["Gebäude"]}],
      "translations": {"en": ["house"]}}]
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator, Optional

from .. import results as R
from . import open_text


def iter_tsv(path: Path, lang: Optional[str] = None, **_options) -> Iterator[dict]:
    with open_text(path) as fh:
        for line in fh:
            line = line.rstrip("\r\n")
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) < 2:
                continue
            word, definition = parts[0].strip(), parts[1].strip()
            pos = parts[2].strip() if len(parts) > 2 else ""
            if not word or not definition:
                continue
            senses = [R.sense(d) for d in definition.split(" | ") if d.strip()]
            yield {"word": word, "lang": lang or "", "pos": pos, "pron": "",
                   "senses": senses, "translations": {}, "forms": [], "extra": {}}


def iter_json(path: Path, lang: Optional[str] = None, **_options) -> Iterator[dict]:
    with open_text(path) as fh:
        data = json.load(fh)
    if isinstance(data, dict):
        data = data.get("entries") or []
    for obj in data:
        if not isinstance(obj, dict) or not obj.get("word"):
            continue
        senses = []
        for s in obj.get("senses") or []:
            if isinstance(s, str):
                senses.append(R.sense(s))
            elif isinstance(s, dict):
                senses.append(R.sense(s.get("gloss", ""), examples=s.get("examples"),
                                      synonyms=s.get("synonyms"), antonyms=s.get("antonyms"),
                                      tags=s.get("tags"), label=str(s.get("label", ""))))
        yield {
            "word": str(obj["word"]), "lang": obj.get("lang") or lang or "",
            "pos": str(obj.get("pos", "")), "pron": str(obj.get("pron", "")),
            "senses": senses, "translations": obj.get("translations") or {},
            "forms": obj.get("forms") or [], "extra": obj.get("extra") or {},
        }
