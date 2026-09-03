"""SQLite index: import, lookup (exact / forms / prefix), translations, cache."""

import unittest

from helpers import TempEnv, fixture

from ob import formats, store


class StoreTest(TempEnv):
    def build(self, name="mini-en.json", **opts):
        st = store.Store(self.data_dir / "t.sqlite")
        st.import_entries(formats.iter_entries(fixture(name), **opts), meta={"title": "t"})
        return st

    def test_import_and_meta(self):
        st = self.build()
        info = st.info()
        self.assertEqual(info["entries"], 4)
        self.assertEqual(st.get_meta("languages"), ["en"])
        self.assertEqual(sorted(st.get_meta("translation_langs")), ["de", "fr"])
        self.assertEqual(st.get_meta("title"), "t")
        self.assertIsNone(st.get_meta("missing"))

    def test_lookup_exact_forms_prefix(self):
        st = self.build()
        rows = st.lookup("HOUSE", "en")
        self.assertEqual([r["pos"] for r in rows], ["noun", "verb"])
        rows = st.lookup("houses")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["matched_form"], "houses")
        rows = st.lookup("hou")
        self.assertTrue(all(r.get("prefix_match") for r in rows))
        self.assertEqual(st.lookup("hou", prefix=False), [])
        self.assertEqual(st.lookup("zzz"), [])
        self.assertEqual(st.lookup(""), [])
        self.assertEqual(st.lookup("house", "de"), [])

    def test_thesaurus(self):
        st = self.build()
        res = st.thesaurus("house", "en")
        self.assertEqual(res["synonyms"], ["home", "dwelling", "residence", "chamber", "accommodate", "lodge"])
        self.assertEqual(res["antonyms"], ["evict"])
        self.assertEqual(st.thesaurus("nothing")["synonyms"], [])

    def test_translate_forward_and_reverse(self):
        st = self.build()
        pairs = st.translate("house", "en", "de")
        self.assertEqual([(p["src"], p["dst"]) for p in pairs], [("house", "Haus"), ("house", "Gebäude"), ("house", "unterbringen")])
        self.assertEqual(pairs[0]["pos"], "noun")
        rev = st.translate("Haus", "de", "en")
        self.assertEqual([(p["src"], p["dst"]) for p in rev], [("Haus", "house")])
        self.assertEqual(st.translate("Haus", "de", "fr"), [])

    def test_translate_to_english_uses_glosses(self):
        st = self.build("cedict-sample.u8")
        pairs = st.translate("好", "zh", "en")
        self.assertIn(("好", "good"), [(p["src"], p["dst"]) for p in pairs])
        # traditional form hits through the forms table
        self.assertEqual(st.lookup("中國")[0]["word"], "中国")

    def test_replace_and_append(self):
        st = self.build()
        st.import_entries([{"word": "extra", "lang": "en", "senses": [{"gloss": "x"}]}], replace=False)
        self.assertEqual(st.info()["entries"], 5)
        st.import_entries([{"word": "only", "lang": "en", "senses": []}], replace=True)
        self.assertEqual(st.info()["entries"], 1)

    def test_open_store_builds_cache_once(self):
        src = fixture("mini.tsv")
        built = []

        def builder(target, progress):
            built.append(target)
            with store.Store(target) as st:
                st.import_entries(formats.iter_entries(src, lang="de"))

        with store.open_store(src, builder=builder) as st:
            self.assertEqual(st.lookup("Katze")[0]["senses"][1]["gloss"], "Raubtier")
        with store.open_store(src, builder=builder) as st2:
            self.assertEqual(st2.info()["entries"], 2)
        self.assertEqual(len(built), 1)
        self.assertTrue(store.is_store(store.cache_path_for(src)))
        with self.assertRaises(FileNotFoundError):
            store.open_store(fixture("mini-de.json"), builder=None)

    def test_is_store(self):
        self.assertFalse(store.is_store(fixture("mini.tsv")))
        st = self.build()
        st.close()
        self.assertTrue(store.is_store(self.data_dir / "t.sqlite"))
        ro = store.Store(self.data_dir / "t.sqlite", readonly=True)
        with self.assertRaises(RuntimeError):
            ro.import_entries([])


if __name__ == "__main__":
    unittest.main()
