"""Remote drivers: page parsers on fixtures + request flows with a fake fetch."""

import json
import unittest

from helpers import FakeResponse, fake_fetch, read_fixture

from ob import http
from ob import sources as S
from ob.sources import deepl, duden, generic, google, leo, mw, oed, thesauruscom
from ob.sources.base import SourceError


class DudenTest(unittest.TestCase):
    def test_slug_and_marks(self):
        self.assertEqual(duden.slugify("Mädchen für alles"), "Maedchen_fuer_alles")
        self.assertEqual(duden.slugify("Straße"), "Strasze")
        self.assertEqual(duden.strip_marks("Ha̲u̲s"), "Haus")
        self.assertEqual(duden.strip_marks("Mädchen"), "Mädchen")

    def test_parse_entry(self):
        entries = duden.Duden.parse_entry(read_fixture("duden-haus.html"), "u")
        self.assertEqual(len(entries), 1)
        e = entries[0]
        self.assertEqual(e["headword"], "Haus")
        self.assertEqual(e["pos"], "Substantiv, Neutrum")
        labels = [s["label"] for s in e["senses"]]
        self.assertEqual(labels, ["1", "2", "2a", "2b", "3"])
        self.assertEqual(e["senses"][0]["gloss"], "Gebäude, das Menschen zum Wohnen dient")
        self.assertEqual(e["senses"][0]["examples"], ["ein großes, altes Haus", "das Haus steht leer"])
        self.assertEqual(e["senses"][0]["tags"], ["umgangssprachlich"])
        self.assertEqual(e["senses"][2]["examples"], ["das Haus war ausverkauft"])
        self.assertEqual(e["senses"][1]["examples"], [])   # sub-sense notes not attributed to parent
        self.assertEqual(e["senses"][0]["synonyms"], ["Anwesen", "Bau", "Bauwerk", "Gebäude", "Domizil", "Heim"])
        self.assertIn("mittelhochdeutsch", e["extra"]["Herkunft"])
        self.assertIn("Genitiv", e["extra"]["Grammatik"])
        self.assertEqual(e["extra"]["Worttrennung"], "Haus")
        self.assertNotIn("Häufigkeit", e["extra"])
        self.assertEqual(e["pronunciation"], "Betonung: Haus")

    def test_parse_search(self):
        url = duden.Duden.parse_search(read_fixture("duden-search.html"), "Haus")
        self.assertEqual(url, "https://www.duden.de/rechtschreibung/Haus")
        first = duden.Duden.parse_search(read_fixture("duden-search.html"), "Zzz")
        self.assertEqual(first, "https://www.duden.de/rechtschreibung/Hausarbeit")
        self.assertIsNone(duden.Duden.parse_search("<html></html>"))

    def test_generic_fallback_on_redesign(self):
        markup = '<h1>Wort</h1><div class="division" id="x"><h2>Bedeutung</h2><p>irgendwas</p></div>'
        entries = duden.Duden.parse_entry(markup)
        self.assertEqual(entries[0]["senses"][0]["gloss"], "irgendwas")
        self.assertEqual(entries[0]["senses"][0]["label"], "Bedeutung")

    def test_lookup_flow_404_then_search(self):
        src = S.build({"id": "duden", "driver": "duden", "type": "dictionary"})
        pages = {
            "https://www.duden.de/rechtschreibung/Haeuser": None,
            "https://www.duden.de/suchen/dudenonline/H%C3%A4user": read_fixture("duden-search.html"),
            "https://www.duden.de/rechtschreibung/Hausarbeit": read_fixture("duden-haus.html"),
        }

        def handler(url, **kw):
            page = pages.get(url)
            if page is None:
                raise http.FetchError("404", status=404, url=url)
            return FakeResponse(page)

        with fake_fetch(handler) as calls:
            res = src.lookup("Häuser", "de")
        self.assertEqual(len(calls), 3)
        self.assertEqual(res["entries"][0]["headword"], "Haus")
        self.assertEqual(res["url"], "https://www.duden.de/rechtschreibung/Hausarbeit")
        with fake_fetch(lambda url, **kw: (_ for _ in ()).throw(http.FetchError("boom", status=500))):
            with self.assertRaises(SourceError):
                src.lookup("x", "de")
        # thesaurus mode reuses the synonyms of the entry
        with fake_fetch(lambda url, **kw: FakeResponse(read_fixture("duden-haus.html"))):
            th = src.thesaurus("Haus", "de")
        self.assertIn("Gebäude", th["synonyms"])
        self.assertEqual(th["groups"][0]["label"], "Gebäude, das Menschen zum Wohnen dient")


