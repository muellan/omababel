"""Search history – the last 1000 queries, most recent first."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import List, Optional

from .config import _atomic_write
from .paths import state_dir

MAX_ENTRIES = 1000


class History:
    FILE = "history.json"

    def __init__(self, path: Optional[Path] = None, limit: int = MAX_ENTRIES):
        self.path = path or (state_dir() / self.FILE)
        self.limit = limit
        self.entries: List[dict] = []
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            self.entries = []
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            data = []
        rows = data.get("entries") if isinstance(data, dict) else data
        self.entries = [r for r in (rows or []) if isinstance(r, dict) and r.get("query")]
        self.entries = self.entries[: self.limit]

    def save(self) -> None:
        _atomic_write(self.path, json.dumps({"version": 1, "entries": self.entries},
                                            ensure_ascii=False) + "\n")

    def add(self, query: str, mode: str = "", lang: str = "", lang2: str = "") -> None:
        query = " ".join(str(query).split())
        if not query:
            return
        key = query.casefold()
        self.entries = [e for e in self.entries if str(e.get("query", "")).casefold() != key]
        self.entries.insert(0, {"query": query, "mode": mode, "lang": lang, "lang2": lang2,
                                "time": int(time.time())})
        del self.entries[self.limit:]
        self.save()

    def remove(self, query: str) -> bool:
        key = " ".join(str(query).split()).casefold()
        before = len(self.entries)
        self.entries = [e for e in self.entries if str(e.get("query", "")).casefold() != key]
        if len(self.entries) != before:
            self.save()
            return True
        return False

    def clear(self) -> None:
        self.entries = []
        self.save()

    def list(self, prefix: str = "", limit: int = MAX_ENTRIES) -> List[dict]:
        p = prefix.casefold().strip()
        out = [e for e in self.entries if not p or p in str(e.get("query", "")).casefold()]
        return out[:limit]
