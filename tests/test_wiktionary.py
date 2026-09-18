"""The Wiktionary web driver, and the local rows that fall back to it."""

import json
import unittest

from helpers import FakeResponse, TempEnv, fake_fetch, read_fixture

from ob import http
from ob import sources as S
from ob.sources import wiktionary as W


def api_reply(wikitext: str) -> FakeResponse:
    return FakeResponse(json.dumps({"parse": {"title": "Haus", "wikitext": wikitext}}),
                        headers={"content-type": "application/json"})


class WikitextTest(unittest.TestCase):
    def setUp(self):
        self.en = read_fixture("wiktionary-en-haus.txt")
        self.de = read_fixture("wiktionary-de-haus.txt")

    def test_plain_unwraps_links_and_templates(self):
        self.assertEqual(W.plain("a [[house|home]] and a [[roof]]"), "a home and a roof")
        self.assertEqual(W.plain("{{l|de|Gebäude}}"), "Gebäude")
        self.assertEqual(W.plain("'''bold''' and ''italic''"), "bold and italic")
        self.assertEqual(W.plain("text<ref>a citation</ref>"), "text")
        self.assertEqual(W.plain("{{unknown-template|x}}"), "")

    def test_language_section_is_picked_by_name(self):
        titles = [s.title for s in W.language_section(self.en, "de")]
        self.assertEqual(titles[0], "German")
        self.assertIn("Noun", titles)
        self.assertNotIn("Translations", [t for t in titles if t == "Translations"])

    def test_language_section_of_a_native_edition(self):
        """The German edition marks its sections `{{Sprache|Deutsch}}`."""
        blocks = W.language_section(self.de, "de")
        self.assertTrue(blocks)
        self.assertIn("Sprache|Deutsch", blocks[0].title)

    def test_entries_from_the_english_edition(self):
        entries = W.parse_entries(self.en, "Haus", "de")
        self.assertEqual(len(entries), 1)
        entry = entries[0]
        self.assertEqual(entry["pos"], "Noun")
        glosses = [s["gloss"] for s in entry["senses"]]
        self.assertEqual(len(glosses), 3)
        self.assertIn("house", glosses[0])
        # the label is a tag, not part of the gloss text
        self.assertEqual(entry["senses"][1]["tags"], ["figurative"])
        self.assertNotIn("figurative", entry["senses"][1]["gloss"])
        self.assertIn("We are building a house", entry["senses"][0]["examples"][0])
        self.assertIn("Gebäude", entry["senses"][0]["synonyms"])
        self.assertIn("Hütte", entry["senses"][0]["antonyms"])

    def test_the_wrong_language_section_is_not_used(self):
        """The Dutch and English sections of the page stay out of a German lookup."""
        entries = W.parse_entries(self.en, "Haus", "de")
        glosses = " ".join(s["gloss"] for e in entries for s in e["senses"])
        self.assertNotIn("German-speaking contexts", glosses)
        self.assertNotIn("dialectal", glosses)

    def test_entries_from_a_native_edition(self):
        entries = W.parse_entries(self.de, "Haus", "de")
        self.assertEqual(entries[0]["pos"], "Substantiv")
        glosses = [s["gloss"] for s in entries[0]["senses"]]
        self.assertEqual(len(glosses), 3)
        self.assertIn("Wohnen", glosses[0])
        self.assertIn("Wohnhaus", entries[0]["senses"][0]["synonyms"])
        self.assertIn("Baracke", entries[0]["senses"][0]["antonyms"])

    def test_translations(self):
        pairs = W.parse_translations(self.en, "en", "de")
        self.assertEqual([p["dst"] for p in pairs], ["Haus"])
        self.assertEqual(pairs[0]["note"], "a building")
        self.assertEqual([p["dst"] for p in W.parse_translations(self.en, "en", "fr")], ["maison"])
        # a nested `*: Mandarin:` row still counts as Chinese
        self.assertEqual([p["dst"] for p in W.parse_translations(self.en, "en", "zh")], ["房子"])
        self.assertEqual(W.parse_translations(self.en, "en", "ja"), [])


