#!/usr/bin/env python3
"""Generate the JSON fixtures the QML harness feeds into the panel.

Runs the real backend (offline, against the bundled sample dictionaries) so
the QML sees exactly the shapes it will get in production.  Output goes to
tests/qml/fixtures/*.json and is committed, so the harness never needs the
backend at test time.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(HERE))

OUT = HERE / "qml" / "fixtures"


# Values that differ on every run and say nothing about the shapes the QML
# has to render: a measured duration, a build timestamp, when a history entry
# was recorded.
_VOLATILE = {"ms": 12, "built": 1700000000, "time": 1700000000}


def _stable(obj):
    if isinstance(obj, dict):
        return {k: (_VOLATILE[k] if k in _VOLATILE and isinstance(v, (int, float)) else _stable(v))
                for k, v in obj.items()}
    if isinstance(obj, list):
        return [_stable(v) for v in obj]
    return obj


def main() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="omababel-fixtures-"))
    os.environ.update({
        "OMABABEL_CONFIG_DIR": str(tmp / "config"), "OMABABEL_DATA_DIR": str(tmp / "data"),
        "OMABABEL_STATE_DIR": str(tmp / "state"), "OMABABEL_CACHE_DIR": str(tmp / "cache"),
        "OMABABEL_OFFLINE": "1",
        # The keyring stub, so the generated state does not depend on whether
        # the machine that regenerates the fixtures happens to run one.
        "OMABABEL_SECRET_TOOL": str(HERE / "fake_secret_tool.py"),
        "OMABABEL_FAKE_KEYRING": str(tmp / "keyring.json"),
    })
    for d in ("config", "data", "state", "cache"):
        (tmp / d).mkdir(parents=True)
    import omababel as backend  # noqa: E402
    from ob import data  # noqa: E402

    fixtures = HERE / "fixtures"
    shutil.copy(fixtures / "mini-en.json", tmp / "data" / "mini-en.json")
    shutil.copy(fixtures / "mini-de.json", tmp / "data" / "mini-de.json")
    data.install("cedict", source_file=fixtures / "cedict-sample.u8")
    data.install("freedict-deu-eng", source_file=fixtures / "deu-eng.tei")

    def op(name, params=None):
        reply = backend.handle({"op": name, "params": params or {}})
        assert reply["ok"], reply
        return reply["data"]

    for row in [
        {"id": "mini-en", "name": "Mini English", "type": "dictionary", "driver": "local", "path": "mini-en.json", "languages": ["en"]},
        {"id": "mini-en-thes", "name": "Mini English synonyms", "type": "thesaurus", "driver": "local", "path": "mini-en.json", "languages": ["en"]},
        {"id": "mini-de", "name": "Mini German", "type": "dictionary", "driver": "local", "path": "mini-de.json", "languages": ["de"]},
        {"id": "mini-de-thes", "name": "Mini German synonyms", "type": "thesaurus", "driver": "local", "path": "mini-de.json", "languages": ["de"]},
        {"id": "mini-trans", "name": "Mini translations", "type": "translator", "driver": "local", "path": "mini-en.json", "translation_mode": "word"},
    ]:
        op("sources.save", {"source": row})
    OUT.mkdir(parents=True, exist_ok=True)

    # (Duden is enabled by default and fails offline, which covers the error rendering path.)
    lookup = op("search", {"mode": "lookup", "query": "Haus", "lang": "de"})
    thesaurus = op("search", {"mode": "thesaurus", "query": "house", "lang": "en"})
    translate = op("search", {"mode": "translate", "query": "Haus", "lang": "de", "lang2": "en"})
    translate_text = op("search", {"mode": "translate", "query": "house", "lang": "en", "lang2": "de"})
    translate_text["results"].append({
        "source": {"id": "google-translate", "name": "Google Translate", "type": "translator", "driver": "google",
                   "kind": "remote", "translation_mode": "text"},
        "ok": True, "error": "", "mode": "text", "pairs": [{"src": "house", "dst": "Haus", "pos": "noun", "note": "house, home",
                                                              "src_html": '<a href="w:house">house</a>', "dst_html": '<a href="w:Haus">Haus</a>', "note_html": "house, home"}],
        "text": "Das Haus", "text_html": '<a href="w:Das">Das</a> <a href="w:Haus">Haus</a>', "detected": "en",
        "url": "https://translate.google.com/?sl=en&tl=de&text=house", "alternatives": ["Das Gebäude"],
        "alternatives_html": ['<a href="w:Das">Das</a> <a href="w:Geb%C3%A4ude">Gebäude</a>'], "count": 2, "ms": 240})
    state = op("state.get")
    datasets = op("data.list")
    status = op("sources.status")

    for name, obj in (("state", state), ("lookup", lookup), ("thesaurus", thesaurus), ("translate", translate),
                      ("translate_text", translate_text), ("datasets", datasets), ("status", status)):
        # The throw-away XDG tree and the measured durations change on every
        # run; keep both out of the fixtures so regenerating them shows only
        # real changes.
        text = (json.dumps(_stable(obj), ensure_ascii=False, indent=1)
                .replace(str(tmp), "/home/user/.omababel")
                .replace(str(ROOT), "/home/user/omababel"))
        # an index file is named after a hash of its source path, which is the
        # throw-away directory of this run
        text = re.sub(r"-[0-9a-f]{16}\.sqlite", "-0000000000000000.sqlite", text)
        (OUT / f"{name}.json").write_text(text + "\n", encoding="utf-8")
        print("wrote", OUT / f"{name}.json")
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
