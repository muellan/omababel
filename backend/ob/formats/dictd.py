"""dictd importer (``foo.index`` + ``foo.dict`` / ``foo.dict.dz``).

The index is ``headword<TAB>offset<TAB>length`` with base64-style numbers.
dictzip files are ordinary gzip members, which Python's gzip module can
read sequentially – we decompress once at import time.
"""

from __future__ import annotations

import gzip
import re
from pathlib import Path
from typing import Iterator, Optional

from .. import languages
from .. import results as R

_B64 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
_B64_INDEX = {c: i for i, c in enumerate(_B64)}


def b64_to_int(text: str) -> int:
    value = 0
    for ch in text:
        value = value * 64 + _B64_INDEX[ch]
    return value


def _pair(name: str):
    m = re.search(r"(?<![a-z])([a-z]{3})-([a-z]{3})(?![a-z])", name.lower())
    if not m:
        return None, None
    return languages.normalize(m.group(1)) or m.group(1), languages.normalize(m.group(2)) or m.group(2)


def iter_dictd(path: Path, src: Optional[str] = None, dst: Optional[str] = None,
               **_options) -> Iterator[dict]:
    path = Path(path)
    if path.suffix == ".index":
        index_path = path
        base = path.with_suffix("")
    else:
        base = path.with_suffix("") if path.suffix == ".dz" else path
        base = base.with_suffix("") if base.suffix == ".dict" else base
        index_path = base.with_suffix(".index")
    dict_path = None
    for cand in (base.with_suffix(".dict.dz"), base.with_suffix(".dict"),
                 Path(str(base) + ".dict.dz"), Path(str(base) + ".dict")):
        if cand.exists():
            dict_path = cand
            break
    if dict_path is None or not index_path.exists():
        raise FileNotFoundError(f"dictd pair not found for {path}")
    if dict_path.name.endswith(".dz"):
        with gzip.open(dict_path, "rb") as fh:
            data = fh.read()
    else:
        data = dict_path.read_bytes()
    p_src, p_dst = _pair(base.name)
    src = src or p_src or ""
    dst = dst or p_dst or ""
    with open(index_path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 3:
                continue
            word, off, length = parts[0], parts[1], parts[2]
            if word.startswith("00-database") or word.startswith("00database"):
                continue
            try:
                start, size = b64_to_int(off), b64_to_int(length)
            except KeyError:
                continue
            body = data[start:start + size].decode("utf-8", errors="replace")
            lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
            if lines and R.fold(lines[0]) == R.fold(word):
                lines = lines[1:]
            text = "\n".join(lines)
            if not text:
                continue
            pos = ""
            m = re.match(r"^<([^>]{1,20})>\s*", text)
            if m:
                pos, text = m.group(1), text[m.end():]
            translations = [t.strip() for t in re.split(r"[,;]\s*|\n", text) if t.strip()]
            yield {
                "word": word, "lang": src, "pos": pos, "pron": "",
                "senses": [R.sense(text.replace("\n", "; "))],
                "translations": {dst: R.dedupe(translations[:30])} if dst else {},
                "forms": [], "extra": {},
            }
