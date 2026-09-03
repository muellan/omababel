"""Importers for the local dictionary formats omababel understands.

Every importer is a generator of entry dicts (see :mod:`ob.store`).
:func:`detect` guesses the format of a file from its name and first bytes;
:func:`iter_entries` dispatches to the right importer.
"""

from __future__ import annotations

import gzip
import io
import lzma
import zipfile
from pathlib import Path
from typing import Iterator, Optional

FORMATS = {
    "kaikki": "kaikki.org / wiktextract JSONL",
    "tei": "FreeDict TEI XML",
    "dictd": "dictd (.index + .dict/.dict.dz)",
    "cedict": "CC-CEDICT (text or cc-cedict all.js)",
    "ecdict": "ECDICT CSV",
    "unihan": "Unihan database (txt/zip/directory)",
    "tsv": "Tab separated (word<TAB>definition[<TAB>pos])",
    "json": "omababel JSON entry list",
}


def open_text(path: Path, encoding: str = "utf-8"):
    """Open a possibly compressed text file for reading."""
    name = path.name.lower()
    if name.endswith(".gz") or name.endswith(".dz"):
        return io.TextIOWrapper(gzip.open(path, "rb"), encoding=encoding, errors="replace")
    if name.endswith(".xz"):
        return io.TextIOWrapper(lzma.open(path, "rb"), encoding=encoding, errors="replace")
    return open(path, "r", encoding=encoding, errors="replace", newline="")


def _base_name(path: Path) -> str:
    name = path.name.lower()
    for ext in (".gz", ".xz", ".bz2", ".dz"):
        if name.endswith(ext):
            name = name[: -len(ext)]
    return name


def detect(path: Path) -> Optional[str]:
    if path.is_dir():
        return "unihan" if any(p.name.startswith("Unihan_") or p.name.startswith("k") for p in path.glob("*.txt")) else None
    name = _base_name(path)
    if name.startswith("unihan") or name.startswith("kdefinition") or name.startswith("kmandarin"):
        return "unihan"
    if name.endswith(".zip"):
        try:
            with zipfile.ZipFile(path) as zf:
                if any(n.startswith("Unihan_") for n in zf.namelist()):
                    return "unihan"
        except zipfile.BadZipFile:
            return None
        return None
    if name.endswith(".index") or name.endswith(".dict"):
        return "dictd"
    if name.endswith(".tei") or "freedict" in name and name.endswith(".xml"):
        return "tei"
    if "cedict" in name or name.endswith(".u8"):
        return "cedict"
    if "ecdict" in name or name == "stardict.csv":
        return "ecdict"
    if name.endswith(".jsonl") or name.endswith(".ndjson") or "kaikki" in name or "wiktextract" in name:
        return "kaikki"
    if name.endswith(".json") or name.endswith(".js"):
        # cc-cedict's all.js vs. our own JSON list
        try:
            with open_text(path) as fh:
                head = fh.read(400)
        except OSError:
            return None
        if '"all"' in head or "variantLookup" in head:
            return "cedict"
        return "json"
    if name.endswith(".csv"):
        try:
            with open_text(path) as fh:
                head = fh.readline()
        except OSError:
            return None
        return "ecdict" if head.startswith("word,phonetic") else "tsv"
    if name.endswith(".tsv") or name.endswith(".txt"):
        try:
            with open_text(path) as fh:
                head = fh.read(2000)
        except OSError:
            return None
        if "\tkDefinition\t" in head or "\tkMandarin\t" in head:
            return "unihan"
        if head.lstrip().startswith("#") and "CC-CEDICT" in head:
            return "cedict"
        for line in head.splitlines():
            if line and not line.startswith("#"):
                if " [" in line and "] /" in line:
                    return "cedict"
                break
        return "tsv"
    if name.endswith(".xml"):
        return "tei"
    return None


def iter_entries(path: Path, fmt: Optional[str] = None, lang: Optional[str] = None,
                 **options) -> Iterator[dict]:
    fmt = fmt or detect(path)
    if fmt == "kaikki":
        from .kaikki import iter_kaikki
        return iter_kaikki(path, lang=lang, **options)
    if fmt == "tei":
        from .tei import iter_tei
        return iter_tei(path, **options)
    if fmt == "dictd":
        from .dictd import iter_dictd
        return iter_dictd(path, **options)
    if fmt == "cedict":
        from .cedict import iter_cedict
        return iter_cedict(path, **options)
    if fmt == "ecdict":
        from .ecdict import iter_ecdict
        return iter_ecdict(path, **options)
    if fmt == "unihan":
        from .unihan import iter_unihan
        return iter_unihan(path, **options)
    if fmt == "tsv":
        from .simple import iter_tsv
        return iter_tsv(path, lang=lang, **options)
    if fmt == "json":
        from .simple import iter_json
        return iter_json(path, lang=lang, **options)
    raise ValueError(f"cannot determine dictionary format of {path}")
