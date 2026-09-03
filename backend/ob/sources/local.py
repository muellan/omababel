"""Local file sources.

``path`` is relative to the app's data directory (``~/.local/share/omababel``)
unless absolute.  Indexes built by ``omababel data install`` are opened
directly; raw dictionary files (kaikki JSONL, TEI, CC-CEDICT, ECDICT,
Unihan, dictd, TSV, JSON) are indexed into the cache on first use.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Tuple

from .. import formats, languages, store
from .. import results as R
from ..paths import resolve_local
from .base import Source, SourceError, register


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
            return []
        return [languages.normalize(x) or x for x in self._meta()["languages"] if x]

    def effective_pairs(self) -> List[Tuple[str, str]]:
        if self.cfg.get("pairs"):
            return super().effective_pairs()
        if not self.installed():
            return []
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
            return False
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
        with self._open() as st:
            langs = self.effective_languages()
            res = st.thesaurus(word, lang if (lang in langs or not langs) else None)
        return res

    def translate(self, text: str, src: str, dst: str) -> dict:
        with self._open() as st:
            pairs = st.translate(text.strip(), src, dst)
        return R.translation("word", pairs)
