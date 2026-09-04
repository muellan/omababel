"""Source drivers.

A *source* is one row in the preferences panel (``sources.json``).  Its
``driver`` field names the class that knows how to query it.  Remote drivers
scrape or call a web service; the ``local`` driver reads dictionary files
from the app's data directory.

:func:`registry` returns the driver catalogue the UI uses to populate the
driver dropdown and to show the right fields for each row.
"""

from __future__ import annotations

from typing import Dict, List, Type

from .base import Source, SourceError, DRIVERS, register  # noqa: F401


def _load_all() -> None:
    # Import for side effect: each module registers its driver.
    from . import duden, mw, oed, thesauruscom, leo, google, deepl, ai, generic, local  # noqa: F401


def get_driver(name: str) -> Type[Source]:
    _load_all()
    try:
        return DRIVERS[name]
    except KeyError:
        raise SourceError(f"unknown source driver '{name}'")


def registry() -> List[dict]:
    _load_all()
    out = []
    for name, cls in sorted(DRIVERS.items(), key=lambda kv: kv[1].order):
        out.append({
            "driver": name,
            "label": cls.label,
            "kind": cls.kind,
            "types": list(cls.types),
            "description": cls.description,
            "default_url": cls.default_url,
            "supports_key": cls.supports_key,
            "key_hint": cls.key_hint,
            "translation_modes": list(cls.translation_modes),
            "languages": list(cls.languages) if cls.languages else [],
            "services": cls.services() if hasattr(cls, "services") else [],
        })
    return out


def build(cfg: dict) -> Source:
    cls = get_driver(cfg.get("driver", "generic"))
    return cls(cfg)


def all_drivers() -> Dict[str, Type[Source]]:
    _load_all()
    return dict(DRIVERS)
