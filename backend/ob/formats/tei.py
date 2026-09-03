"""FreeDict TEI XML importer (``freedict-deu-eng-*.src.tar.xz`` → ``deu-eng.tei``).

Uses ``iterparse`` so multi-hundred-MB dictionaries stream through without
being held in memory.  Language pair is read from the file name
(``deu-eng``) or from the TEI header.
"""

from __future__ import annotations

import io
import lzma
import re
import tarfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import IO, Iterator, List, Optional, Tuple

from .. import languages
from .. import results as R

TEI_NS = "{http://www.tei-c.org/ns/1.0}"


def _strip_ns(tag: str) -> str:
    return tag.split("}", 1)[1] if "}" in tag else tag


def pair_from_name(name: str) -> Optional[Tuple[str, str]]:
    m = re.search(r"(?<![a-z])([a-z]{3})-([a-z]{3})(?![a-z])", name.lower())
    if not m:
        return None
    a = languages.normalize(m.group(1)) or m.group(1)
    b = languages.normalize(m.group(2)) or m.group(2)
    return a, b


def open_tei(path: Path) -> IO[bytes]:
    """Return a binary stream of the TEI document inside ``path``.

    Accepts a plain ``.tei``/``.xml``, an ``.xz`` compressed file, or the
    FreeDict ``.src.tar.xz`` tarball.
    """
    name = path.name.lower()
    if name.endswith(".tar.xz") or name.endswith(".tar"):
        tf = tarfile.open(path, "r:*")
        member = None
        for m in tf.getmembers():
            if m.name.endswith(".tei"):
                member = m
                break
        if member is None:
            raise ValueError(f"no .tei file inside {path}")
        data = tf.extractfile(member)
        if data is None:
            raise ValueError(f"cannot read {member.name} from {path}")
        return io.BytesIO(data.read())
    if name.endswith(".xz"):
        return lzma.open(path, "rb")
    return open(path, "rb")


def _text(el: Optional[ET.Element]) -> str:
    if el is None:
        return ""
    return R.clean("".join(el.itertext()))


def parse_entry(entry: ET.Element, src: str, dst: str) -> Optional[dict]:
    orths = [_text(o) for o in entry.iter(TEI_NS + "orth")]
    orths = [o for o in orths if o]
    if not orths:
        return None
    word = orths[0]
    pron = ""
    for p in entry.iter(TEI_NS + "pron"):
        pron = _text(p)
        break
    pos_parts: List[str] = []
    for gram in entry.findall(TEI_NS + "gramGrp"):
        for child in gram:
            t = _text(child)
            if t:
                pos_parts.append(t)
    pos = ", ".join(pos_parts)
    senses: List[dict] = []
    translations: List[str] = []
    for sense in entry.findall(TEI_NS + "sense"):
        quotes = [_text(q) for q in sense.iter(TEI_NS + "quote")]
        quotes = [q for q in quotes if q]
        defs = [_text(d) for d in sense.findall(TEI_NS + "def")]
        notes = [_text(n) for n in sense.findall(TEI_NS + "note")]
        usgs = [_text(u) for u in sense.findall(TEI_NS + "usg")]
        syns: List[str] = []
        for xr in sense.findall(TEI_NS + "xr"):
            if (xr.get("type") or "syn").lower().startswith("syn"):
                syns.extend(_text(r) for r in xr.findall(TEI_NS + "ref"))
        gloss = "; ".join(quotes) if quotes else "; ".join(d for d in defs if d)
        if defs and quotes:
            gloss += " — " + "; ".join(d for d in defs if d)
        if not gloss and not syns:
            continue
        senses.append(R.sense(gloss, examples=[n for n in notes if n], synonyms=syns,
                              tags=[u for u in usgs if u]))
        translations.extend(quotes)
    # entry-level cross references
    for xr in entry.findall(TEI_NS + "xr"):
        if (xr.get("type") or "syn").lower().startswith("syn") and senses:
            senses[0]["synonyms"] = R.dedupe(senses[0]["synonyms"] + [_text(r) for r in xr.findall(TEI_NS + "ref")])
    if not senses:
        return None
    return {
        "word": word, "lang": src, "pos": pos, "pron": pron, "senses": senses,
        "translations": {dst: R.dedupe(translations)} if translations else {},
        "forms": orths[1:], "extra": {},
    }


def iter_tei(path: Path, src: Optional[str] = None, dst: Optional[str] = None,
             **_options) -> Iterator[dict]:
    pair = pair_from_name(path.name)
    if pair:
        src = src or pair[0]
        dst = dst or pair[1]
    stream = open_tei(path)
    try:
        for event, el in ET.iterparse(stream, events=("end",)):
            tag = _strip_ns(el.tag)
            if tag == "entry":
                entry = parse_entry(el, src or "", dst or "")
                el.clear()
                if entry:
                    yield entry
            elif tag == "teiHeader" and (not src or not dst):
                # <sourceDesc> / title like "German - English"
                for lang_el in el.iter(TEI_NS + "language"):
                    ident = lang_el.get("ident")
                    code = languages.normalize(ident)
                    if code and not src:
                        src = code
                    elif code and not dst and code != src:
                        dst = code
    finally:
        stream.close()