class MerriamWebsterTest(unittest.TestCase):
    def test_parse_dictionary(self):
        entries = mw.MerriamWebster.parse_dictionary(read_fixture("mw-house.html"))
        self.assertEqual(len(entries), 2)
        noun = entries[0]
        self.assertEqual((noun["headword"], noun["pos"], noun["pronunciation"]), ("house", "noun", "ˈhau̇s"))
        self.assertEqual([s["label"] for s in noun["senses"]], ["a", "b", "2"])
        self.assertEqual(noun["senses"][0]["gloss"], "a building that serves as living quarters for one or a few families")
        self.assertEqual(noun["senses"][0]["examples"], ["a house on the corner"])
        self.assertEqual(noun["senses"][0]["synonyms"], ["home", "dwelling"])
        self.assertEqual(entries[1]["pos"], "verb")
        self.assertEqual(entries[1]["senses"][0]["gloss"], "to provide with living quarters")

    def test_parse_thesaurus(self):
        syn, ant = mw.MerriamWebster.parse_thesaurus(read_fixture("mw-thes-house.html"))
        self.assertEqual(syn, ["home", "dwelling", "residence"])
        self.assertEqual(ant, ["office", "evict"])   # MW groups near antonyms with antonyms
        syn, ant = mw.MerriamWebster.parse_thesaurus(read_fixture("mw-thes-new.html"))
        self.assertEqual((syn, ant), (["home", "abode"], ["evict"]))
        # antonym boxes share the synonym list class; the box heading decides,
        # and the "Definitions" link back to the dictionary is not a word
        groups = mw.MerriamWebster.parse_thesaurus_groups(read_fixture("mw-thes-headings.html"))
        self.assertEqual([(g["label"], g["synonyms"], g["antonyms"]) for g in groups],
                         [("as in home", ["home", "abode"], ["office", "workplace"]),
                          ("as in family", ["household"], [])])
        # real-page shapes: nested headings, a sense without an "as in" label, a
        # heading that sits before its box, and trailing page navigation
        groups = mw.MerriamWebster.parse_thesaurus_groups(read_fixture("mw-thes-deep.html"))
        self.assertEqual([(g["label"], g["synonyms"], g["antonyms"]) for g in groups],
                         [("as in home", ["home", "abode"], ["office"]),
                          ("", ["household"], ["individual", "stranger"]),
                          ("as in accommodate", ["lodge"], ["evict"])])
        groups = mw.MerriamWebster.parse_thesaurus_groups(read_fixture("mw-thes-senses.html"))
        self.assertEqual([(g["pos"], g["label"], g["synonyms"], g["antonyms"]) for g in groups],
                         [("noun", "as in home", ["home", "abode"], ["office"]),
                          ("noun", "as in family", ["household"], []),
                          ("verb", "as in accommodate", ["lodge"], ["evict"])])

    def test_thesaurus_never_lists_antonyms_as_synonyms(self):
        """The 'evidence' shape: an entry-wide antonym box carrying the very
        class MW also uses for synonym boxes, and no heading of its own."""
        groups = mw.MerriamWebster.parse_thesaurus_groups(read_fixture("mw-thes-evidence.html"))
        self.assertEqual([(g["pos"], g["label"], g["synonyms"], g["antonyms"]) for g in groups],
                         [("noun", "as in proof", ["proof", "testimony", "confirmation"],
                           ["confutation", "disproof"]),
                          ("noun", "as in document", ["record", "certificate"], []),
                          ("verb", "as in show", ["demonstrate", "attest"],
                           ["confute", "rebut", "disprove"])])
        # nothing that is an antonym anywhere may show up as a synonym
        syn = {w.lower() for g in groups for w in g["synonyms"]}
        for bad in ("confute", "disprove", "rebut", "confutation", "disproof"):
            self.assertNotIn(bad, syn)
        # and the page navigation below the entry stays out
        self.assertNotIn("evident", syn)

    def test_thesaurus_drops_boxes_it_cannot_place(self):
        markup = ('<div class="sense-content"><p class="as-in">as in proof</p>'
                  '<div class="thes-list syn-list"><ul><li><a href="/thesaurus/proof">proof</a></li></ul></div>'
                  '<div class="thes-list rel-list"><ul><li><a href="/thesaurus/hint">hint</a></li></ul></div>'
                  '</div>')
        groups = mw.MerriamWebster.parse_thesaurus_groups(markup)
        self.assertEqual([(g["synonyms"], g["antonyms"]) for g in groups], [(["proof"], [])])

    def test_api_parsing(self):
        data = [{"meta": {"id": "house:1"}, "hwi": {"hw": "house", "prs": [{"mw": "ˈhau̇s"}]}, "fl": "noun",
                 "shortdef": ["a building"],
                 "def": [{"sseq": [[["sense", {"sn": "1 a", "dt": [["text", "{bc}a building that {a_link|serves} as living quarters"],
                                                                     ["vis", [{"t": "a {it}house{/it} on the corner"}]]]}]]]}]},
                "housed", "houses"]
        entries = mw.MerriamWebster.parse_api_dictionary(data, "house")
        self.assertEqual(len(entries), 1)
        s = entries[0]["senses"][0]
        self.assertEqual(s["gloss"], "a building that serves as living quarters")
        self.assertEqual(s["examples"], ["a house on the corner"])
        self.assertEqual(s["label"], "1 a")
        syn, ant = mw.MerriamWebster.parse_api_thesaurus([{"meta": {"syns": [["home", "abode"]], "ants": [["evict"]]}}, "x"], "house")
        self.assertEqual((syn, ant), (["home", "abode"], ["evict"]))
        self.assertEqual(mw.strip_tokens("{bc}see {sx|home||}"), "see home")

    def test_flows(self):
        src = S.build({"id": "mw", "driver": "mw", "type": "dictionary"})
        with fake_fetch(lambda url, **kw: FakeResponse(read_fixture("mw-house.html"))) as calls:
            res = src.lookup("house", "en")
        self.assertIn("/dictionary/house", calls[0][0])
        self.assertEqual(len(res["entries"]), 2)
        with fake_fetch(lambda url, **kw: (_ for _ in ()).throw(http.FetchError("nf", status=404))):
            self.assertEqual(src.lookup("zzz", "en")["entries"], [])
        keyed = S.build({"id": "mw", "driver": "mw", "type": "thesaurus", "api_key": "KEY"})
        with fake_fetch(lambda url, **kw: FakeResponse(json.dumps([{"meta": {"syns": [["home"]], "ants": []}}]))) as calls:
            th = keyed.thesaurus("house", "en")
        self.assertIn("key=KEY", calls[0][0])
        self.assertIn("references/thesaurus", calls[0][0])
        self.assertEqual(th["synonyms"], ["home"])


