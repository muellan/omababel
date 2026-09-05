"""Local driver, search orchestration and the data catalogue."""

import json
import shutil
import time
import unittest
from pathlib import Path

from helpers import TempEnv, FakeResponse, fake_fetch, fixture

from ob import data, search
from ob import results as R
from ob import sources as S
from ob.config import SourcesConfig
from ob.sources.base import Source, SourceError, register


@register
class FakeSource(Source):
    """Test driver: canned answers, optional failure / delay."""
    driver = "fake"
    label = "Fake"
    types = ("dictionary", "thesaurus", "translator")
    translation_modes = ("word", "text")

    def __init__(self, cfg):
        super().__init__(cfg)
        # test directives travel in the free-text ``notes`` field as JSON
        try:
            self.opts = json.loads(cfg.get("notes") or "{}")
        except ValueError:
            self.opts = {}

    def lookup(self, word, lang):
        self._maybe_fail()
        return {"entries": [{"headword": word, "pos": "", "pronunciation": "", "lang": lang,
                             "senses": [{"gloss": f"{self.name} says {word}", "examples": [], "synonyms": ["s1"],
                                         "antonyms": [], "tags": [], "label": ""}], "extra": {}, "url": ""}],
                "url": "u"}

    def thesaurus(self, word, lang):
        self._maybe_fail()
        return R.thesaurus(self.opts.get("syn", ["b", "a"]), self.opts.get("ant", ["z"]))

    def translate(self, text, src, dst):
        self._maybe_fail()
        return {"mode": self.translation_mode, "pairs": [{"src": text, "dst": text[::-1], "pos": "", "note": ""}],
                "text": text.upper(), "detected": src, "url": "", "alternatives": []}

    def _maybe_fail(self):
        if self.opts.get("delay"):
            time.sleep(self.opts["delay"])
        if self.opts.get("fail"):
            raise SourceError("nope")
        if self.opts.get("crash"):
            raise ValueError("unexpected")


def opts(**kw):
    return json.dumps(kw)


def cfg_with(rows):
    from ob.config import normalize_source
    cfg = SourcesConfig()
    cfg.sources = [normalize_source(r) for r in rows]
    cfg.save()
    return cfg


class LocalSourceTest(TempEnv):
    def setUp(self):
        super().setUp()
        shutil.copy(fixture("mini-en.json"), self.data_dir / "mini-en.json")
        shutil.copy(fixture("mini-de.json"), self.data_dir / "mini-de.json")

    def test_raw_file_indexed_lazily(self):
        src = S.build({"id": "en", "driver": "local", "type": "dictionary", "path": "mini-en.json"})
        self.assertTrue(src.installed())
        self.assertEqual(src.effective_languages(), ["en"])
        self.assertTrue(src.supports("lookup", "en"))
        self.assertFalse(src.supports("lookup", "de"))
        res = src.lookup("houses", "en")
        self.assertEqual(res["entries"][0]["headword"], "house")
        self.assertEqual(res["entries"][0]["extra"]["matched form"], "houses")
        st = src.status()
        self.assertTrue(st["installed"])
        self.assertEqual(st["entries"], 4)
        self.assertEqual(st["format"], "json")

    def test_translator_pairs_derived_from_data(self):
        src = S.build({"id": "en", "driver": "local", "type": "translator", "path": "mini-en.json"})
        pairs = src.effective_pairs()
        self.assertIn(("en", "de"), pairs)
        self.assertIn(("de", "en"), pairs)
        self.assertTrue(src.supports("translate", "en", "fr"))
        self.assertFalse(src.supports("translate", "de", "fr"))
        res = src.translate("Haus", "de", "en")
        self.assertEqual(res["mode"], "word")
        self.assertEqual(res["pairs"][0]["dst"], "house")

    def test_thesaurus(self):
        src = S.build({"id": "en", "driver": "local", "type": "thesaurus", "path": "mini-en.json", "languages": ["en"]})
        res = src.thesaurus("big", "en")
        self.assertEqual(res["synonyms"], ["large", "huge"])
        self.assertEqual(res["antonyms"], ["small", "little"])

    def test_missing_file(self):
        src = S.build({"id": "x", "driver": "local", "type": "dictionary", "path": "nope.json", "dataset": "wiktionary-de"})
        self.assertFalse(src.installed())
        self.assertFalse(src.supports("lookup", "de"))
        self.assertIn("omababel data install wiktionary-de", src.status()["error"])
        with self.assertRaises(SourceError):
            src.lookup("x", "de")
        empty = S.build({"id": "y", "driver": "local", "type": "dictionary"})
        self.assertFalse(empty.installed())

    def test_cjk_per_character_fallback(self):
        (self.data_dir / "uni.txt").write_text(fixture("unihan-sample.txt").read_text(encoding="utf-8"), encoding="utf-8")
        src = S.build({"id": "u", "driver": "local", "type": "dictionary", "path": "uni.txt", "languages": ["zh"]})
        res = src.lookup("中国", "zh")
        self.assertEqual([e["headword"] for e in res["entries"]], ["中", "国"])

    def test_absolute_path(self):
        src = S.build({"id": "abs", "driver": "local", "type": "dictionary", "path": str(fixture("mini.tsv")), "languages": "de"})
        self.assertEqual(src.lookup("Hund", "de")["entries"][0]["senses"][0]["gloss"], "Haustier, das bellt")


