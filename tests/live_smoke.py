#!/usr/bin/env python3
"""Query every remote source for real and show what comes back.

    OMABABEL_LIVE=1 python3 tests/live_smoke.py [source-id ...]

Not part of the automatic suite (needs internet, hits third-party sites).
Run it when a site changed its layout or after touching a scraper.  Exit
code 1 when a source returned an error or nothing.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from ob import sources as S  # noqa: E402
from ob.config import default_sources  # noqa: E402

SAMPLES = {
    "duden": ("lookup", "Haus", "de", ""),
    "merriam-webster": ("lookup", "house", "en", ""),
    "merriam-webster-thesaurus": ("thesaurus", "house", "en", ""),
    "oed": ("lookup", "house", "en", ""),
    "thesaurus-com": ("thesaurus", "house", "en", ""),
    "leo": ("translate", "house", "en", "de"),
    "google-translate": ("translate", "Wo ist der Bahnhof?", "de", "en"),
    "deepl": ("translate", "Wo ist der Bahnhof?", "de", "en"),
}


def main(argv) -> int:
    if not os.environ.get("OMABABEL_LIVE"):
        print("set OMABABEL_LIVE=1 to run network checks", file=sys.stderr)
        return 2
    os.environ.pop("OMABABEL_OFFLINE", None)
    wanted = set(argv[1:])
    failures = 0
    for row in default_sources():
        if row["driver"] == "local" or row["id"] not in SAMPLES:
            continue
        if wanted and row["id"] not in wanted:
            continue
        mode, query, lang, lang2 = SAMPLES[row["id"]]
        src = S.build(row)
        started = time.time()
        try:
            if mode == "lookup":
                res = src.lookup(query, lang)
                items = res["entries"]
                summary = "; ".join(f"{e['headword']} ({e['pos']}): {len(e['senses'])} senses" for e in items[:3])
            elif mode == "thesaurus":
                res = src.thesaurus(query, lang)
                items = res["synonyms"] + res["antonyms"]
                summary = f"{len(res['synonyms'])} syn ({', '.join(res['synonyms'][:6])}…) / {len(res['antonyms'])} ant"
            else:
                res = src.translate(query, lang, lang2)
                items = res["pairs"] or ([res["text"]] if res["text"] else [])
                summary = res["text"] or "; ".join(f"{p['src']} → {p['dst']}" for p in res["pairs"][:4])
            ms = int((time.time() - started) * 1000)
            if items:
                print(f"OK   {row['id']:<28} {ms:>5} ms  {summary[:110]}")
            else:
                failures += 1
                print(f"EMPTY {row['id']:<27} {ms:>5} ms  (no results – layout changed?)")
        except Exception as e:  # noqa: BLE001
            failures += 1
            print(f"FAIL {row['id']:<28} {type(e).__name__}: {e}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
