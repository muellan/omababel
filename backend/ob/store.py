"""SQLite index for local dictionaries.

All local formats (kaikki JSONL, FreeDict TEI, CC-CEDICT, ECDICT, Unihan,
dictd, TSV, JSON) are normalised into one schema so lookups, thesaurus
queries and word translations run the same code.  An index is built once
(``omababel data install`` or lazily on first use for raw files) and then
queried with plain SQL.

Entry record (as produced by the importers)::

    {"word": "Haus", "lang": "de", "pos": "noun", "pron": "haʊs",
     "senses": [sense...], "translations": {"en": ["house"]},
     "forms": ["Häuser"], "extra": {...}}
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Callable, Dict, Iterable, Iterator, List, Optional

from . import results as R
from .paths import cache_dir

SCHEMA_VERSION = 3

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS entries(
  id INTEGER PRIMARY KEY,
  word TEXT NOT NULL,
  norm TEXT NOT NULL,
  lang TEXT NOT NULL,
  pos TEXT NOT NULL DEFAULT '',
  pron TEXT NOT NULL DEFAULT '',
  senses TEXT NOT NULL DEFAULT '[]',
  translations TEXT NOT NULL DEFAULT '{}',
  extra TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_entries_norm ON entries(norm, lang);
CREATE TABLE IF NOT EXISTS forms(norm TEXT NOT NULL, entry_id INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS idx_forms_norm ON forms(norm);
CREATE TABLE IF NOT EXISTS rev(norm TEXT NOT NULL, lang TEXT NOT NULL, entry_id INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS idx_rev_norm ON rev(norm, lang);
"""

Progress = Callable[[str, int], None]


def norm(word: str) -> str:
    return R.fold(R.clean(word))