class SearchRunTest(TempEnv):
    def rows(self):
        return [
            {"id": "d1", "name": "Dict One", "type": "dictionary", "driver": "fake", "languages": ["en"]},
            {"id": "d2", "name": "Dict Two", "type": "dictionary", "driver": "fake", "languages": ["en", "de"], "notes": opts(fail=True)},
            {"id": "d3", "name": "Off", "type": "dictionary", "driver": "fake", "enabled": False},
            {"id": "t1", "name": "Thes One", "type": "thesaurus", "driver": "fake", "notes": opts(syn=["b", "a"], ant=["z", "a"])},
            {"id": "t2", "name": "Thes Two", "type": "thesaurus", "driver": "fake", "notes": opts(syn=["C"], ant=["y"], crash=True)},
            {"id": "t3", "name": "Thes Three", "type": "thesaurus", "driver": "fake", "notes": opts(syn=["c", "d"], ant=[])},
            {"id": "tr", "name": "Trans", "type": "translator", "driver": "fake", "pairs": "en-de", "translation_mode": "text"},
            {"id": "loc", "name": "Local missing", "type": "dictionary", "driver": "local", "path": "missing.sqlite", "dataset": "cedict"},
        ]

    def test_lookup_selection_order_and_errors(self):
        cfg = cfg_with(self.rows())
        res = search.run("lookup", "  house  ", "en", cfg=cfg)
        self.assertEqual(res["query"], "house")
        self.assertEqual([r["source"]["id"] for r in res["results"]], ["d1", "d2"])
        self.assertTrue(res["results"][0]["ok"])
        self.assertEqual(res["results"][0]["count"], 1)
        self.assertFalse(res["results"][1]["ok"])
        self.assertEqual(res["results"][1]["error"], "nope")
        self.assertEqual([s["id"] for s in res["skipped"]], ["loc"])
        self.assertEqual(res["skipped"][0]["dataset"], "cedict")
        de = search.run("lookup", "Haus", "de", cfg=cfg)
        self.assertEqual([r["source"]["id"] for r in de["results"]], ["d2"])

    def test_coverage_reports_the_languages_a_mode_is_served_in(self):
        cov = search.coverage(cfg_with(self.rows()))
        # d1 serves en, d2 en+de, the disabled d3 counts for nothing
        self.assertEqual(cov["lookup"], {"any": False, "langs": ["de", "en"]})
        # t1..t3 declare no languages at all -> every language is served
        self.assertTrue(cov["thesaurus"]["any"])
        self.assertEqual(cov["translate"]["langs"], ["en"])
        self.assertEqual(cov["translate"]["pairs"], {"en": ["de"]})
        self.assertFalse(cov["translate"]["any"])
        # an uninstalled local dictionary does not make its language available
        self.assertNotIn("zh", cov["lookup"]["langs"])

    def test_results_are_streamed_as_each_source_finishes(self):
        cfg = cfg_with(self.rows())
        started = []
        streamed = []
        res = search.run("thesaurus", "x", "en", cfg=cfg,
                         on_start=lambda sources, skipped: started.append((sources, skipped)),
                         on_result=lambda r, i, n: streamed.append((r["source"]["id"], i, n)))
        # the set of sources is known before any of them runs
        self.assertEqual(len(started), 1)
        self.assertEqual([s["id"] for s in started[0][0]], ["t1", "t2", "t3"])
        # every source reports exactly once, with the slot it will occupy in
        # the finished answer (arrival order is whatever finishes first)
        self.assertEqual(len(streamed), 3)
        self.assertEqual(sorted(streamed), [("t1", 0, 3), ("t2", 1, 3), ("t3", 2, 3)])
        final = [r["source"]["id"] for r in res["results"]]
        self.assertEqual(final, ["t1", "t2", "t3"])
        for source_id, index, _ in streamed:
            self.assertEqual(final[index], source_id)

    def test_a_single_source_and_a_timeout_are_streamed_too(self):
        rows = [{"id": "only", "name": "Only", "type": "dictionary", "driver": "fake"}]
        seen = []
        search.run("lookup", "x", "en", cfg=cfg_with(rows),
                   on_result=lambda r, i, n: seen.append((r["source"]["id"], i, n)))
        self.assertEqual(seen, [("only", 0, 1)])
        slow = [{"id": "slow", "name": "Slow", "type": "dictionary", "driver": "fake", "notes": opts(delay=5)},
                {"id": "quick", "name": "Quick", "type": "dictionary", "driver": "fake"}]
        seen = []
        search.run("lookup", "x", "en", cfg=cfg_with(slow), timeout=0.2,
                   on_result=lambda r, i, n: seen.append((r["source"]["id"], r["ok"])))
        self.assertEqual(sorted(seen), [("quick", True), ("slow", False)])

    def test_thesaurus_consolidation(self):
        res = search.run("thesaurus", "x", "en", cfg=cfg_with(self.rows()))
        self.assertEqual(res["consolidated"]["synonyms"], ["a", "b", "c", "d"])
        self.assertEqual(res["consolidated"]["antonyms"], ["z"])   # crashed t2 excluded, "a" is a synonym
        self.assertEqual([g["source"] for g in res["consolidated"]["groups"]], ["Thes One", "Thes Three"])
        self.assertEqual(res["consolidated"]["groups"][0]["synonyms"], ["a", "b"])
        crashed = [r for r in res["results"] if r["source"]["id"] == "t2"][0]
        self.assertIn("ValueError", crashed["error"])

    def test_translate(self):
        cfg = cfg_with(self.rows())
        res = search.run("translate", "house", "en", "de", cfg=cfg)
        self.assertEqual(len(res["results"]), 1)
        self.assertEqual(res["results"][0]["text"], "HOUSE")
        self.assertEqual(res["results"][0]["mode"], "text")
        self.assertEqual(search.run("translate", "house", "de", "en", cfg=cfg)["results"], [])

    def test_only_and_empty(self):
        cfg = cfg_with(self.rows())
        res = search.run("lookup", "x", "en", cfg=cfg, only=["d2"])
        self.assertEqual([r["source"]["id"] for r in res["results"]], ["d2"])
        self.assertEqual(search.run("lookup", "   ", "en", cfg=cfg)["results"], [])
        self.assertEqual(search.run("thesaurus", "", "en", cfg=cfg)["consolidated"]["synonyms"], [])
        with self.assertRaises(ValueError):
            search.run("bogus", "x", "en", cfg=cfg)

    def test_timeout(self):
        rows = [{"id": "slow", "type": "dictionary", "driver": "fake", "notes": opts(delay=0.6)},
                {"id": "fast", "type": "dictionary", "driver": "fake"}]
        res = search.run("lookup", "x", "en", cfg=cfg_with(rows), timeout=0.2)
        by_id = {r["source"]["id"]: r for r in res["results"]}
        self.assertTrue(by_id["fast"]["ok"])
        self.assertFalse(by_id["slow"]["ok"])
        self.assertIn("timed out", by_id["slow"]["error"])


