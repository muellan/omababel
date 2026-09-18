"""Local file sources.

``path`` is relative to the app's data directory (``~/.local/share/omababel``)
unless absolute.  Indexes built by ``omababel data install`` are opened
directly; raw dictionary files (kaikki JSONL, TEI, CC-CEDICT, ECDICT,
Unihan, dictd, TSV, JSON) are indexed into the cache on first use.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import List, Optional, Tuple

from .. import formats, languages, store
from .. import results as R
from ..paths import resolve_local
from .base import Source, SourceError, register


# `wiktionary-de` (the English edition's German entries) and
# `wiktionary-de-native` (the German edition) -- the two shapes `ob.data`
# publishes.  Both have a web edition to ask while the dump is not installed.
_WIKTIONARY_DATASET = re.compile(r"^wiktionary-([a-z]{2,3})(-native)?$")

_UNSET = object()


def _is_cjk_word(text: str) -> bool:
    text = text.strip()
    if len(text) < 1 or len(text) > 12:
        return False
    return all(("一" <= ch <= "鿿") or ("㐀" <= ch <= "䶿")
               or ("\U00020000" <= ch <= "\U0002ffff") for ch in text)


@register
class Local(Source):
    driver = "local"
    label = "Local file"
    kind = "local"
    types = ("dictionary", "thesaurus", "translator")
    description = ("A dictionary file in the app's local storage: kaikki/wiktextract JSONL, FreeDict TEI, "
                   "CC-CEDICT, ECDICT CSV, Unihan, dictd, TSV or an index built by 'omababel data install'.")
    translation_modes = ("word",)
    order = 1

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        self.format = str(cfg.get("format") or "")
        self.dataset = str(cfg.get("dataset") or "")
        self._store: Optional[store.Store] = None
        self._meta_cache: Optional[dict] = None
        self._fallback = _UNSET

    # ------------------------------------------------------------ fallback
    def web_fallback(self):
        """The live source to use while this row's dataset is missing.

        A Wiktionary dump is hundreds of megabytes and is installed on
        demand, so until it is there the row would simply not answer.  The
        same edition of Wiktionary is on the web, so ask that instead --
        slower and one page at a time, but an answer.
        """
        if self._fallback is _UNSET:
            self._fallback = self._build_fallback()
        return self._fallback

    def _build_fallback(self):
        m = _WIKTIONARY_DATASET.match(self.dataset)
        if not m:
            return None
        code, native = m.group(1), bool(m.group(2))
        if languages.normalize(code) is None:
            return None
        edition = code if native else "en"
        from .wiktionary import API, Wiktionary
        cfg = dict(self.cfg)
        cfg["driver"] = "wiktionary"
        cfg["kind"] = "remote"
        cfg["path"] = ""
        cfg["url"] = API.replace("{edition}", edition)
        if not cfg.get("languages"):
            cfg["languages"] = [code]
        if self.type == "translator" and not cfg.get("pairs"):
            # The translation tables of an entry point outwards from the
            # entry's own language, so this row translates `code` -> anything.
            cfg["pairs"] = [[code, other] for other in languages.LANGUAGES if other != code]
        try:
            return Wiktionary(cfg)
        except Exception:      # noqa: BLE001 - a fallback must never be fatal
            return None

    def available(self) -> bool:
        """False only when there is nothing at all to ask."""
        return self.installed() or self.web_fallback() is not None

    def describe(self) -> dict:
        out = super().describe()
        if not self.installed() and self.web_fallback() is not None:
            out["kind"] = "remote"
            out["name"] = f"{self.name} · web"
            out["fallback"] = "web"
        return out

    # --------------------------------------------------------------- files
    def file_path(self) -> Path:
        if not self.path:
            raise SourceError(f"{self.name}: no file path configured")
        return resolve_local(self.path)

    def installed(self) -> bool:
        try:
            return self.file_path().exists()
        except SourceError:
            return False

    def status(self) -> dict:
        try:
            p = self.file_path()
        except SourceError as e:
            return {"installed": False, "error": str(e)}
        if not p.exists():
            fallback = self.web_fallback()
            if fallback is not None:
                return {"installed": False, "path": str(p), "fallback": fallback.edition,
                        "note": f"not installed - querying {fallback.edition}.wiktionary.org",
                        "hint": f"run: omababel data install {self.dataset}"}
            hint = f"run: omababel data install {self.dataset}" if self.dataset else "file not found"
            return {"installed": False, "error": hint, "path": str(p)}
        try:
            with self._open() as st:
                info = st.info()
            info["installed"] = True
            return info
        except Exception as e:  # pragma: no cover - defensive
            return {"installed": True, "error": str(e), "path": str(p)}

    def _open(self) -> store.Store:
        p = self.file_path()
        if not p.exists():
            hint = f" (run: omababel data install {self.dataset})" if self.dataset else ""
            raise SourceError(f"{self.name}: {p} not found{hint}")
        lang = self.cfg_languages[0] if self.cfg_languages else None

        def build(target: Path, progress) -> None:
            fmt = self.format or formats.detect(p)
            if not fmt:
                raise SourceError(f"{self.name}: cannot determine format of {p.name}")
            with store.Store(target) as st:
                st.import_entries(formats.iter_entries(p, fmt=fmt, lang=lang),
                                  meta={"format": fmt, "source": str(p), "title": self.name},
                                  progress=progress)

        try:
            return store.open_store(p, builder=build)
        except (OSError, ValueError) as e:
            raise SourceError(f"{self.name}: {e}")

    def _meta(self) -> dict:
        if self._meta_cache is None:
            try:
                with self._open() as st:
                    self._meta_cache = {
                        "languages": st.get_meta("languages") or st.languages(),
                        "translation_langs": st.get_meta("translation_langs") or [],
                    }
            except SourceError:
                self._meta_cache = {"languages": [], "translation_langs": []}
        return self._meta_cache

    # -------------------------------------------------------- capabilities
    def effective_languages(self) -> List[str]:
        if self.cfg_languages:
            return self.cfg_languages
        if not self.installed():
            fallback = self.web_fallback()
            return fallback.effective_languages() if fallback is not None else []
        return [languages.normalize(x) or x for x in self._meta()["languages"] if x]

    def effective_pairs(self) -> List[Tuple[str, str]]:
        if self.cfg.get("pairs"):
            return super().effective_pairs()
        if not self.installed():
            fallback = self.web_fallback()
            return fallback.effective_pairs() if fallback is not None else []
        meta = self._meta()
        langs = [languages.normalize(x) or x for x in meta["languages"] if x]
        tlangs = [languages.normalize(x) or x for x in meta["translation_langs"] if x]
        pairs = set()
        for a in langs:
            for b in tlangs:
                if a != b:
                    pairs.add((a, b))
                    pairs.add((b, a))
        return sorted(pairs)

    def supports(self, mode: str, lang: str, lang2: Optional[str] = None) -> bool:
        if not self.installed():
            fallback = self.web_fallback()
            return fallback is not None and fallback.supports(mode, lang, lang2)
        return super().supports(mode, lang, lang2)

    # ---------------------------------------------------------------- work
    @staticmethod
    def _to_entry(e: dict, url: str = "") -> dict:
        extra = dict(e.get("extra") or {})
        if e.get("matched_form"):
            extra["matched form"] = e["matched_form"]
        if e.get("prefix_match"):
            extra["match"] = "prefix"
        # drop bulky machine fields from the display
        for key in ("synonyms", "antonyms"):
            extra.pop(key, None)
        return R.entry(e["word"], pos=e.get("pos", ""), senses=e.get("senses") or [],
                       pronunciation=e.get("pron", ""), lang=e.get("lang", ""), extra=extra, url=url)

    def lookup(self, word: str, lang: str) -> dict:
        if not self.installed() and self.web_fallback() is not None:
            return self.web_fallback().lookup(word, lang)
        with self._open() as st:
            langs = self.effective_languages()
            use_lang = lang if (lang in langs or not langs) else None
            rows = st.lookup(word, use_lang)
            if not rows and use_lang:
                rows = st.lookup(word, None)
            if not rows and _is_cjk_word(word):
                # Character dictionaries (Unihan) – look up each ideograph.
                seen = set()
                for ch in word.strip():
                    if ch in seen or not _is_cjk_word(ch):
                        continue
                    seen.add(ch)
                    rows.extend(st.lookup(ch, use_lang, prefix=False))
        return {"entries": [self._to_entry(r) for r in rows], "url": ""}

    def thesaurus(self, word: str, lang: str) -> dict:
        if not self.installed() and self.web_fallback() is not None:
            return self.web_fallback().thesaurus(word, lang)
        with self._open() as st:
            langs = self.effective_languages()
            res = st.thesaurus(word, lang if (lang in langs or not langs) else None)
        return res

    def translate(self, text: str, src: str, dst: str) -> dict:
        if not self.installed() and self.web_fallback() is not None:
            return self.web_fallback().translate(text, src, dst)
        with self._open() as st:
            pairs = st.translate(text.strip(), src, dst)
        return R.translation("word", pairs)
