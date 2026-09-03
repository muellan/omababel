"""Downloadable dictionary datasets.

``omababel data list|install|remove|status`` (and the *Data* tab of the
preferences panel) work on the catalogue below.  Installing a dataset
streams the download into ``<data>/downloads``, converts it into an
``<data>/<id>.sqlite`` index and deletes the download again.

The big Wiktionary/FreeDict dumps are GPL / CC BY-SA licensed and several
hundred MB, which is why they are fetched on demand instead of being
bundled with the (MIT) plugin.
"""

from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path
from typing import Callable, Dict, Iterator, List, Optional

from . import formats, http, languages, store
from .paths import data_dir

Progress = Callable[[dict], None]

KAIKKI_LANG_URL = "https://kaikki.org/dictionary/{name}/kaikki.org-dictionary-{name}.jsonl"
KAIKKI_EDITION_URL = "https://kaikki.org/dictionary/downloads/{code}/{code}-extract.jsonl.gz"
KAIKKI_EDITIONS = ["de", "fr", "es", "pt", "ja", "zh", "it", "ru", "pl", "nl", "ko", "cs",
                   "el", "th", "tr", "vi", "id", "ms"]
FREEDICT_DB = "https://freedict.org/freedict-database.json"
FREEDICT_DIR = "https://download.freedict.org/dictionaries/{pair}/"
CEDICT_URLS = [
    "https://raw.githubusercontent.com/edvardsr/cc-cedict/main/data/all.js",
    "https://www.mdbg.net/chinese/export/cedict/cedict_1_0_ts_utf-8_mdbg.txt.gz",
]
ECDICT_URL = "https://raw.githubusercontent.com/skywind3000/ECDICT/master/ecdict.csv"
UNIHAN_URLS = [
    "https://www.unicode.org/Public/UCD/latest/ucd/Unihan.zip",
]
UNIHAN_GITHUB = ["https://raw.githubusercontent.com/unicode-org/unihan-database/main/kDefinition.txt",
                 "https://raw.githubusercontent.com/unicode-org/unihan-database/main/kCantonese.txt"]

# Pairs of the default languages that FreeDict actually provides.
FREEDICT_DEFAULT_PAIRS = [
    "deu-eng", "eng-deu", "deu-fra", "fra-deu", "deu-spa", "spa-deu", "deu-por", "por-deu",
    "deu-ita", "ita-deu", "deu-jpn", "jpn-deu", "eng-fra", "fra-eng", "eng-spa", "spa-eng",
    "eng-por", "por-eng", "eng-ita", "ita-eng", "eng-jpn", "jpn-eng", "eng-zho", "fra-zho",
    "fra-spa", "spa-fra", "fra-por", "por-fra", "spa-por", "por-spa", "fra-jpn", "jpn-fra",
    "eng-rus", "rus-eng", "deu-rus", "rus-deu", "eng-nld", "nld-eng", "deu-nld", "nld-deu",
    "eng-pol", "pol-eng", "deu-pol", "pol-deu", "eng-swe", "swe-eng", "deu-swe", "swe-deu",
    "eng-lat", "lat-eng", "lat-deu", "eng-tur", "tur-eng", "deu-tur", "tur-deu",
]


# ------------------------------------------------------------------ catalogue