class ThesaurusComTest(unittest.TestCase):
    def test_json_path(self):
        syn, ant = thesauruscom.ThesaurusCom.parse(read_fixture("thesaurus-house.html"))
        self.assertEqual(syn, ["apartment", "home", "shack", "household", "clan"])
        self.assertEqual(ant, ["office"])
        groups = thesauruscom.ThesaurusCom.parse_groups(read_fixture("thesaurus-house.html"))
        self.assertEqual([(g["pos"], g["label"], g["synonyms"], g["antonyms"]) for g in groups],
                         [("noun", "human habitat", ["apartment", "home", "shack"], ["office"]),
                          ("noun", "family", ["household", "clan"], [])])

    def test_dom_path(self):
        syn, ant = thesauruscom.ThesaurusCom.parse(read_fixture("thesaurus-house-dom.html"))
        self.assertEqual((syn, ant), (["home", "dwelling"], ["office"]))

    def test_dom_walk_separates_antonyms(self):
        # 2026 layout: no data-type attributes, no JSON – only headings.
        syn, ant = thesauruscom.ThesaurusCom.parse(read_fixture("thesaurus-house-2026.html"))
        self.assertEqual(syn, ["apartment", "home", "abode", "household", "clan"])
        self.assertEqual(ant, ["office"])          # not lumped into synonyms; related words ignored
        groups = thesauruscom.ThesaurusCom.parse_groups(read_fixture("thesaurus-house-2026.html"))
        self.assertEqual([(g["pos"], g["label"]) for g in groups], [("noun", "human habitat"), ("noun", "family, ancestry")])
        self.assertEqual(groups[0]["antonyms"], ["office"])
        self.assertEqual(groups[1]["antonyms"], [])

    def test_definitions_tab_is_not_a_word(self):
        # thesaurus.com links its Definitions tab to dictionary.com, whose URLs
        # share the /browse/ shape – it used to end up as a card of its own.
        groups = thesauruscom.ThesaurusCom.parse_groups(read_fixture("thesaurus-house-junk.html"))
        self.assertEqual([(g["synonyms"], g["antonyms"]) for g in groups], [(["apartment"], ["office"])])
        syn, ant = thesauruscom.ThesaurusCom.parse(read_fixture("thesaurus-house-junk.html"))
        self.assertEqual((syn, ant), (["apartment"], ["office"]))

    def test_escaped_json(self):
        markup = 'self.__next_f.push("{\\"synonyms\\":[{\\"term\\":\\"abode\\"}]}")'
        syn, ant = thesauruscom.ThesaurusCom.parse(markup)
        self.assertEqual(syn, ["abode"])

    def test_flow(self):
        src = S.build({"id": "t", "driver": "thesauruscom", "type": "thesaurus"})
        with fake_fetch(lambda url, **kw: FakeResponse(read_fixture("thesaurus-house.html"))):
            res = src.thesaurus("house", "en")
        self.assertEqual(res["url"], "https://www.thesaurus.com/browse/house")
        self.assertIn("home", res["synonyms"])
        self.assertEqual(len(res["groups"]), 2)


