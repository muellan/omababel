"""Unihan importer.

Accepts ``Unihan.zip`` (unicode.org), a directory of ``Unihan_*.txt`` /
``k*.txt`` files, or a single property file.  Both the canonical
``U+4E2D<TAB>kDefinition<TAB>...`` layout and the GitHub review repo's
``U+4E2D 中<TAB>kDefinition<TAB>...`` layout are understood.

One entry per code point: definition senses (English), Mandarin reading
as pronunciation, other readings in ``extra``.
"""

from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path
from typing import Dict, Iterator, List

from .. import results as R
from . import open_text

READING_PROPS = ("kMandarin", "kCantonese", "kJapaneseOn", "kJapaneseKun", "kJapanese",
                 "kKorean", "kHangul", "kVietnamese", "kHanyuPinyin", "kTang",
                 "kDefinition", "kTotalStrokes", "kRSUnicode", "kSimplifiedVariant",
                 "kTraditionalVariant", "kSemanticVariant", "kFrequency", "kGradeLevel")

_LINE = re.compile(r"^U\+([0-9A-Fa-f]{4,6})(?:\s\S+)?\t(k\w+)\t(.*)$")


def _iter_lines(path: Path) -> Iterator[str]:
    path = Path(path)
    if path.is_dir():
        for f in sorted(path.glob("*.txt")):
            with open_text(f) as fh:
                for line in fh:
                    yield line
    elif path.name.lower().endswith(".zip"):
        with zipfile.ZipFile(path) as zf:
            for name in sorted(zf.namelist()):
                if not name.endswith(".txt"):
                    continue
                with zf.open(name) as raw:
                    for line in io.TextIOWrapper(raw, encoding="utf-8", errors="replace"):
                        yield line
    else:
        with open_text(path) as fh:
            for line in fh:
                yield line


def _variants(value: str) -> List[str]:
    out = []
    for token in value.split():
        m = re.match(r"U\+([0-9A-Fa-f]{4,6})", token)
        if m:
            out.append(chr(int(m.group(1), 16)))
    return out


def iter_unihan(path: Path, **_options) -> Iterator[dict]:
    props: Dict[int, Dict[str, str]] = {}
    for line in _iter_lines(path):
        if not line or line.startswith("#"):
            continue
        m = _LINE.match(line.rstrip("\n"))
        if not m:
            continue
        cp, prop, value = int(m.group(1), 16), m.group(2), m.group(3).strip()
        if prop not in READING_PROPS:
            continue
        props.setdefault(cp, {})[prop] = value
    for cp in sorted(props):
        p = props[cp]
        definition = p.get("kDefinition", "")
        if not definition and not p.get("kMandarin"):
            continue
        char = chr(cp)
        senses = []
        for part in re.split(r";\s*", definition):
            part = part.strip()
            if part:
                s = R.sense(part)
                s["lang"] = "en"
                senses.append(s)
        extra: Dict[str, object] = {"codepoint": f"U+{cp:04X}"}
        for prop in ("kCantonese", "kJapaneseOn", "kJapaneseKun", "kJapanese", "kKorean",
                     "kHangul", "kVietnamese", "kTotalStrokes", "kRSUnicode", "kFrequency", "kGradeLevel"):
            if p.get(prop):
                extra[prop[1:]] = p[prop]
        forms: List[str] = []
        for prop in ("kSimplifiedVariant", "kTraditionalVariant"):
            if p.get(prop):
                vs = _variants(p[prop])
                if vs:
                    extra[prop[1:]] = "".join(vs)
                    forms.extend(vs)
        yield {
            "word": char, "lang": "zh", "pos": "", "pron": p.get("kMandarin", ""),
            "senses": senses or [R.sense("")], "translations": {"en": [s["gloss"] for s in senses]} if senses else {},
            "forms": forms, "extra": extra,
        }