class WiktionaryDriverTest(TempEnv):
    def row(self, **kw):
        cfg = {"id": "wikt", "driver": "wiktionary", "type": "dictionary",
               "url": "https://en.wiktionary.org/w/api.php", "languages": ["de"]}
        cfg.update(kw)
        return S.build(cfg)

    def test_edition_comes_from_the_url(self):
        self.assertEqual(self.row().edition, "en")
        self.assertEqual(self.row(url="https://de.wiktionary.org/w/api.php").edition, "de")

    def test_lookup_calls_the_api_and_parses(self):
        with fake_fetch(lambda url, **kw: api_reply(read_fixture("wiktionary-en-haus.txt"))) as calls:
            res = self.row().lookup("Haus", "de")
        self.assertIn("action=parse", calls[0][0])
        self.assertIn("prop=wikitext", calls[0][0])
        self.assertEqual(res["url"], "https://en.wiktionary.org/wiki/Haus")
        self.assertEqual(res["entries"][0]["pos"], "Noun")

    def test_a_missing_page_is_an_empty_result_not_an_error(self):
        reply = FakeResponse(json.dumps({"error": {"code": "missingtitle"}}),
                             headers={"content-type": "application/json"})
        with fake_fetch(lambda url, **kw: reply):
            self.assertEqual(self.row().lookup("qqqq", "de")["entries"], [])

    def test_a_broken_api_is_a_source_error(self):
        def boom(url, **kw):
            raise http.FetchError("boom", status=500, url=url)
        with fake_fetch(boom):
            with self.assertRaises(S.SourceError):
                self.row().lookup("Haus", "de")

    def test_thesaurus_uses_the_senses(self):
        with fake_fetch(lambda url, **kw: api_reply(read_fixture("wiktionary-en-haus.txt"))):
            res = self.row(type="thesaurus").thesaurus("Haus", "de")
        self.assertIn("Gebäude", res["synonyms"])
        self.assertIn("Hütte", res["antonyms"])


class LocalFallbackTest(TempEnv):
    def row(self, dataset="wiktionary-de", **kw):
        cfg = {"id": dataset, "driver": "local", "type": "dictionary",
               "path": f"{dataset}.sqlite", "dataset": dataset, "languages": ["de"]}
        cfg.update(kw)
        return S.build(cfg)

    def test_a_missing_wiktionary_falls_back_to_the_web(self):
        src = self.row()
        self.assertFalse(src.installed())
        self.assertTrue(src.available())
        self.assertTrue(src.supports("lookup", "de"))
        self.assertIsNotNone(src.web_fallback())
        self.assertEqual(src.web_fallback().edition, "en")

    def test_the_native_edition_row_asks_its_own_edition(self):
        src = self.row("wiktionary-de-native")
        self.assertEqual(src.web_fallback().edition, "de")

    def test_lookup_is_delegated(self):
        with fake_fetch(lambda url, **kw: api_reply(read_fixture("wiktionary-en-haus.txt"))) as calls:
            res = self.row().lookup("Haus", "de")
        self.assertTrue(calls)
        self.assertEqual(res["entries"][0]["pos"], "Noun")

    def test_the_card_says_the_answer_came_from_the_web(self):
        described = self.row().describe()
        self.assertEqual(described["fallback"], "web")
        self.assertTrue(described["name"].endswith("· web"))

    def test_status_explains_the_fallback(self):
        status = self.row().status()
        self.assertFalse(status["installed"])
        self.assertEqual(status["fallback"], "en")
        self.assertIn("wiktionary.org", status["note"])
        # still tells the user how to get the fast local copy
        self.assertIn("omababel data install wiktionary-de", status["hint"])

    def test_an_installed_dataset_wins(self):
        (self.data_dir / "mini-de.json").write_text(
            read_fixture("mini-de.json"), encoding="utf-8")
        src = self.row(path="mini-de.json")
        self.assertTrue(src.installed())
        with fake_fetch(lambda url, **kw: self.fail("the web must not be asked")):
            res = src.lookup("Haus", "de")
        self.assertTrue(res["entries"])

    def test_a_translator_row_translates_out_of_its_language(self):
        src = self.row(type="translator", translation_mode="word", languages=[])
        self.assertTrue(src.supports("translate", "de", "en"))
        self.assertFalse(src.supports("translate", "en", "de"))

    def test_a_non_wiktionary_dataset_has_no_fallback(self):
        self.assertIsNone(self.row("cedict").web_fallback())
        self.assertFalse(self.row("cedict").available())


if __name__ == "__main__":
    unittest.main()
