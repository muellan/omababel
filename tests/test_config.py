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
        self.assertFalse(cfg.get("deepl")["enabled"])            # free endpoints rate-limit
        self.assertFalse(cfg.get("google-translate")["enabled"])
        self.assertTrue(cfg.get("leo")["enabled"])
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

    def test_keys_go_to_the_keyring_and_never_into_the_file(self):
        cfg = config.SourcesConfig()
        cfg.upsert({"id": "deepl", "name": "DeepL", "type": "translator", "driver": "deepl",
                    "api_key": "s3cret"})
        raw = cfg.path.read_text(encoding="utf-8")
        self.assertNotIn("s3cret", raw)
        self.assertIn('"api_key": ""', raw)
        # readable again for the source that needs it
        self.assertEqual(cfg.key_for("deepl"), "s3cret")
        self.assertEqual([r for r in cfg.with_keys() if r["id"] == "deepl"][0]["api_key"], "s3cret")
        pub = [s for s in cfg.public() if s["id"] == "deepl"][0]
        self.assertEqual(pub["api_key"], "")
        self.assertTrue(pub["has_key"])
        self.assertEqual(pub["key_storage"], "keyring")
        # the file mode stays owner-only
        self.assertEqual(cfg.path.stat().st_mode & 0o777, 0o600)
        # deleting the source drops the secret with it
        cfg.delete("deepl")
        self.assertEqual(config.secrets.load("deepl"), "")

    def test_a_key_from_an_older_version_is_migrated_out_of_the_file(self):
        cfg = config.SourcesConfig()
        raw = json.loads(cfg.path.read_text(encoding="utf-8"))
        for row in raw["sources"]:
            if row["id"] == "merriam-webster":
                row["api_key"] = "legacy-key"
        cfg.path.write_text(json.dumps(raw), encoding="utf-8")
        again = config.SourcesConfig()
        self.assertNotIn("legacy-key", again.path.read_text(encoding="utf-8"))
        self.assertEqual(again.key_for("merriam-webster"), "legacy-key")
        self.assertEqual(again.insecure, [])

    def test_a_key_can_come_from_an_environment_variable_or_a_command(self):
        cfg = config.SourcesConfig()
        cfg.upsert({"id": "env-src", "name": "Env", "type": "dictionary", "driver": "generic",
                    "url": "https://x/{word}", "api_key_env": "OMABABEL_TEST_KEY"})
        os.environ["OMABABEL_TEST_KEY"] = "from-env"
        try:
            self.assertEqual(cfg.key_for("env-src"), "from-env")
            self.assertEqual([s for s in cfg.public() if s["id"] == "env-src"][0]["key_storage"], "environment")
        finally:
            del os.environ["OMABABEL_TEST_KEY"]
        cfg.upsert({"id": "cmd-src", "name": "Cmd", "type": "dictionary", "driver": "generic",
                    "url": "https://x/{word}", "api_key_cmd": "printf 'from-cmd\\nnoise'"})
        self.assertEqual(cfg.key_for("cmd-src"), "from-cmd")

    def test_without_a_keyring_a_key_is_refused_rather_than_written(self):
        os.environ["OMABABEL_NO_KEYRING"] = "1"
        os.environ["OMABABEL_SECRET_TOOL"] = "/nonexistent/secret-tool"
        try:
            cfg = config.SourcesConfig()
            with self.assertRaises(config.secrets.SecretError):
                cfg.upsert({"id": "nokey", "name": "No key", "type": "dictionary", "driver": "generic",
                            "url": "https://x/{word}", "api_key": "plain"})
            self.assertNotIn("plain", cfg.path.read_text(encoding="utf-8"))
        finally:
            del os.environ["OMABABEL_NO_KEYRING"]

    def test_ai_rows_come_first_and_an_old_config_follows_once(self):
        cfg = config.SourcesConfig()
        self.assertEqual([s["id"] for s in cfg.sources][:3],
                         ["ai-dictionary", "ai-thesaurus", "ai-translator"])
        self.assertTrue(all(not s["enabled"] for s in cfg.sources[:3]))
        # a config written before the AI rows moved up
        raw = json.loads(cfg.path.read_text(encoding="utf-8"))
        ai = [r for r in raw["sources"] if r["driver"] == "ai"]
        raw["sources"] = [r for r in raw["sources"] if r["driver"] != "ai"] + ai
        raw.pop("layout_version", None)
        cfg.path.write_text(json.dumps(raw), encoding="utf-8")
        again = config.SourcesConfig()
        self.assertEqual([s["id"] for s in again.sources][:3],
                         ["ai-dictionary", "ai-thesaurus", "ai-translator"])
        # ... and only once: an order the user made afterwards survives
        again.move("duden", -3)
        third = config.SourcesConfig()
        self.assertEqual(third.sources[0]["id"], "duden")

    def test_moving_and_reordering_a_block_of_sources(self):
        cfg = config.SourcesConfig()
        ids = [s["id"] for s in cfg.sources]
        # a selection moves as a block and keeps its order
        self.assertTrue(cfg.move([ids[3], ids[4]], -1))
        self.assertEqual([s["id"] for s in cfg.sources][:5],
                         [ids[0], ids[1], ids[3], ids[4], ids[2]])
        self.assertTrue(cfg.move([ids[3], ids[4]], 1))
        self.assertEqual([s["id"] for s in cfg.sources][:5], ids[:5])
        self.assertFalse(cfg.move([ids[0]], -1))          # already first
        self.assertFalse(cfg.move([], 1))
        # a drag puts the block in front of a row, in list order
        self.assertTrue(cfg.reorder([ids[5], ids[1]], ids[0]))
        self.assertEqual([s["id"] for s in cfg.sources][:3], [ids[1], ids[5], ids[0]])
        # ... or at the end when nothing follows
        self.assertTrue(cfg.reorder([ids[1]], ""))
        self.assertEqual(cfg.sources[-1]["id"], ids[1])
        self.assertFalse(cfg.reorder(["nope"], ""))
        # the order survives a reload
        self.assertEqual([s["id"] for s in config.SourcesConfig().sources],
                         [s["id"] for s in cfg.sources])

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

    def test_limit_from_prefs(self):
        h = History()
        for i in range(30):
            h.add(f"w{i}")
        self.assertEqual(History().limit, 1000)
        config.Prefs().update({"history_max": 10})
        trimmed = History()
        self.assertEqual(trimmed.limit, 10)
        self.assertEqual(len(trimmed.entries), 10)
        self.assertEqual(trimmed.entries[0]["query"], "w29")
        self.assertEqual(len(History().list()), 10)          # persisted trim
        config.Prefs().update({"history_max": "abc"})          # ignored
        self.assertEqual(config.Prefs().data["history_max"], 10)
        config.Prefs().update({"history_max": 0})              # clamped
        self.assertEqual(config.Prefs().data["history_max"], 1)


if __name__ == "__main__":
    unittest.main()
