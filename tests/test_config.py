"""sources.json / prefs.json / history."""

import json
import os
import unittest

from helpers import TempEnv

from ob import config
from ob.history import History


class SourcesConfigTest(TempEnv):
    def test_defaults_created_and_valid(self):
        cfg = config.SourcesConfig()
        self.assertTrue(cfg.path.exists())
        ids = [s["id"] for s in cfg.sources]
        for required in ("duden", "merriam-webster", "oed", "thesaurus-com", "leo", "google-translate", "deepl",
                         "wiktionary-de", "freedict-deu-eng", "cedict", "ecdict", "unihan"):
            self.assertIn(required, ids)
        self.assertEqual(len(ids), len(set(ids)), "duplicate source ids")
        self.assertFalse(cfg.get("oed")["enabled"])
        self.assertEqual(oct(cfg.path.stat().st_mode & 0o777), "0o600")
        for s in cfg.sources:
            self.assertIn(s["type"], config.SOURCE_TYPES)
            if s["type"] == "translator":
                self.assertIn(s["translation_mode"], config.TRANSLATION_MODES)
            if s["driver"] == "local":
                self.assertTrue(s["path"].endswith(".sqlite"))
                self.assertTrue(s["dataset"])

    def test_upsert_delete_and_builtin_memory(self):
        cfg = config.SourcesConfig()
        n = len(cfg.sources)
        row = cfg.upsert({"name": "My Dict", "type": "dictionary", "driver": "generic",
                          "url": "https://x/{word}", "languages": "de, EN", "api_key": "k"})
        self.assertEqual(row["id"], "my-dict")
        self.assertEqual(row["languages"], ["de", "en"])
        self.assertEqual(row["kind"], "remote")
        again = cfg.upsert({"name": "My Dict", "type": "thesaurus", "driver": "generic", "url": "u"})
        self.assertEqual(again["id"], "my-dict-2")
        self.assertEqual(len(config.SourcesConfig().sources), n + 2)
        # editing keeps builtin flag, deleting a builtin remembers it
        edited = cfg.upsert({"id": "duden", "name": "Duden!", "type": "dictionary", "driver": "duden", "url": "https://www.duden.de/rechtschreibung/{slug}"})
        self.assertTrue(edited["builtin"])
        self.assertTrue(cfg.delete("leo"))
        self.assertFalse(cfg.delete("leo"))
        cfg2 = config.SourcesConfig()
        self.assertIsNone(cfg2.get("leo"))
        self.assertIn("leo", cfg2.removed_builtins)
        self.assertEqual(cfg2.get("duden")["name"], "Duden!")
        cfg2.reset_defaults()
        self.assertIsNotNone(cfg2.get("leo"))
        self.assertEqual(cfg2.get("duden")["name"], "Duden")

    def test_new_builtins_are_merged_in(self):
        cfg = config.SourcesConfig()
        cfg.sources = [s for s in cfg.sources if s["id"] != "cedict"]
        cfg.save()
        merged = config.SourcesConfig()
        self.assertIsNotNone(merged.get("cedict"))

    def test_enable_move_public(self):
        cfg = config.SourcesConfig()
        self.assertTrue(cfg.set_enabled("duden", False))
        self.assertFalse(cfg.get("duden")["enabled"])
        first = cfg.sources[0]["id"]
        self.assertTrue(cfg.move(first, 1))
        self.assertEqual(cfg.sources[1]["id"], first)
        self.assertFalse(cfg.move(first, -5) and cfg.sources[0]["id"] != first)
        cfg.upsert({"id": "duden", "name": "Duden", "type": "dictionary", "driver": "duden", "api_key": "secret"})
        pub = [s for s in cfg.public() if s["id"] == "duden"][0]
        self.assertEqual(pub["api_key"], "")
        self.assertTrue(pub["has_key"])

    def test_corrupt_file_recovers(self):
        cfg = config.SourcesConfig()
        cfg.path.write_text("{not json", encoding="utf-8")
        cfg2 = config.SourcesConfig()
        self.assertGreater(len(cfg2.sources), 10)

    def test_normalize_pairs(self):
        row = config.normalize_source({"name": "x", "type": "translator", "pairs": "deu-eng, en-fr, bad", "translation_mode": "nonsense"})
        self.assertEqual(row["pairs"], [["de", "en"], ["en", "fr"]])
        self.assertEqual(row["translation_mode"], "text")


class PrefsTest(TempEnv):
    def test_roundtrip_and_validation(self):
        p = config.Prefs()
        self.assertEqual(p.data["mode"], "lookup")
        p.update({"mode": "translate", "lang": "deu", "lang2": "xx", "extra": 1})
        p2 = config.Prefs()
        self.assertEqual(p2.data["mode"], "translate")
        self.assertEqual(p2.data["lang"], "de")
        self.assertEqual(p2.data["lang2"], "en")   # invalid -> default
        self.assertEqual(p2.data["extra"], 1)
        p2.update({"mode": "bogus"})
        self.assertEqual(config.Prefs().data["mode"], "translate")


class HistoryTest(TempEnv):
    def test_add_dedupe_limit(self):
        h = History(limit=5)
        for w in ["a", "b", "A", "c", "d", "e", "f"]:
            h.add(w, mode="lookup", lang="en")
        self.assertEqual([e["query"] for e in h.entries], ["f", "e", "d", "c", "A"])
        h.add("  spaced   out ")
        self.assertEqual(h.entries[0]["query"], "spaced out")
        h.add("")
        self.assertEqual(len(h.entries), 5)
        again = History(limit=5)
        self.assertEqual(again.entries[0]["query"], "spaced out")

    def test_list_remove_clear(self):
        h = History()
        h.add("Haus"); h.add("house"); h.add("Maus")
        self.assertEqual([e["query"] for e in h.list("hau")], ["Haus"])
        self.assertEqual([e["query"] for e in h.list("aus")], ["Maus", "Haus"])
        self.assertTrue(h.remove("HAUS"))
        self.assertFalse(h.remove("nope"))
        h.clear()
        self.assertEqual(History().entries, [])

    def test_max_1000(self):
        h = History()
        for i in range(1100):
            h.entries.insert(0, {"query": f"w{i}"})
        h.add("last")
        self.assertEqual(len(h.entries), 1000)
        self.assertEqual(h.entries[0]["query"], "last")

    def test_corrupt(self):
        h = History()
        h.path.write_text("[[[", encoding="utf-8")
        self.assertEqual(History().entries, [])


if __name__ == "__main__":
    unittest.main()
