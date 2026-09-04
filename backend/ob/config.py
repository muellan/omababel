"""``sources.json`` and ``prefs.json``.

``sources.json`` holds the editable list of search sources.  Built-in rows
carry ``"builtin": true``; when a new plugin version adds built-ins they
are appended to the user's list (unless the user deleted them before –
those ids are remembered in ``removed_builtins``).  User edits to a
built-in row are never overwritten.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Dict, List, Optional

from . import languages, secrets
from .paths import config_dir, state_dir

SOURCE_TYPES = ("dictionary", "thesaurus", "translator")
TRANSLATION_MODES = ("word", "text")

FIELDS = ("id", "name", "enabled", "type", "kind", "driver", "url", "path", "format",
          "dataset", "translation_mode", "api_key", "api_key_env", "api_key_cmd", "has_key",
          "languages", "pairs", "builtin", "notes")

# Never written to disk: the secret itself lives in the keyring (see ob.secrets).
SECRET_FIELDS = ("api_key",)


def _lang_name(code: str) -> str:
    return languages.name(code)


def default_sources() -> List[dict]:
    """The built-in source rows."""
    rows: List[dict] = []

    def row(id, name, type, driver, **kw) -> dict:
        r = {"id": id, "name": name, "enabled": True, "type": type, "driver": driver,
             "kind": "local" if driver == "local" else "remote", "url": "", "path": "",
             "format": "", "dataset": "", "translation_mode": "text" if type == "translator" else "",
             "api_key": "", "languages": [], "pairs": [], "builtin": True, "notes": ""}
        r.update(kw)
        return r

    # ---- remote dictionaries / thesauri
    rows.append(row("duden", "Duden", "dictionary", "duden", url="https://www.duden.de/rechtschreibung/{slug}",
                    languages=["de"]))
    rows.append(row("merriam-webster", "Merriam-Webster", "dictionary", "mw",
                    url="https://www.merriam-webster.com/dictionary/{word}", languages=["en"]))
    rows.append(row("merriam-webster-thesaurus", "Merriam-Webster Thesaurus", "thesaurus", "mw",
                    url="https://www.merriam-webster.com/thesaurus/{word}", languages=["en"]))
    rows.append(row("oed", "Oxford English Dictionary", "dictionary", "oed", enabled=False,
                    url="https://www.oed.com/search/dictionary/?scope=Entries&q={word}", languages=["en"],
                    notes="Subscription site; free access only returns search snippets. Enter an OED Researcher API credential (app_id:app_key) for full entries."))
    rows.append(row("thesaurus-com", "Thesaurus.com", "thesaurus", "thesauruscom",
                    url="https://www.thesaurus.com/browse/{word}", languages=["en"]))
    # ---- remote translators
    rows.append(row("leo", "LEO", "translator", "leo", url="https://dict.leo.org/", translation_mode="word"))
    # The key-less web endpoints of both services rate-limit within a handful
    # of requests, so they ship disabled; enable them after adding an API key.
    rows.append(row("google-translate", "Google Translate", "translator", "google", enabled=False,
                    url="https://translate.googleapis.com/translate_a/single", translation_mode="text",
                    notes="Disabled by default: the free endpoint rate-limits quickly. Add a Cloud Translation API key, then enable."))
    rows.append(row("deepl", "DeepL", "translator", "deepl", enabled=False, url="https://www.deepl.com/translator",
                    translation_mode="text",
                    notes="Disabled by default: the free endpoint rate-limits quickly. Add a DeepL API key, then enable."))
    # ---- local datasets (installed on demand)
    for code in languages.DEFAULT_LANGUAGES:
        lname = _lang_name(code)
        ds = f"wiktionary-{code}"
        rows.append(row(f"{ds}", f"Wiktionary ({lname}, English edition)", "dictionary", "local",
                        path=f"{ds}.sqlite", dataset=ds, languages=[code]))
        rows.append(row(f"{ds}-thesaurus", f"Wiktionary synonyms ({lname}, English edition)", "thesaurus", "local",
                        path=f"{ds}.sqlite", dataset=ds, languages=[code]))
        rows.append(row(f"{ds}-translator", f"Wiktionary translations ({lname})", "translator", "local",
                        path=f"{ds}.sqlite", dataset=ds, translation_mode="word"))
        if code != "en":
            nds = f"wiktionary-{code}-native"
            rows.append(row(nds, f"Wiktionary ({lname} edition)", "dictionary", "local",
                            path=f"{nds}.sqlite", dataset=nds, languages=[code]))
            rows.append(row(f"{nds}-thesaurus", f"Wiktionary synonyms ({lname} edition)", "thesaurus", "local",
                            path=f"{nds}.sqlite", dataset=nds, languages=[code]))
    for pair in ("deu-eng", "eng-deu", "deu-fra", "fra-deu", "deu-spa", "spa-deu", "deu-por", "por-deu",
                 "eng-fra", "fra-eng", "eng-spa", "spa-eng", "eng-por", "por-eng", "eng-jpn", "jpn-eng",
                 "deu-jpn", "jpn-deu", "eng-zho"):
        a, b = pair.split("-")
        ca, cb = languages.normalize(a) or a, languages.normalize(b) or b
        rows.append(row(f"freedict-{pair}", f"FreeDict {_lang_name(ca)} → {_lang_name(cb)}", "translator", "local",
                        path=f"freedict-{pair}.sqlite", dataset=f"freedict-{pair}", translation_mode="word",
                        pairs=[[ca, cb], [cb, ca]]))
    rows.append(row("cedict", "CC-CEDICT", "dictionary", "local", path="cedict.sqlite", dataset="cedict",
                    languages=["zh"]))
    rows.append(row("cedict-translator", "CC-CEDICT translations", "translator", "local", path="cedict.sqlite",
                    dataset="cedict", translation_mode="word", pairs=[["zh", "en"], ["en", "zh"]]))
    rows.append(row("ecdict", "ECDICT", "dictionary", "local", path="ecdict.sqlite", dataset="ecdict",
                    languages=["en"]))
    rows.append(row("ecdict-translator", "ECDICT translations", "translator", "local", path="ecdict.sqlite",
                    dataset="ecdict", translation_mode="word", pairs=[["en", "zh"], ["zh", "en"]]))
    rows.append(row("unihan", "Unihan characters", "dictionary", "local", path="unihan.sqlite", dataset="unihan",
                    languages=["zh", "ja"]))
    return rows


def normalize_source(src: dict) -> dict:
    """Coerce a row into the canonical shape (missing fields filled in)."""
    out = {
        "id": str(src.get("id") or "").strip(),
        "name": str(src.get("name") or src.get("id") or "").strip(),
        "enabled": bool(src.get("enabled", True)),
        "type": src.get("type") if src.get("type") in SOURCE_TYPES else "dictionary",
        "driver": str(src.get("driver") or ("local" if src.get("path") else "generic")),
        "url": str(src.get("url") or "").strip(),
        "path": str(src.get("path") or "").strip(),
        "format": str(src.get("format") or "").strip(),
        "dataset": str(src.get("dataset") or "").strip(),
        "translation_mode": src.get("translation_mode") if src.get("translation_mode") in TRANSLATION_MODES else "",
        "api_key": str(src.get("api_key") or ""),
        "api_key_env": str(src.get("api_key_env") or "").strip(),
        "api_key_cmd": str(src.get("api_key_cmd") or "").strip(),
        # not a secret: whether one is in the keyring.  Without it every row
        # would need a keyring round trip on every request.
        "has_key": bool(src.get("has_key") or src.get("api_key")),
        "builtin": bool(src.get("builtin", False)),
        "notes": str(src.get("notes") or ""),
    }
    out["kind"] = "local" if out["driver"] == "local" else "remote"
    langs = src.get("languages") or []
    if isinstance(langs, str):
        langs = [x.strip() for x in langs.replace(";", ",").split(",") if x.strip()]
    out["languages"] = [languages.normalize(x) or x for x in langs]
    pairs = src.get("pairs") or []
    if isinstance(pairs, str):
        pairs = [p.strip() for p in pairs.replace(";", ",").split(",") if p.strip()]
    norm_pairs: List[List[str]] = []
    for p in pairs:
        if isinstance(p, str) and "-" in p:
            a, b = p.split("-", 1)
        elif isinstance(p, (list, tuple)) and len(p) == 2:
            a, b = p
        else:
            continue
        norm_pairs.append([languages.normalize(a) or str(a), languages.normalize(b) or str(b)])
    out["pairs"] = norm_pairs
    if out["type"] == "translator" and not out["translation_mode"]:
        out["translation_mode"] = "word" if out["driver"] in ("local", "leo") else "text"
    if not out["id"]:
        out["id"] = _slug(out["name"]) or "source"
    return out


def _slug(text: str) -> str:
    import re
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:40]


class SourcesConfig:
    FILE = "sources.json"

    def __init__(self, path: Optional[Path] = None):
        self.path = path or (config_dir() / self.FILE)
        self.sources: List[dict] = []
        self.removed_builtins: List[str] = []
        # ids whose key is still in the file because no keyring took it
        self.insecure: List[str] = []
        self.load()

    # ------------------------------------------------------------- io
    def load(self) -> None:
        data = None
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                data = None
        if not isinstance(data, dict):
            data = {}
        self.removed_builtins = [str(x) for x in data.get("removed_builtins") or []]
        rows = [normalize_source(s) for s in data.get("sources") or [] if isinstance(s, dict)]
        self.sources = rows
        changed = self._merge_defaults()
        changed = self._migrate_plaintext_keys() or changed
        if not self.path.exists() or changed:
            self.save()

    def _migrate_plaintext_keys(self) -> bool:
        """Move keys an older version wrote into sources.json to the keyring.

        A row whose key cannot be moved (no keyring on this system) keeps it,
        but is flagged so the panel and the CLI can say so.
        """
        changed = False
        for row in self.sources:
            if not row.get("api_key"):
                continue
            try:
                secrets.store(row["id"], row["api_key"])
            except secrets.SecretError:
                self.insecure.append(row["id"])
                continue
            row["api_key"] = ""
            row["has_key"] = True
            changed = True
        return changed

    def _merge_defaults(self) -> bool:
        present = {s["id"] for s in self.sources}
        changed = False
        for d in default_sources():
            if d["id"] in present or d["id"] in self.removed_builtins:
                continue
            self.sources.append(normalize_source(d))
            changed = True
        return changed

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        rows = []
        for s in self.sources:
            row = dict(s)
            if s["id"] not in self.insecure:
                for field in SECRET_FIELDS:
                    row[field] = ""          # secrets belong in the keyring
            rows.append(row)
        payload = {"version": 1, "sources": rows, "removed_builtins": self.removed_builtins}
        _atomic_write(self.path, json.dumps(payload, indent=2, ensure_ascii=False) + "\n", mode=0o600)

    # -------------------------------------------------------- secrets
    def set_key(self, source_id: str, value: str) -> None:
        """Store (or, for an empty value, drop) a source's secret."""
        if value:
            secrets.store(source_id, value)
        else:
            secrets.remove(source_id)
        row = self.get(source_id)
        if row is not None:
            row["api_key"] = ""
            row["has_key"] = bool(value)
            if source_id in self.insecure:
                self.insecure.remove(source_id)
            self.save()

    def key_for(self, source_id: str) -> str:
        row = self.get(source_id)
        return "" if row is None else (row.get("api_key") or secrets.resolve(row))

    def with_keys(self) -> List[dict]:
        """Rows with their secret filled in – for building sources."""
        out = []
        for s in self.sources:
            row = dict(s)
            row["api_key"] = s.get("api_key") or secrets.resolve(s)
            out.append(row)
        return out

    # ----------------------------------------------------------- edits
    def get(self, source_id: str) -> Optional[dict]:
        for s in self.sources:
            if s["id"] == source_id:
                return s
        return None

    def upsert(self, src: dict) -> dict:
        """Update the row with ``src["id"]`` or append a new row (no id given).

        A secret in ``api_key`` is moved straight into the keyring; it is
        never part of the stored row.
        """
        row = normalize_source(src)
        secret = row["api_key"]
        row["api_key"] = ""
        existing = self.get(row["id"]) if str(src.get("id") or "").strip() else None
        if existing is not None:
            row["builtin"] = existing.get("builtin", False)
            idx = self.sources.index(existing)
            self.sources[idx] = row
        else:
            base = row["id"]
            n = 2
            while self.get(row["id"]) is not None:
                row["id"] = f"{base}-{n}"
                n += 1
            self.sources.append(row)
        self.save()
        if secret:
            self.set_key(row["id"], secret)
        return row

    def delete(self, source_id: str) -> bool:
        existing = self.get(source_id)
        if existing is None:
            return False
        secrets.remove(source_id)
        self.sources.remove(existing)
        if existing.get("builtin") and source_id not in self.removed_builtins:
            self.removed_builtins.append(source_id)
        self.save()
        return True

    def set_enabled(self, source_id: str, enabled: bool) -> bool:
        existing = self.get(source_id)
        if existing is None:
            return False
        existing["enabled"] = bool(enabled)
        self.save()
        return True

    def move(self, source_id: str, delta: int) -> bool:
        existing = self.get(source_id)
        if existing is None:
            return False
        idx = self.sources.index(existing)
        new = max(0, min(len(self.sources) - 1, idx + delta))
        if new == idx:
            return False
        self.sources.pop(idx)
        self.sources.insert(new, existing)
        self.save()
        return True

    def reset_defaults(self) -> None:
        self.sources = [normalize_source(d) for d in default_sources()]
        self.removed_builtins = []
        self.save()

    def public(self) -> List[dict]:
        """Rows for the UI – secrets are never included, only where they live."""
        out = []
        for s in self.sources:
            row = dict(s)
            store = secrets.describe(s)
            row["key_storage"] = "file" if s.get("api_key") else store
            row["has_key"] = bool(s.get("api_key")) or bool(store)
            row["supports_key"] = bool(s.get("has_key")) or row["has_key"]
            row["key_insecure"] = s["id"] in self.insecure
            row["api_key"] = ""
            out.append(row)
        return out


