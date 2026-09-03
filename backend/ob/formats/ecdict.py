"""ECDICT importer (github.com/skywind3000/ECDICT ``ecdict.csv``).

Columns: word, phonetic, definition (English), translation (Chinese),
pos, collins, oxford, tag, bnc, frq, exchange, detail, audio.
``exchange`` lists inflections as ``p:did/d:done/i:doing/3:does/...``.
"""

from __future__ import annotations

import csv
import re
import sys
from pathlib import Path
from typing import Iterator, List

from .. import results as R
from . import open_text

csv.field_size_limit(min(sys.maxsize, 2 ** 31 - 1))

# "n. a dwelling", "vt. 给...房子住" ...
_POS_PREFIX = re.compile(r"^(n|v|vt|vi|a|adj|adv|prep|conj|pron|int|interj|num|art|aux|abbr|pl|u|c|s)\.\s*", re.I)
# ... and the dot-less WordNet style "v change location" / "n benefit" used by
# entries that only carry WordNet glosses.
_WN_PREFIX = re.compile(r"^([nvars])\s+(?=\S)")


def _strip_pos(line: str, dotless_ok: bool):
    m = _POS_PREFIX.match(line)
    if m:
        return line[m.end():], m.group(1).lower() + "."
    if dotless_ok:
        m = _WN_PREFIX.match(line)
        if m:
            return line[m.end():], m.group(1) + "."
    return line, ""

_EXCHANGE_KEYS = {"p", "d", "i", "3", "r", "t", "s"}  # past, done, ing, 3rd, comparative, superlative, plural


def _split_lines(text: str) -> List[str]:
    return [ln.strip() for ln in re.split(r"\\n|\n|\r", text or "") if ln.strip()]


def convert(row: dict) -> dict:
    word = row.get("word", "").strip()
    definition = _split_lines(row.get("definition", ""))
    translation = _split_lines(row.get("translation", ""))
    senses: List[dict] = []
    dotless_ok = not any(_POS_PREFIX.match(d) for d in definition)
    for d in definition:
        text, tag = _strip_pos(d, dotless_ok)
        senses.append(R.sense(text, tags=[tag] if tag else []))
    for s in senses:
        s["lang"] = "en"
    for t in translation:
        text, tag = _strip_pos(t, False)
        s = R.sense(text, tags=[tag] if tag else [])
        s["lang"] = "zh"
        senses.append(s)
    zh_words: List[str] = []
    for t in translation:
        t = _POS_PREFIX.sub("", t)
        for part in re.split(r"[；;，,、]\s*", t):
            part = re.sub(r"\[.*?\]|\(.*?\)|（.*?）", "", part).strip()
            if part and len(part) <= 30:
                zh_words.append(part)
    forms: List[str] = []
    for chunk in (row.get("exchange") or "").split("/"):
        if ":" in chunk:
            key, val = chunk.split(":", 1)
            if key in _EXCHANGE_KEYS and val and val != word:
                forms.append(val)
    extra = {}
    for key in ("collins", "oxford", "tag", "bnc", "frq"):
        if row.get(key):
            extra[key] = row[key]
    return {
        "word": word, "lang": "en", "pos": _pos_summary(row.get("pos", "")),
        "pron": row.get("phonetic", "").strip(), "senses": senses,
        "translations": {"zh": R.dedupe(zh_words)} if zh_words else {},
        "forms": forms, "extra": extra,
    }


def _pos_summary(pos: str) -> str:
    # "n:57/v:43" -> "n., v."
    parts = []
    for chunk in pos.split("/"):
        if ":" in chunk:
            parts.append(chunk.split(":", 1)[0] + ".")
    return ", ".join(parts)


def iter_ecdict(path: Path, **_options) -> Iterator[dict]:
    with open_text(path) as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            if not row.get("word"):
                continue
            if not (row.get("definition") or row.get("translation")):
                continue
            yield convert(row)