class Store:
    def __init__(self, path: Path, readonly: bool = False):
        self.path = Path(path)
        self.readonly = readonly
        if readonly:
            uri = f"file:{self.path}?mode=ro"
            self.conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.conn = sqlite3.connect(str(self.path), check_same_thread=False)
            self.conn.executescript(SCHEMA)
        self.conn.row_factory = sqlite3.Row

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ------------------------------------------------------------- meta
    def set_meta(self, key: str, value) -> None:
        self.conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
                          (key, json.dumps(value, ensure_ascii=False)))

    def get_meta(self, key: str, default=None):
        try:
            row = self.conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        except sqlite3.OperationalError:
            return default
        if row is None:
            return default
        try:
            return json.loads(row[0])
        except ValueError:
            return row[0]

    def info(self) -> dict:
        try:
            count = self.conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
            langs = [r[0] for r in self.conn.execute("SELECT DISTINCT lang FROM entries LIMIT 50")]
        except sqlite3.OperationalError:
            count, langs = 0, []
        return {
            "path": str(self.path),
            "entries": count,
            "languages": langs,
            "format": self.get_meta("format"),
            "source": self.get_meta("source"),
            "title": self.get_meta("title"),
            "license": self.get_meta("license"),
            "built": self.get_meta("built"),
        }

    # ----------------------------------------------------------- import
    def import_entries(self, entries: Iterable[dict], meta: Optional[dict] = None,
                       progress: Optional[Progress] = None, replace: bool = True) -> int:
        if self.readonly:
            raise RuntimeError("store is read-only")
        cur = self.conn.cursor()
        cur.execute("PRAGMA journal_mode=OFF")
        cur.execute("PRAGMA synchronous=OFF")
        if replace:
            cur.execute("DELETE FROM entries")
            cur.execute("DELETE FROM forms")
            cur.execute("DELETE FROM rev")
        count = 0
        batch_e: List[tuple] = []
        batch_f: List[tuple] = []
        batch_r: List[tuple] = []
        next_id = (cur.execute("SELECT COALESCE(MAX(id), 0) FROM entries").fetchone()[0] or 0) + 1
        last_report = time.time()
        seen_langs: Dict[str, int] = {}
        seen_tlangs: Dict[str, int] = {}

        def flush() -> None:
            if batch_e:
                cur.executemany("INSERT INTO entries(id, word, norm, lang, pos, pron, senses, translations, extra)"
                                " VALUES (?,?,?,?,?,?,?,?,?)", batch_e)
                batch_e.clear()
            if batch_f:
                cur.executemany("INSERT INTO forms(norm, entry_id) VALUES (?,?)", batch_f)
                batch_f.clear()
            if batch_r:
                cur.executemany("INSERT INTO rev(norm, lang, entry_id) VALUES (?,?,?)", batch_r)
                batch_r.clear()

        for e in entries:
            word = R.clean(e.get("word", ""))
            if not word:
                continue
            eid = next_id
            next_id += 1
            senses = e.get("senses") or []
            translations = e.get("translations") or {}
            batch_e.append((eid, word, norm(word), e.get("lang") or "", e.get("pos") or "",
                            e.get("pron") or "", json.dumps(senses, ensure_ascii=False),
                            json.dumps(translations, ensure_ascii=False),
                            json.dumps(e.get("extra") or {}, ensure_ascii=False)))
            lang_code = e.get("lang") or ""
            seen_langs[lang_code] = seen_langs.get(lang_code, 0) + 1
            for tl in translations:
                seen_tlangs[tl] = seen_tlangs.get(tl, 0) + 1
            seen_forms = {norm(word)}
            for f in e.get("forms") or []:
                nf = norm(f)
                if nf and nf not in seen_forms:
                    seen_forms.add(nf)
                    batch_f.append((nf, eid))
            for lang, words in translations.items():
                seen_t = set()
                for w in words:
                    nw = norm(w)
                    if nw and nw not in seen_t and len(nw) <= 80:
                        seen_t.add(nw)
                        batch_r.append((nw, lang, eid))
            count += 1
            if len(batch_e) >= 2000:
                flush()
            if progress and time.time() - last_report > 0.5:
                progress("importing", count)
                last_report = time.time()
        flush()
        self.set_meta("schema", SCHEMA_VERSION)
        self.set_meta("built", int(time.time()))
        self.set_meta("count", count)
        self.set_meta("languages", sorted(seen_langs, key=lambda k: -seen_langs[k]))
        self.set_meta("translation_langs", sorted(seen_tlangs, key=lambda k: -seen_tlangs[k]))
        for k, v in (meta or {}).items():
            self.set_meta(k, v)
        self.conn.commit()
        if progress:
            progress("imported", count)
        return count

    # ------------------------------------------------------------ query
    @staticmethod
    def _row_to_entry(row: sqlite3.Row) -> dict:
        senses = json.loads(row["senses"] or "[]")
        translations = json.loads(row["translations"] or "{}")
        extra = json.loads(row["extra"] or "{}")
        return {
            "id": row["id"], "word": row["word"], "lang": row["lang"], "pos": row["pos"],
            "pron": row["pron"], "senses": senses, "translations": translations, "extra": extra,
        }

    def _by_ids(self, ids: List[int]) -> List[dict]:
        if not ids:
            return []
        out: List[dict] = []
        for i in range(0, len(ids), 500):
            chunk = ids[i:i + 500]
            q = "SELECT * FROM entries WHERE id IN (%s) ORDER BY id" % ",".join("?" * len(chunk))
            out.extend(self._row_to_entry(r) for r in self.conn.execute(q, chunk))
        return out

    def lookup(self, word: str, lang: Optional[str] = None, limit: int = 40,
               prefix: bool = True) -> List[dict]:
        key = norm(word)
        if not key:
            return []
        params: list = [key]
        sql = "SELECT * FROM entries WHERE norm = ?"
        if lang:
            sql += " AND lang = ?"
            params.append(lang)
        rows = self.conn.execute(sql + " ORDER BY id LIMIT ?", params + [limit]).fetchall()
        out = [self._row_to_entry(r) for r in rows]
        if not out:
            fsql = ("SELECT e.* FROM forms f JOIN entries e ON e.id = f.entry_id WHERE f.norm = ?"
                    + (" AND e.lang = ?" if lang else "") + " ORDER BY e.id LIMIT ?")
            rows = self.conn.execute(fsql, params + [limit]).fetchall()
            out = [self._row_to_entry(r) for r in rows]
            for e in out:
                e["matched_form"] = word
        if not out and prefix and len(key) >= 2:
            psql = ("SELECT * FROM entries WHERE norm >= ? AND norm < ?"
                    + (" AND lang = ?" if lang else "") + " ORDER BY norm, id LIMIT ?")
            rows = self.conn.execute(psql, [key, key + "￿"] + ([lang] if lang else []) + [limit]).fetchall()
            out = [self._row_to_entry(r) for r in rows]
            for e in out:
                e["prefix_match"] = True
        return out

    def thesaurus(self, word: str, lang: Optional[str] = None) -> dict:
        entries = self.lookup(word, lang, prefix=False)
        groups = R.groups_from_senses(entries)
        for e in entries:
            extra_syn = e["extra"].get("synonyms") if isinstance(e["extra"].get("synonyms"), list) else []
            extra_ant = e["extra"].get("antonyms") if isinstance(e["extra"].get("antonyms"), list) else []
            if extra_syn or extra_ant:
                groups.append(R.group(extra_syn, extra_ant, pos=e.get("pos", "")))
        return R.thesaurus([], [], groups=groups)

    def translate(self, word: str, src: str, dst: str, limit: int = 60) -> List[dict]:
        """Word translations ``src -> dst`` as result pairs."""
        pairs: List[dict] = []
        seen = set()
        for e in self.lookup(word, src, prefix=False):
            words = e["translations"].get(dst) or []
            for w in words:
                k = (R.fold(e["word"]), R.fold(w))
                if k not in seen:
                    seen.add(k)
                    pairs.append(R.pair(e["word"], w, pos=e["pos"]))
            if not words and dst == "en":
                # Monolingual-English glosses (kaikki English edition, CEDICT, Unihan)
                for s in e["senses"]:
                    g = s.get("gloss", "")
                    if g and s.get("lang", "en") == "en":
                        k = (R.fold(e["word"]), R.fold(g))
                        if k not in seen:
                            seen.add(k)
                            pairs.append(R.pair(e["word"], g, pos=e["pos"]))
        if len(pairs) < limit:
            # reverse direction: dst-language word appearing as a translation
            key = norm(word)
            rows = self.conn.execute(
                "SELECT entry_id FROM rev WHERE norm = ? AND lang = ? LIMIT ?", (key, src, limit)
            ).fetchall()
            ids = [r[0] for r in rows]
            for e in self._by_ids(ids):
                if e["lang"] != dst:
                    continue
                k = (R.fold(word), R.fold(e["word"]))
                if k not in seen:
                    seen.add(k)
                    pairs.append(R.pair(word, e["word"], pos=e["pos"]))
        return pairs[:limit]

    def languages(self) -> List[str]:
        return [r[0] for r in self.conn.execute("SELECT DISTINCT lang FROM entries")]


# ----------------------------------------------------------------- caching

def cache_path_for(source_path: Path) -> Path:
    try:
        st = source_path.stat()
        stamp = f"{source_path.resolve()}|{st.st_size}|{int(st.st_mtime)}"
    except OSError:
        stamp = str(source_path)
    digest = hashlib.sha1(stamp.encode("utf-8")).hexdigest()[:16]
    return cache_dir() / f"{source_path.stem}-{digest}.sqlite"


def is_store(path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        with open(path, "rb") as fh:
            return fh.read(16) == b"SQLite format 3\x00"
    except OSError:
        return False


def open_store(path: Path, builder: Optional[Callable[[Path, Progress], None]] = None,
               progress: Optional[Progress] = None) -> Store:
    """Open ``path`` if it is an index, else build/reuse a cached index for it."""
    if is_store(path):
        return Store(path, readonly=True)
    if builder is None:
        raise FileNotFoundError(f"{path} is not an omababel index")
    cpath = cache_path_for(path)
    if not is_store(cpath):
        tmp = cpath.with_suffix(".building")
        if tmp.exists():
            tmp.unlink()
        builder(tmp, progress or (lambda *_: None))
        os.replace(tmp, cpath)
    return Store(cpath, readonly=True)