def catalog() -> List[dict]:
    items: List[dict] = []
    for code in languages.DEFAULT_LANGUAGES + sorted(c for c in languages.LANGUAGES if c not in languages.DEFAULT_LANGUAGES):
        info = languages.LANGUAGES[code]
        items.append({
            "id": f"wiktionary-{code}",
            "title": f"Wiktionary – {info['name']} (English edition)",
            "description": f"All {info['name']} entries of the English Wiktionary via kaikki.org: definitions in English, synonyms/antonyms, translations. Large (hundreds of MB).",
            "kind": "kaikki", "lang": code, "license": "CC BY-SA 4.0 / GFDL",
            "urls": [KAIKKI_LANG_URL.replace("{name}", http.quote(info["kaikki"]))],
            "types": ["dictionary", "thesaurus", "translator"],
            "default": code in languages.DEFAULT_LANGUAGES,
        })
        if code in KAIKKI_EDITIONS:
            items.append({
                "id": f"wiktionary-{code}-native",
                "title": f"Wiktionary – {info['name']} ({info['native']} edition)",
                "description": f"{info['name']} entries of the {info['native']} Wiktionary edition (kaikki.org): definitions in {info['name']}, synonyms/antonyms. Large.",
                "kind": "kaikki-edition", "lang": code, "license": "CC BY-SA 4.0 / GFDL",
                "urls": [KAIKKI_EDITION_URL.replace("{code}", code)],
                "types": ["dictionary", "thesaurus"],
                "default": code in languages.DEFAULT_LANGUAGES,
            })
    for pair in FREEDICT_DEFAULT_PAIRS:
        a, b = pair.split("-")
        items.append({
            "id": f"freedict-{pair}",
            "title": f"FreeDict {languages.name(a)} → {languages.name(b)}",
            "description": f"FreeDict bilingual word dictionary {pair} (TEI source release).",
            "kind": "freedict", "pair": pair, "license": "GPL (see dictionary header)",
            "urls": [],  # resolved from the FreeDict database at install time
            "types": ["translator", "dictionary"],
            "default": pair in ("deu-eng", "eng-deu", "deu-fra", "fra-deu", "deu-spa", "spa-deu",
                                "deu-por", "por-deu", "eng-fra", "fra-eng", "eng-spa", "spa-eng",
                                "eng-por", "por-eng", "eng-jpn", "jpn-eng", "deu-jpn", "jpn-deu", "eng-zho"),
        })
    items.append({
        "id": "cedict", "title": "CC-CEDICT (Chinese → English)",
        "description": "MDBG's CC-CEDICT: ~120k Chinese words with pinyin and English definitions (from github.com/edvardsr/cc-cedict).",
        "kind": "cedict", "lang": "zh", "license": "CC BY-SA 4.0", "urls": list(CEDICT_URLS),
        "types": ["dictionary", "translator"], "default": True,
    })
    items.append({
        "id": "ecdict", "title": "ECDICT (English ↔ Chinese)",
        "description": "skywind3000/ECDICT: 770k English headwords with IPA, English definitions, Chinese translations and inflections (66 MB).",
        "kind": "ecdict", "lang": "en", "license": "MIT", "urls": [ECDICT_URL],
        "types": ["dictionary", "translator"], "default": True,
    })
    items.append({
        "id": "unihan", "title": "Unihan (CJK characters)",
        "description": "Unicode Unihan database: readings and definitions for ~98k Han characters (Mandarin, Cantonese, Japanese, Korean).",
        "kind": "unihan", "lang": "zh", "license": "Unicode License v3", "urls": list(UNIHAN_URLS),
        "types": ["dictionary", "translator"], "default": True,
    })
    return items


def catalog_by_id() -> Dict[str, dict]:
    return {d["id"]: d for d in catalog()}


def index_path(dataset_id: str) -> Path:
    return data_dir() / f"{dataset_id}.sqlite"


def status(dataset_id: str) -> dict:
    p = index_path(dataset_id)
    out = {"id": dataset_id, "installed": p.exists(), "path": str(p)}
    if p.exists():
        try:
            out["size"] = p.stat().st_size
            with store.Store(p, readonly=True) as st:
                out.update(st.info())
        except Exception as e:  # pragma: no cover - defensive
            out["error"] = str(e)
    return out


def list_status() -> List[dict]:
    out = []
    for d in catalog():
        item = dict(d)
        item.update(status(d["id"]))
        out.append(item)
    return out


# ------------------------------------------------------------------- download