class LeoTest(unittest.TestCase):
    def test_pair_codes(self):
        self.assertEqual(leo.Leo.pair_code("en", "de"), ("ende", "en"))
        self.assertEqual(leo.Leo.pair_code("de", "zh"), ("chde", "zh"))
        with self.assertRaises(SourceError):
            leo.Leo.pair_code("en", "fr")

    def test_parse_xml(self):
        pairs = leo.Leo.parse_xml(read_fixture("leo-house.xml"), "en", "de")
        self.assertEqual([(p["src"], p["dst"]) for p in pairs],
                         [("house", "das Haus Pl.: die Häuser"), ("building", "Gebäude"),
                          # LEO's trailing form separator is dropped
                          ("to house | housed, housed", "unterbringen | brachte unter, untergebracht")])
        self.assertEqual(pairs[0]["pos"], "Substantive")
        rev = leo.Leo.parse_xml(read_fixture("leo-house.xml"), "de", "en")
        self.assertEqual(rev[0]["src"], "das Haus Pl.: die Häuser")

    def test_parse_html(self):
        pairs = leo.Leo.parse_html(read_fixture("leo-house.html"), "de", "en")
        self.assertEqual([(p["src"], p["dst"], p["pos"]) for p in pairs],
                         [("das Haus", "house", "Nouns"), ("das Gebäude", "building", "Nouns"), ("unterbringen", "to house", "Verbs")])

    def test_flow_xml_then_html(self):
        src = S.build({"id": "leo", "driver": "leo", "type": "translator"})
        self.assertTrue(src.supports("translate", "en", "de"))
        self.assertFalse(src.supports("translate", "en", "fr"))

        def handler(url, **kw):
            if "query.xml" in url:
                raise http.FetchError("blocked", status=403)
            return FakeResponse(read_fixture("leo-house.html"))

        with fake_fetch(handler) as calls:
            res = src.translate("house", "en", "de")
        self.assertEqual(len(calls), 2)
        self.assertEqual(res["mode"], "word")
        self.assertEqual(res["pairs"][0]["dst"], "das Haus")
        self.assertEqual(res["url"], "https://dict.leo.org/englisch-deutsch/house")
        with fake_fetch(lambda url, **kw: FakeResponse(read_fixture("leo-house.xml"), headers={"content-type": "text/xml"})):
            res = src.translate("Haus", "de", "en")
        self.assertEqual(res["pairs"][0]["dst"], "house")