DEFAULT_PREFS = {
    "mode": "lookup",
    "lang": "de",
    "lang2": "en",
    "thesaurus_sort": "alpha",
    "history_max": 1000,
    "panel_width": 0,
    "panel_height": 0,
    "font_scale": 1.0,
}


class Prefs:
    FILE = "prefs.json"

    def __init__(self, path: Optional[Path] = None):
        self.path = path or (config_dir() / self.FILE)
        self.data: Dict[str, object] = dict(DEFAULT_PREFS)
        if self.path.exists():
            try:
                loaded = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    self.data.update(loaded)
            except (ValueError, OSError):
                pass

    def update(self, values: dict) -> dict:
        for k, v in values.items():
            if k in ("lang", "lang2"):
                v = languages.normalize(str(v)) or DEFAULT_PREFS[k]
            if k == "mode" and v not in ("lookup", "thesaurus", "translate"):
                continue
            if k == "thesaurus_sort" and v not in ("alpha", "length"):
                continue
            if k == "history_max":
                try:
                    v = max(1, min(100000, int(v)))
                except (TypeError, ValueError):
                    continue
            self.data[k] = v
        self.save()
        return dict(self.data)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(self.path, json.dumps(self.data, indent=2, ensure_ascii=False) + "\n")


def _atomic_write(path: Path, text: str, mode: Optional[int] = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-", suffix=path.suffix)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        if mode is not None:
            os.chmod(tmp, mode)
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
