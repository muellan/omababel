"""CC-CEDICT importer.

Two inputs are accepted:

* the canonical text format (``cedict_ts.u8`` from MDBG)::

      中國 中国 [Zhong1 guo2] /China/

* ``data/all.js`` from github.com/edvardsr/cc-cedict::

      export default {"all":[[trad, simp, pinyin, defs, variants, classifiers], ...]}

Every entry is indexed under its simplified form with the traditional form
as an alternative form, so both scripts hit.  Pinyin gets tone marks.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Iterator, List, Optional

from .. import results as R
from . import open_text

_LINE = re.compile(r"^(?P<trad>\S+)\s+(?P<simp>\S+)\s+\[(?P<pinyin>[^\]]*)\]\s+/(?P<defs>.*)/\s*$")

_TONES = {
    "a": "aāáǎà", "e": "eēéěè", "i": "iīíǐì", "o": "oōóǒò", "u": "uūúǔù", "ü": "üǖǘǚǜ",
    "A": "AĀÁǍÀ", "E": "EĒÉĚÈ", "I": "IĪÍǏÌ", "O": "OŌÓǑÒ", "U": "UŪÚǓÙ", "Ü": "ÜǕǗǙǛ",
}


def pinyin_marks(syllables: str) -> str:
    """``Zhong1 guo2`` -> ``Zhōng guó`` (``5`` = neutral tone)."""
    out: List[str] = []
    for syl in syllables.split():
        m = re.match(r"^([A-Za-zü:Ü]+)([1-5])$", syl)
        if not m:
            out.append(syl)
            continue
        letters, tone = m.group(1).replace("u:", "ü").replace("U:", "Ü"), int(m.group(2))
        if tone == 5:
            out.append(letters)
            continue
        low = letters.lower()
        idx = -1
        if "a" in low:
            idx = low.index("a")
        elif "e" in low:
            idx = low.index("e")
        elif "ou" in low:
            idx = low.index("o")
        else:
            for i in range(len(low) - 1, -1, -1):
                if low[i] in "aeiouü":
                    idx = i
                    break
        if idx < 0:
            out.append(letters)
            continue
        ch = letters[idx]
        marked = _TONES.get(ch, ch * 5)[tone] if ch in _TONES else ch
        out.append(letters[:idx] + marked + letters[idx + 1:])
    return " ".join(out)


def make_entry(trad: str, simp: str, pinyin: str, defs: List[str]) -> Optional[dict]:
    defs = [R.clean(d) for d in defs if R.clean(d)]
    if not defs:
        return None
    senses = [R.sense(d) for d in defs]
    for s in senses:
        s["lang"] = "en"
    extra = {"traditional": trad, "simplified": simp, "pinyin_numeric": pinyin}
    forms = [trad] if trad != simp else []
    return {
        "word": simp, "lang": "zh", "pos": "", "pron": pinyin_marks(pinyin),
        "senses": senses, "translations": {"en": R.dedupe(defs)}, "forms": forms, "extra": extra,
    }


def parse_line(line: str) -> Optional[dict]:
    m = _LINE.match(line.strip())
    if not m:
        return None
    return make_entry(m.group("trad"), m.group("simp"), m.group("pinyin"), m.group("defs").split("/"))


def iter_cedict(path: Path, **_options) -> Iterator[dict]:
    path = Path(path)
    name = path.name.lower()
    if name.endswith(".js") or name.endswith(".json"):
        with open_text(path) as fh:
            raw = fh.read()
        start = raw.find("{")
        data = json.loads(raw[start:]) if start >= 0 else {}
        rows = data.get("all") if isinstance(data, dict) else data
        for row in rows or []:
            if not isinstance(row, list) or len(row) < 4:
                continue
            trad, simp, pinyin, defs = row[0], row[1], row[2], row[3]
            if isinstance(defs, str):
                defs = [defs]
            entry = make_entry(str(trad), str(simp), str(pinyin), [str(d) for d in defs])
            if entry:
                if len(row) > 5 and row[5]:
                    entry["extra"]["classifiers"] = [str(c) for c in row[5]]
                yield entry
        return
    with open_text(path) as fh:
        for line in fh:
            if not line or line.startswith("#"):
                continue
            entry = parse_line(line)
            if entry:
                yield entry