class GoogleTest(unittest.TestCase):
    def test_parse_gtx(self):
        data = [[["Haus", "house", None, None, 10], [None, None, "haʊs"]],
                [["noun", ["Haus", "Gebäude"], [["Haus", ["house", "home"], None, 0.5], ["Gebäude", ["building", "house"]]], "house", 1]],
                "en", None, None, [["house", None, [["Haus", 0, True, False], ["Gebäude", 0, True, False]]]]]
        res = google.GoogleTranslate.parse_gtx(data)
        self.assertEqual(res["text"], "Haus")
        self.assertEqual(res["detected"], "en")
        self.assertEqual([(p["src"], p["dst"], p["pos"]) for p in res["pairs"]], [("house", "Haus", "noun"), ("house", "Gebäude", "noun")])
        self.assertEqual(res["pairs"][0]["note"], "house, home")
        self.assertEqual(res["alternatives"], ["Gebäude"])
        with self.assertRaises(SourceError):
            google.GoogleTranslate.parse_gtx({"bad": 1})

    def test_flows(self):
        src = S.build({"id": "g", "driver": "google", "type": "translator"})
        self.assertTrue(src.supports("translate", "ja", "sw"))
        with fake_fetch(lambda url, **kw: FakeResponse('[[["Haus","house"]],null,"en"]')) as calls:
            res = src.translate("house", "en", "de")
        self.assertIn("sl=en&tl=de", calls[0][0])
        self.assertEqual(res["text"], "Haus")
        self.assertEqual(res["mode"], "text")
        keyed = S.build({"id": "g", "driver": "google", "type": "translator", "api_key": "K", "translation_mode": "word"})
        with fake_fetch(lambda url, **kw: FakeResponse('{"data":{"translations":[{"translatedText":"Haus"}]}}')) as calls:
            res = keyed.translate("house", "en", "de")
        self.assertIn("translation.googleapis.com", calls[0][0])
        self.assertEqual(calls[0][1]["data"]["target"], "de")
        self.assertEqual((res["text"], res["mode"]), ("Haus", "word"))
        with fake_fetch(lambda url, **kw: FakeResponse("<html>captcha</html>")):
            with self.assertRaises(SourceError):
                src.translate("x", "en", "de")


class DeepLTest(unittest.TestCase):
    def test_rpc_body(self):
        raw = deepl.DeepL.build_rpc("hi", "EN", "DE", rpc_id=8300000000, now_ms=1000)
        body = json.loads(raw)
        self.assertEqual(body["params"]["lang"]["target_lang"], "DE")
        self.assertEqual(body["params"]["timestamp"], 1000 - 1000 % 2 + 2)
        self.assertIn('"method": "', raw)  # 8300000000: (id+5)%29 != 0 and (id+3)%13 != 0 -> normal spacing
        # find an id where the odd spacing rule applies
        odd = next(i for i in range(8300000000, 8300000100) if (i + 5) % 29 == 0)
        self.assertIn('"method" : "', deepl.DeepL.build_rpc("x", "EN", "DE", rpc_id=odd, now_ms=1))

    def test_parse_rpc(self):
        data = {"result": {"source_lang": "EN", "translations": [{"beams": [
            {"sentences": [{"text": "Hallo"}]}, {"sentences": [{"text": "Servus"}]}]}]}}
        res = deepl.DeepL.parse_rpc(data)
        self.assertEqual((res["text"], res["detected"], res["alternatives"]), ("Hallo", "en", ["Servus"]))
        with self.assertRaises(SourceError):
            deepl.DeepL.parse_rpc({"error": {"message": "Too many requests"}})

    def test_flows(self):
        src = S.build({"id": "d", "driver": "deepl", "type": "translator"})
        self.assertTrue(src.supports("translate", "de", "en"))
        self.assertFalse(src.supports("translate", "de", "sw"))
        with fake_fetch(lambda url, **kw: FakeResponse('{"result":{"translations":[{"beams":[{"sentences":[{"text":"Haus"}]}]}]}}')) as calls:
            res = src.translate("house", "en", "de")
        self.assertIn("www2.deepl.com", calls[0][0])
        self.assertEqual(res["text"], "Haus")
        keyed = S.build({"id": "d", "driver": "deepl", "type": "translator", "api_key": "abc:fx"})
        with fake_fetch(lambda url, **kw: FakeResponse('{"translations":[{"detected_source_language":"EN","text":"Haus"}]}')) as calls:
            res = keyed.translate("house", "en", "de")
        self.assertTrue(calls[0][0].startswith("https://api-free.deepl.com"))
        self.assertEqual(calls[0][1]["headers"]["Authorization"], "DeepL-Auth-Key abc:fx")
        self.assertEqual(calls[0][1]["data"]["target_lang"], "DE")
        self.assertEqual(res["detected"], "en")
        with fake_fetch(lambda url, **kw: (_ for _ in ()).throw(http.FetchError("x", status=429))):
            with self.assertRaises(SourceError) as ctx:
                src.translate("x", "en", "de")
            self.assertIn("rate limited", str(ctx.exception))