class DataCatalogTest(TempEnv):
    def test_catalog_shape(self):
        items = data.catalog()
        ids = [d["id"] for d in items]
        self.assertEqual(len(ids), len(set(ids)))
        for required in ("wiktionary-de", "wiktionary-de-native", "wiktionary-en", "freedict-deu-eng", "cedict", "ecdict", "unihan"):
            self.assertIn(required, ids)
        self.assertNotIn("wiktionary-en-native", ids)
        for d in items:
            self.assertTrue(d["title"] and d["license"] and d["kind"])
        # every local default source points at a catalogue dataset
        for row in SourcesConfig().sources:
            if row["driver"] == "local":
                self.assertIn(row["dataset"], ids, row["id"])
        with self.assertRaises(ValueError):
            data.install("nope")

    def test_install_from_file_and_remove(self):
        events = []
        res = data.install("cedict", progress=events.append, source_file=fixture("cedict-sample.u8"))
        self.assertTrue(res["installed"])
        self.assertEqual(res["entries"], 4)
        self.assertEqual(res["license"], "CC BY-SA 4.0")
        self.assertEqual(events[-1]["phase"], "done")
        self.assertTrue(data.index_path("cedict").exists())
        # the default source rows now work against it
        out = search.run("lookup", "中国", "zh")
        by_id = {r["source"]["id"]: r for r in out["results"]}
        self.assertEqual(by_id["cedict"]["entries"][0]["pronunciation"], "Zhōng guó")
        self.assertTrue(data.remove("cedict"))
        self.assertFalse(data.remove("cedict"))
        self.assertFalse(data.status("cedict")["installed"])

    def test_install_freedict_from_tei(self):
        res = data.install("freedict-deu-eng", source_file=fixture("deu-eng.tei"))
        self.assertEqual(res["entries"], 2)
        tr = search.run("translate", "Haus", "de", "en", only=["freedict-deu-eng"])
        self.assertEqual(tr["results"][0]["pairs"][0]["dst"], "house")
        tr2 = search.run("translate", "house", "en", "de", only=["freedict-deu-eng"])
        self.assertEqual(tr2["results"][0]["pairs"][0]["dst"], "Haus")

    def test_empty_import_rejected(self):
        empty = self.tmp / "empty.jsonl"
        empty.write_text("", encoding="utf-8")
        with self.assertRaises(ValueError):
            data.install("wiktionary-de", source_file=empty)
        self.assertFalse(data.index_path("wiktionary-de").exists())

    def test_download_helpers(self):
        src = "https://download.freedict.org/dictionaries/deu-eng/1.0/s.src.tar.xz"
        dictd = "https://download.freedict.org/dictionaries/deu-eng/1.0/d.dictd.tar.xz"
        with fake_fetch(lambda url, **kw: FakeResponse(json.dumps([{"name": "deu-eng", "releases": [
                {"platform": "dictd", "URL": dictd}, {"platform": "src", "URL": src}]}]))):
            self.assertEqual(data.freedict_release_url("deu-eng"), src)

    def test_a_release_url_off_the_freedict_hosts_is_ignored(self):
        """The release address comes out of a JSON document on freedict.org –
        a compromised one must not be able to send the download elsewhere."""
        listing = '<a href="1.0/">1.0/</a>'

        def serve(url, **kw):
            if "freedict-database" in url:
                return FakeResponse(json.dumps([{"name": "deu-eng", "releases": [
                    {"platform": "src", "URL": "https://evil.example/steal.tar.xz"},
                    {"platform": "dictd", "URL": "file:///etc/passwd"}]}]))
            return FakeResponse(listing)

        with fake_fetch(serve):
            # neither candidate is usable, so it falls back to the listing
            self.assertEqual(data.freedict_release_url("deu-eng"),
                             "https://download.freedict.org/dictionaries/deu-eng/1.0/"
                             "freedict-deu-eng-1.0.src.tar.xz")

    def test_a_scraped_version_has_to_look_like_a_version(self):
        listing = '<a href="1.0/">1.0/</a><a href="9%2F..%2F..%2Fetc/">bogus</a>'

        def serve(url, **kw):
            if "freedict-database" in url:
                raise data.http.FetchError("down")
            return FakeResponse(listing)

        with fake_fetch(serve):
            self.assertEqual(data.freedict_release_url("deu-eng"),
                             "https://download.freedict.org/dictionaries/deu-eng/1.0/"
                             "freedict-deu-eng-1.0.src.tar.xz")

        def listing(url, **kw):
            if "freedict-database" in url:
                raise data.http.FetchError("down")
            return FakeResponse('<a href="0.8/">0.8/</a><a href="1.10/">1.10/</a><a href="1.9/">1.9/</a>')

        with fake_fetch(listing):
            self.assertEqual(data.freedict_release_url("deu-eng"),
                             "https://download.freedict.org/dictionaries/deu-eng/1.10/freedict-deu-eng-1.10.src.tar.xz")
        with self.assertRaises(data.http.FetchError):
            data.download("https://kaikki.org/x", self.tmp / "x")    # offline
        # everything outside [A-Za-z0-9._-] becomes an underscore, so a name
        # can carry no separator and no surprise
        self.assertEqual(data._filename("https://a/b/c%20d.txt?x=1"), "c_d.txt")


if __name__ == "__main__":
    unittest.main()
