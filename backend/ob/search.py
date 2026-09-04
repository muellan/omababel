"""Search orchestration: pick the sources for a mode + language(s), query
them concurrently and assemble the response for the panel."""

from __future__ import annotations

import concurrent.futures as cf
import os
import time
from typing import Dict, List, Optional

from . import results as R
from . import sources as S
from .config import SourcesConfig

MODES = ("lookup", "thesaurus", "translate")
MAX_WORKERS = int(os.environ.get("OMABABEL_WORKERS", "8"))
SOURCE_TIMEOUT = float(os.environ.get("OMABABEL_SOURCE_TIMEOUT", "20"))


def build_sources(cfg: SourcesConfig) -> List[S.Source]:
    """Live source objects, with their secrets read from the keyring."""
    out: List[S.Source] = []
    for row in cfg.with_keys():
        try:
            out.append(S.build(row))
        except S.SourceError:
            continue
    return out


def coverage(cfg: Optional[SourcesConfig] = None) -> dict:
    """Which languages an enabled source can actually answer for, per mode.

    ``any`` is true when a source serves every language (an unrestricted
    generic row); ``langs`` lists the languages a mode is served in (for
    translate: the languages usable as the *source* side) and ``pairs`` maps
    each source language to the target languages reachable from it.  The
    panel dims everything else in the language selectors.
    """
    cfg = cfg or SourcesConfig()
    out: Dict[str, dict] = {
        "lookup": {"any": False, "langs": []},
        "thesaurus": {"any": False, "langs": []},
        "translate": {"any": False, "langs": [], "pairs": {}},
    }
    by_type = {"dictionary": "lookup", "thesaurus": "thesaurus", "translator": "translate"}
    for src in build_sources(cfg):
        mode = by_type.get(src.type)
        if not src.enabled or mode is None:
            continue
        if src.kind == "local" and hasattr(src, "installed") and not src.installed():
            continue
        if mode != "translate":
            langs = src.effective_languages()
            if langs:
                out[mode]["langs"].extend(langs)
            else:
                out[mode]["any"] = True
            continue
        pairs = src.effective_pairs()
        if not pairs:
            langs = src.effective_languages()
            if not langs:
                out["translate"]["any"] = True
                continue
            pairs = [(a, b) for a in langs for b in langs if a != b]
        for a, b in pairs:
            out["translate"]["langs"].append(a)
            out["translate"]["pairs"].setdefault(a, []).append(b)
    for mode in ("lookup", "thesaurus", "translate"):
        out[mode]["langs"] = sorted(set(out[mode]["langs"]))
    out["translate"]["pairs"] = {a: sorted(set(bs)) for a, bs in out["translate"]["pairs"].items()}
    return out


def _run_one(src: S.Source, mode: str, query: str, lang: str, lang2: str) -> dict:
    started = time.time()
    base = {"source": src.describe(), "ok": True, "error": ""}
    try:
        if mode == "lookup":
            res = src.lookup(query, lang)
            base.update({"entries": res.get("entries", []), "url": res.get("url", "")})
            base["count"] = len(base["entries"])
        elif mode == "thesaurus":
            res = src.thesaurus(query, lang)
            base.update({"synonyms": res.get("synonyms", []), "antonyms": res.get("antonyms", []),
                         "groups": res.get("groups", []), "url": res.get("url", "")})
            base["count"] = len(base["synonyms"]) + len(base["antonyms"])
        else:
            res = src.translate(query, lang, lang2)
            base.update(res)
            base["count"] = len(res.get("pairs", [])) + (1 if res.get("text") else 0)
    except S.SourceError as e:
        base.update({"ok": False, "error": str(e), "count": 0})
    except Exception as e:  # noqa: BLE001 - a bad page must not take the panel down
        base.update({"ok": False, "error": f"{type(e).__name__}: {e}", "count": 0})
    base["ms"] = int((time.time() - started) * 1000)
    return base


def run(mode: str, query: str, lang: str, lang2: str = "", cfg: Optional[SourcesConfig] = None,
        only: Optional[List[str]] = None, timeout: float = SOURCE_TIMEOUT,
        include_disabled: bool = False) -> dict:
    if mode not in MODES:
        raise ValueError(f"unknown mode '{mode}'")
    query = " ".join(str(query).split())
    cfg = cfg or SourcesConfig()
    chosen: List[S.Source] = []
    skipped: List[dict] = []
    for src in build_sources(cfg):
        if only and src.id not in only:
            continue
        if not src.enabled and not include_disabled:
            continue
        want_type = {"lookup": "dictionary", "thesaurus": "thesaurus", "translate": "translator"}[mode]
        if src.type != want_type:
            continue
        if src.supports(mode, lang, lang2 if mode == "translate" else None):
            chosen.append(src)
        elif src.kind == "local" and hasattr(src, "installed") and not src.installed():
            skipped.append({"id": src.id, "name": src.name, "reason": "not installed",
                            "dataset": getattr(src, "dataset", "")})
    out: Dict[str, object] = {
        "mode": mode, "query": query, "lang": lang, "lang2": lang2 if mode == "translate" else "",
        "results": [], "skipped": skipped,
    }
    if not query or not chosen:
        if mode == "thesaurus":
            out["consolidated"] = R.consolidate([])
        return out
    results: List[dict] = []
    if len(chosen) == 1:
        results.append(_run_one(chosen[0], mode, query, lang, lang2))
    else:
        pool = cf.ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(chosen)))
        futs = {pool.submit(_run_one, s, mode, query, lang, lang2): s for s in chosen}
        try:
            for fut in cf.as_completed(futs, timeout=timeout):
                results.append(fut.result())
        except cf.TimeoutError:
            for fut, s in futs.items():
                if not fut.done():
                    results.append({"source": s.describe(), "ok": False,
                                    "error": f"timed out after {int(timeout)}s", "count": 0})
                    fut.cancel()
        finally:
            # Never wait for a hung source; the caller exits the process anyway.
            pool.shutdown(wait=False, cancel_futures=True)
    # keep configured order
    order = {s.id: i for i, s in enumerate(chosen)}
    results.sort(key=lambda r: order.get(r["source"]["id"], 999))
    out["results"] = results
    if mode == "thesaurus":
        out["consolidated"] = R.consolidate(r for r in results if r.get("ok"))
    return out