class OEDTest(unittest.TestCase):
    def test_parse_search(self):
        entries = oed.OED.parse_search(read_fixture("oed-search.html"), "house")
        self.assertEqual(len(entries), 2)   # duplicate entry link collapsed
        self.assertEqual((entries[0]["headword"], entries[0]["pos"]), ("house", "n.¹"))
        self.assertIn("building for human habitation", entries[0]["senses"][0]["gloss"])
        self.assertEqual(entries[0]["url"], "https://www.oed.com/dictionary/house_n1?tab=meaning_and_use")

    def test_api_flow(self):
        src = S.build({"id": "oed", "driver": "oed", "type": "dictionary", "api_key": "id:key"})

        def handler(url, **kw):
            self.assertEqual(kw["headers"]["app_id"], "id")
            if "/senses/" in url:
                return FakeResponse('{"data":[{"definition":"A building.","sense_number":"I.1"}]}')
            return FakeResponse('{"data":[{"id":"house_nn01","lemma":"house","parts_of_speech":["NN"],"definition":"x","etymology_summary":"Old English"}]}')

        with fake_fetch(handler):
            res = src.lookup("house", "en")
        e = res["entries"][0]
        self.assertEqual(e["senses"][0]["gloss"], "A building.")
        self.assertEqual(e["extra"]["Etymology"], "Old English")
        bad = S.build({"id": "oed", "driver": "oed", "type": "dictionary", "api_key": "nocolon"})
        with fake_fetch(lambda url, **kw: FakeResponse("{}")):
            with self.assertRaises(SourceError):
                bad.lookup("house", "en")


class GenericTest(unittest.TestCase):
    def test_json_and_html(self):
        src = S.build({"id": "c", "driver": "generic", "type": "dictionary", "url": "https://api/{word}", "api_key": "T"})
        with fake_fetch(lambda url, **kw: FakeResponse('{"word":"x","synonyms":[{"term":"y"},"z"],"antonyms":["w"]}', headers={"content-type": "application/json"})) as calls:
            res = src.lookup("x", "en")
        self.assertEqual(calls[0][1]["headers"]["Authorization"], "Bearer T")
        self.assertEqual(res["entries"][0]["senses"][1]["synonyms"], ["y", "z"])
        self.assertIn("word: x", res["entries"][0]["senses"][0]["gloss"])
        html = "<html><nav>skip</nav><main><h1>Word</h1><p>Meaning one</p></main><footer>f</footer></html>"
        with fake_fetch(lambda url, **kw: FakeResponse(html)):
            res = src.lookup("x", "en")
        self.assertEqual(res["entries"][0]["senses"][0]["gloss"], "Word Meaning one")
        th = S.build({"id": "c", "driver": "generic", "type": "thesaurus", "url": "https://api/{word}"})
        with fake_fetch(lambda url, **kw: FakeResponse('{"synonyms":["a"]}')):
            self.assertEqual(th.thesaurus("x", "en")["synonyms"], ["a"])
        tr = S.build({"id": "c", "driver": "generic", "type": "translator", "url": "https://t/{from}/{to}/{word}"})
        with fake_fetch(lambda url, **kw: FakeResponse("Haus")) as calls:
            self.assertEqual(tr.translate("house", "en", "de")["text"], "Haus")
        self.assertEqual(calls[0][0], "https://t/en/de/house")
        bad = S.build({"id": "c", "driver": "generic", "type": "dictionary", "url": "https://no-placeholder"})
        with self.assertRaises(SourceError):
            bad.lookup("x", "en")


class RegistryTest(unittest.TestCase):
    def test_registry(self):
        names = [d["driver"] for d in S.registry()]
        self.assertEqual(names[0], "local")
        for n in ("duden", "mw", "oed", "thesauruscom", "leo", "google", "deepl", "generic"):
            self.assertIn(n, names)
        with self.assertRaises(SourceError):
            S.get_driver("nope")
        for d in S.registry():
            self.assertTrue(d["types"])
            self.assertIn(d["kind"], ("remote", "local"))


if __name__ == "__main__":
    unittest.main()
