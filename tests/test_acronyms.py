"""Acronym and abbreviation lookup: the three sites and what they answer."""

import unittest

from helpers import FakeResponse, TempEnv, fake_fetch, read_fixture

from ob import sources as S
from ob.sources import acronyms as A


class ShapeTest(unittest.TestCase):
    def test_what_counts_as_an_acronym(self):
        for yes in ("NASA", "PhD", "B2B", "Wi-Fi", "IT", "UNESCO", "I18N"):
            self.assertTrue(A.looks_like_acronym(yes), yes)
        for no in ("Haus", "nasa", "house price", "a", "", "internationalisation",
                   "Städtepartnerschaft"):
            self.assertFalse(A.looks_like_acronym(no), no)

    def test_all_caps_is_the_strong_signal(self):
        self.assertTrue(A.is_all_caps("NASA"))
        self.assertTrue(A.is_all_caps("B2B"))
        self.assertFalse(A.is_all_caps("PhD"))
        self.assertFalse(A.is_all_caps("NASA rocket"))

    def test_folding_ignores_dots_and_case(self):
        self.assertEqual(A.fold("N.A.S.A."), A.fold("nasa"))


class ParserTest(unittest.TestCase):
    def meanings(self, cls, fixture, acronym="NASA"):
        return [m for m, _c in cls.parse(read_fixture(fixture), acronym)]

    def test_thefreedictionary(self):
        got = self.meanings(A.FreeDictionaryAcronyms, "tfd-acronyms-nasa.html")
        self.assertIn("National Aeronautics and Space Administration", got)
        self.assertIn("North American Saxophone Alliance", got)
        # a near-miss row for a *different* acronym stays out
        self.assertNotIn("North American Securities Administrators Association", got)

    def test_acronymfinder_keeps_the_category_and_drops_the_rating(self):
        rows = A.AcronymFinder.parse(read_fixture("acronymfinder-nasa.html"), "NASA")
        self.assertEqual(rows[0][0], "National Aeronautics and Space Administration")
        self.assertIn("Governmental", rows[0][1])
        self.assertEqual([c for _m, c in rows], ["Governmental » NASA", "Sports", "Miscellaneous"])

    def test_allacronyms_reads_the_meaning_links(self):
        rows = A.AllAcronyms.parse(read_fixture("allacronyms-nasa.html"), "NASA")
        got = [m for m, _c in rows]
        self.assertIn("National Aeronautics and Space Administration", got)
        # an empty link falls back to the href
        self.assertIn("North American Saxophone Alliance", got)
        # the site's own navigation is not a meaning
        self.assertNotIn("abbreviated", got)
        self.assertEqual(rows[0][1], "Space")

    def test_the_generic_table_reader_is_the_fallback(self):
        markup = """<table>
          <tr><th>Abbreviation</th><th>Full form</th><th>Field</th></tr>
          <tr><td>API</td><td>Application Programming Interface</td><td>Computing</td></tr>
          <tr><td>API</td><td>Active Pharmaceutical Ingredient</td><td>Medicine</td></tr>
          <tr><td>APR</td><td>Annual Percentage Rate</td><td>Finance</td></tr>
        </table>"""
        import ob.htmlutil as H
        rows = A.rows_from_tables(H.parse(markup), "API")
        self.assertEqual([m for m, _c in rows],
                         ["Application Programming Interface", "Active Pharmaceutical Ingredient"])
        self.assertEqual(rows[0][1], "Computing")


class EntryTest(unittest.TestCase):
    def test_entries_carry_the_acronym_and_drop_duplicates(self):
        entries = A.to_entries("NASA", [("National Aeronautics and Space Administration", "Space"),
                                        ("national aeronautics and space administration", ""),
                                        ("", "")], url="https://example.invalid/NASA")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["pos"], "acronym")
        self.assertEqual(len(entries[0]["senses"]), 1)
        self.assertEqual(entries[0]["senses"][0]["acronym"], "NASA")
        self.assertEqual(entries[0]["senses"][0]["tags"], ["Space"])

    def test_no_meanings_is_no_entry(self):
        self.assertEqual(A.to_entries("NASA", []), [])


class DriverTest(TempEnv):
    def row(self, driver="tfd-acronyms", **kw):
        cfg = {"id": driver, "driver": driver, "type": "dictionary"}
        cfg.update(kw)
        return S.build(cfg)

    def test_a_plain_word_is_not_looked_up_at_all(self):
        with fake_fetch(lambda url, **kw: self.fail("no request for an ordinary word")) as calls:
            res = self.row().lookup("Haus", "de")
        self.assertEqual(res["entries"], [])
        self.assertEqual(calls, [])

    def test_an_acronym_is_fetched_and_parsed(self):
        markup = read_fixture("tfd-acronyms-nasa.html")
        with fake_fetch(lambda url, **kw: FakeResponse(markup)) as calls:
            res = self.row().lookup("NASA", "en")
        self.assertEqual(calls[0][0], "https://acronyms.thefreedictionary.com/NASA")
        self.assertEqual(res["entries"][0]["headword"], "NASA")
        self.assertGreaterEqual(len(res["entries"][0]["senses"]), 3)

    def test_the_three_built_in_rows_are_enabled(self):
        from ob.config import default_sources
        rows = {r["id"]: r for r in default_sources()}
        for id in ("tfd-acronyms", "acronymfinder", "allacronyms"):
            self.assertIn(id, rows)
            self.assertTrue(rows[id]["enabled"], id)
            self.assertEqual(rows[id]["type"], "dictionary")
            # no language: an acronym is not a language's property
            self.assertEqual(rows[id]["languages"], [])

    def test_they_are_chosen_for_any_language(self):
        src = self.row()
        self.assertTrue(src.supports("lookup", "de"))
        self.assertTrue(src.supports("lookup", "ja"))
        self.assertFalse(src.supports("thesaurus", "en"))


if __name__ == "__main__":
    unittest.main()