def download(url: str, target: Path, progress: Optional[Progress] = None,
             timeout: float = 60.0) -> Path:
    """Stream ``url`` into ``target`` (resumable-ish: restarts on failure)."""
    import urllib.request

    if os.environ.get("OMABABEL_OFFLINE"):
        raise http.FetchError("offline mode (OMABABEL_OFFLINE is set)", url=url)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": http.DEFAULT_UA, "Accept": "*/*"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp, open(tmp, "wb") as out:
            total = int(resp.headers.get("Content-Length") or 0)
            done = 0
            last = 0.0
            while True:
                chunk = resp.read(1024 * 256)
                if not chunk:
                    break
                out.write(chunk)
                done += len(chunk)
                now = time.time()
                if progress and now - last > 0.3:
                    progress({"phase": "download", "bytes": done, "total": total, "url": url})
                    last = now
    except Exception as e:
        if tmp.exists():
            tmp.unlink()
        raise http.FetchError(f"download failed: {e}", url=url)
    os.replace(tmp, target)
    if progress:
        progress({"phase": "download", "bytes": target.stat().st_size,
                  "total": target.stat().st_size, "url": url, "done": True})
    return target


def freedict_release_url(pair: str) -> str:
    """Find the TEI ``src`` release of a FreeDict dictionary."""
    try:
        db = http.fetch(FREEDICT_DB, headers={"Accept": "application/json"}, timeout=60).json()
        for d in db:
            if isinstance(d, dict) and d.get("name") == pair:
                releases = d.get("releases") or []
                for rel in releases:
                    if rel.get("platform") == "src" and rel.get("URL"):
                        return rel["URL"]
                for rel in releases:
                    if rel.get("platform") == "dictd" and rel.get("URL"):
                        return rel["URL"]
    except (http.FetchError, ValueError):
        pass
    # Fall back to the download directory listing.
    listing = http.fetch(FREEDICT_DIR.replace("{pair}", pair), timeout=60).text
    import re
    versions = sorted(set(re.findall(r'href="([0-9][^"/]*)/"', listing)),
                      key=lambda v: [int(x) if x.isdigit() else x for x in re.split(r"[.-]", v)])
    if not versions:
        raise http.FetchError(f"no FreeDict release found for {pair}")
    v = versions[-1]
    return f"https://download.freedict.org/dictionaries/{pair}/{v}/freedict-{pair}-{v}.src.tar.xz"


# -------------------------------------------------------------------- install

def _filename(url: str) -> str:
    import urllib.parse
    name = url.rsplit("/", 1)[-1].split("?")[0] or "download"
    return urllib.parse.unquote(name)


def install(dataset_id: str, progress: Optional[Progress] = None, keep_download: bool = False,
            source_file: Optional[Path] = None) -> dict:
    """Download + index ``dataset_id``.  ``source_file`` skips the download."""
    ds = catalog_by_id().get(dataset_id)
    if ds is None:
        raise ValueError(f"unknown dataset '{dataset_id}'")
    report = progress or (lambda _: None)
    downloads = data_dir() / "downloads"
    target = index_path(dataset_id)
    files: List[Path] = []
    if source_file is not None:
        files = [Path(source_file)]
    else:
        urls = list(ds["urls"])
        if ds["kind"] == "freedict":
            report({"phase": "resolve", "message": f"resolving FreeDict release for {ds['pair']}"})
            urls = [freedict_release_url(ds["pair"])]
        last_err: Optional[Exception] = None
        for url in urls:
            try:
                report({"phase": "download", "bytes": 0, "total": 0, "url": url})
                files = [download(url, downloads / _filename(url), progress=report)]
                break
            except http.FetchError as e:
                last_err = e
                report({"phase": "warning", "message": str(e)})
        if not files and ds["kind"] == "unihan":
            # GitHub review repo fallback: a couple of property files
            try:
                folder = downloads / "unihan-github"
                folder.mkdir(parents=True, exist_ok=True)
                for url in UNIHAN_GITHUB:
                    download(url, folder / _filename(url), progress=report)
                files = [folder]
            except http.FetchError as e:
                last_err = e
        if not files:
            raise http.FetchError(f"could not download {dataset_id}: {last_err}")
    src = files[0]
    fmt = {"kaikki": "kaikki", "kaikki-edition": "kaikki", "freedict": None, "cedict": "cedict",
           "ecdict": "ecdict", "unihan": "unihan"}[ds["kind"]]
    if fmt is None:
        fmt = "dictd" if ".dictd" in src.name else "tei"
    lang = ds.get("lang") if ds["kind"] == "kaikki-edition" else None
    opts = {}
    if ds["kind"] == "freedict":
        a, b = ds["pair"].split("-")
        opts = {"src": languages.normalize(a) or a, "dst": languages.normalize(b) or b}
    if ds["kind"] == "freedict" and fmt == "dictd":
        src = _extract_dictd(src, downloads / f"{dataset_id}-dictd")
    report({"phase": "import", "count": 0, "message": f"indexing {src.name}"})
    tmp = target.with_suffix(".building")
    if tmp.exists():
        tmp.unlink()
    count = 0
    try:
        with store.Store(tmp) as st:
            count = st.import_entries(
                formats.iter_entries(src, fmt=fmt, lang=lang, **opts),
                meta={"format": fmt, "source": str(src if source_file else (ds["urls"][0] if ds["urls"] else src)),
                      "title": ds["title"], "license": ds["license"], "dataset": dataset_id},
                progress=lambda phase, n: report({"phase": "import", "count": n}),
            )
    except Exception:
        if tmp.exists():
            tmp.unlink()
        raise
    if count == 0:
        tmp.unlink()
        raise ValueError(f"{dataset_id}: no entries found in {src.name} (format {fmt})")
    os.replace(tmp, target)
    if source_file is None and not keep_download:
        for f in files:
            if f.is_dir():
                shutil.rmtree(f, ignore_errors=True)
            elif f.exists():
                f.unlink()
    result = status(dataset_id)
    report({"phase": "done", "count": count, "path": str(target)})
    return result


def _extract_dictd(tarball: Path, folder: Path) -> Path:
    import tarfile
    folder.mkdir(parents=True, exist_ok=True)
    with tarfile.open(tarball, "r:*") as tf:
        members = [m for m in tf.getmembers() if m.isfile() and (m.name.endswith(".index") or ".dict" in m.name)]
        for m in members:
            m.name = os.path.basename(m.name)
            tf.extract(m, folder)
    idx = next(folder.glob("*.index"), None)
    if idx is None:
        raise ValueError("no .index file inside dictd archive")
    return idx


def remove(dataset_id: str) -> bool:
    p = index_path(dataset_id)
    if p.exists():
        p.unlink()
        return True
    return False


def import_file(dataset_id: str, path: Path, progress: Optional[Progress] = None) -> dict:
    """Index a file the user downloaded manually."""
    return install(dataset_id, progress=progress, source_file=path)
