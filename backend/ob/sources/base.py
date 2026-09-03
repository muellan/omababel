"""Base class and registry for source drivers."""

from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Sequence, Tuple, Type

from .. import languages
from .. import results as R

DRIVERS: Dict[str, Type["Source"]] = {}


class SourceError(Exception):
    """A source could not answer (network, parse, missing file...)."""


def register(cls: Type["Source"]) -> Type["Source"]:
    DRIVERS[cls.driver] = cls
    return cls


class Source:
    """One configured search source.

    Subclasses override :meth:`lookup`, :meth:`thesaurus`, :meth:`translate`
    for the types they support and declare capabilities via class
    attributes so the UI can render suitable controls.
    """

    driver = "base"
    label = "Base"
    kind = "remote"                     # "remote" | "local"
    types: Sequence[str] = ()           # subset of dictionary/thesaurus/translator
    description = ""
    default_url = ""
    supports_key = False
    key_hint = ""
    translation_modes: Sequence[str] = ()   # "word" | "text"
    languages: Sequence[str] = ()       # empty => any language
    pairs: Sequence[Tuple[str, str]] = ()   # translator pairs; empty => any
    order = 100

    def __init__(self, cfg: dict):
        self.cfg = dict(cfg)
        self.id = str(cfg.get("id") or self.driver)
        self.name = str(cfg.get("name") or self.label)
        self.type = str(cfg.get("type") or (self.types[0] if self.types else "dictionary"))
        self.enabled = bool(cfg.get("enabled", True))
        self.url = str(cfg.get("url") or self.default_url or "")
        self.path = str(cfg.get("path") or "")
        self.api_key = str(cfg.get("api_key") or "")
        self.translation_mode = str(cfg.get("translation_mode") or
                                    (self.translation_modes[0] if self.translation_modes else "word"))
        langs = cfg.get("languages")
        if isinstance(langs, str):
            langs = [x.strip() for x in langs.replace(";", ",").split(",") if x.strip()]
        self.cfg_languages: List[str] = [languages.normalize(x) or x for x in (langs or [])]

    # ------------------------------------------------------------ meta
    def describe(self) -> dict:
        return {"id": self.id, "name": self.name, "type": self.type,
                "driver": self.driver, "kind": self.kind,
                "translation_mode": self.translation_mode}

    def effective_languages(self) -> List[str]:
        """Languages this row serves (config wins over driver defaults)."""
        if self.cfg_languages:
            return self.cfg_languages
        return list(self.languages)

    def effective_pairs(self) -> List[Tuple[str, str]]:
        cfg_pairs = self.cfg.get("pairs")
        out: List[Tuple[str, str]] = []
        if cfg_pairs:
            for p in cfg_pairs:
                if isinstance(p, str) and "-" in p:
                    a, b = p.split("-", 1)
                elif isinstance(p, (list, tuple)) and len(p) == 2:
                    a, b = p
                else:
                    continue
                out.append((languages.normalize(a) or a, languages.normalize(b) or b))
            return out
        if self.cfg_languages and not self.pairs:
            # A translator restricted by a plain language list serves any
            # pair among those languages.
            ls = self.cfg_languages
            return [(a, b) for a in ls for b in ls if a != b]
        return list(self.pairs)

    def supports(self, mode: str, lang: str, lang2: Optional[str] = None) -> bool:
        if mode in ("lookup", "thesaurus"):
            want = "dictionary" if mode == "lookup" else "thesaurus"
            if self.type != want:
                return False
            langs = self.effective_languages()
            return (not langs) or (lang in langs)
        if mode == "translate":
            if self.type != "translator":
                return False
            pairs = self.effective_pairs()
            if not pairs:
                langs = self.effective_languages()
                return (not langs) or (lang in langs and (lang2 or "") in langs)
            return (lang, lang2 or "") in pairs
        return False

    # ------------------------------------------------------------ work
    def lookup(self, word: str, lang: str) -> dict:
        raise SourceError(f"{self.name} does not support dictionary lookup")

    def thesaurus(self, word: str, lang: str) -> dict:
        raise SourceError(f"{self.name} does not support thesaurus lookup")

    def translate(self, text: str, src: str, dst: str) -> dict:
        raise SourceError(f"{self.name} does not support translation")

    # ------------------------------------------------------------ helpers
    @staticmethod
    def thesaurus_from_entries(entries: Iterable[dict], url: str = "") -> dict:
        entries = list(entries)
        return R.thesaurus([], [], url=url, groups=R.groups_from_senses(entries))
