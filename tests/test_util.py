"""htmlutil, results helpers, languages, render."""

import unittest

import helpers  # noqa: F401  (sets up sys.path / offline mode)

from ob import htmlutil, languages, render
from ob import results as R


class HtmlUtilTest(unittest.TestCase):
    def test_parse_and_query(self):
        doc = htmlutil.parse('<div id="a" class="x y"><p>Hello <b>world</b></p><ul><li>one<li>two</ul></div>')
        a = doc.find(id="a")
        self.assertIsNotNone(a)
        self.assertTrue(a.has_class("y"))
        self.assertEqual([li.inline_text() for li in a.find_all("li")], ["one", "two"])
        self.assertEqual(a.find("p").inline_text(), "Hello world")
        self.assertEqual(doc.find(cls="missing"), None)

    def test_text_extraction_skips_scripts_and_blocks(self):
        doc = htmlutil.parse("<div><script>var x = 1</script><p>a</p><p>b</p><br>c</div>")
        self.assertEqual(doc.get_text(), "a\nb\nc")
        self.assertEqual(htmlutil.strip_tags("<p>x &amp; y</p><script>z</script><div>q</div>"), "x & y\nq")

    def test_attrs_and_closest(self):
        doc = htmlutil.parse('<table id="t"><tr data-dz-ui="dictentry"><td lang="en">house</td></tr></table>')
        td = doc.find("td")
        self.assertEqual(td.get("lang"), "en")
        self.assertEqual(td.closest("table").id, "t")
        self.assertEqual(len(doc.find_all(attrs={"data-dz-ui": "dictentry"})), 1)

    def test_find_json_blob(self):
        markup = 'x = 1; window.__STATE__ = {"a": [1, {"b": "}"}], "c": "\\"]"} ; more'
        blob = htmlutil.find_json_blob(markup, "window.__STATE__")
        self.assertEqual(blob, '{"a": [1, {"b": "}"}], "c": "\\"]"}')
        self.assertIsNone(htmlutil.find_json_blob(markup, "nope"))
        self.assertEqual(htmlutil.find_json_blob('"synonyms":[{"t":1}]', '"synonyms":'), '[{"t":1}]')

    def test_unclosed_tags_are_tolerated(self):
        doc = htmlutil.parse("<div><p>one<p>two</div><span>after")
        self.assertEqual([p.inline_text() for p in doc.find_all("p")], ["one", "two"])
        self.assertEqual(doc.find("span").inline_text(), "after")


class ResultsTest(unittest.TestCase):
    def test_dedupe_and_sort(self):
        self.assertEqual(R.dedupe(["b", " a ", "B", "", "a"]), ["b", "a"])
        self.assertEqual(R.sort_words(["Zebra", "äpfel", "apple", "Apple"]), ["äpfel", "apple", "Zebra"])

    def test_consolidate(self):
        parts = [{"synonyms": ["home", "Dwelling"], "antonyms": ["office"]},
                 {"synonyms": ["abode", "home"], "antonyms": ["home", "Office"]}, None]
        out = R.consolidate(parts)
        self.assertEqual(out["synonyms"], ["abode", "Dwelling", "home"])
        self.assertEqual(out["antonyms"], ["office"])   # "home" dropped: it is a synonym
        self.assertEqual(out["groups"], [])

    def test_thesaurus_groups(self):
        # flat lists only -> one unlabelled group; groups only -> flat lists derived
        flat = R.thesaurus(["b", "a"], ["z"])
        self.assertEqual(flat["groups"], [{"label": "", "pos": "", "synonyms": ["b", "a"], "antonyms": ["z"]}])
        grouped = R.thesaurus([], [], groups=[R.group(["x", "y"], [], label="one", pos="noun"),
                                              R.group(["y", "w"], ["q"], label="two"), R.group([], [], label="empty")])
        self.assertEqual(grouped["synonyms"], ["x", "y", "w"])
        self.assertEqual(grouped["antonyms"], ["q"])
        self.assertEqual([g["label"] for g in grouped["groups"]], ["one", "two"])
        entries = [{"pos": "noun", "senses": [{"gloss": "g1", "synonyms": ["s1"], "antonyms": []},
                                             {"gloss": "g2", "synonyms": [], "antonyms": []},
                                             {"gloss": "g3", "synonyms": [], "antonyms": ["a3"]}]}]
        self.assertEqual([g["label"] for g in R.groups_from_senses(entries)], ["g1", "g3"])
        out = R.consolidate([{"source": {"id": "s", "name": "S"}, "synonyms": ["b", "a"], "antonyms": [],
                             "groups": [R.group(["b", "a"], [], label="L")]}])
        self.assertEqual(out["groups"], [{"source": "S", "source_id": "s", "label": "L", "pos": "",
                                          "synonyms": ["a", "b"], "antonyms": []}])

    def test_entry_shape(self):
        e = R.entry(" Haus ", pos="n", senses=[R.sense("x", examples=["", "y"])], extra={"a": "", "b": "c"})
        self.assertEqual(e["headword"], "Haus")
        self.assertEqual(e["senses"][0]["examples"], ["y"])
        self.assertEqual(e["extra"], {"b": "c"})


class LanguagesTest(unittest.TestCase):
    def test_normalize(self):
        for given, want in [("de", "de"), ("DE", "de"), ("deu", "de"), ("German", "de"), ("zh-CN", "zh"),
                            ("cmn", "zh"), ("zho", "zh"), ("nor", "nb"), ("iw", "he"), ("en-US", "en"),
                            ("xx", None), ("", None), (None, None)]:
            self.assertEqual(languages.normalize(given), want, given)

    def test_codes(self):
        self.assertEqual(languages.iso3("de"), "deu")
        self.assertEqual(languages.leo_code("zh"), "ch")
        self.assertEqual(languages.deepl_code("pt"), "PT-PT")
        self.assertEqual(languages.google_code("zh"), "zh-CN")
        self.assertIsNone(languages.leo_code("ja"))

    def test_options_english_first_then_alphabetical(self):
        opts = languages.options()
        self.assertEqual(opts[0]["value"], "en")
        labels = [o["label"] for o in opts[1:]]
        self.assertEqual(labels, sorted(labels))
        self.assertEqual(len(opts), len(languages.LANGUAGES))


class RenderTest(unittest.TestCase):
    def test_linkify_escapes_and_links(self):
        html = render.linkify("l'été <b> & 中国人")
        self.assertIn('<a href="w:l%27%C3%A9t%C3%A9">l&#x27;été</a>', html)
        self.assertIn("&lt;<a href=\"w:b\">b</a>&gt; &amp;", html)
        self.assertIn('<a href="w:%E4%B8%AD%E5%9B%BD%E4%BA%BA">中国人</a>', html)
        self.assertEqual(render.href_word(render.word_href("well-known")), "well-known")
        self.assertEqual(render.linkify(""), "")

    def test_decorate(self):
        res = {"mode": "lookup", "results": [{"entries": [
            {"headword": "Haus", "senses": [{"gloss": "a b", "examples": ["c"], "synonyms": ["d"], "antonyms": []}],
             "extra": {"k": "v w"}}]}]}
        render.decorate(res)
        e = res["results"][0]["entries"][0]
        self.assertIn("<a", e["headword_html"])
        self.assertIn("<a", e["senses"][0]["gloss_html"])
        self.assertEqual(e["extra_html"][0]["key"], "k")
        tr = {"mode": "translate", "results": [{"text": "a b", "pairs": [{"src": "x", "dst": "y"}]}]}
        render.decorate(tr)
        self.assertIn("<a", tr["results"][0]["text_html"])
        self.assertIn("<a", tr["results"][0]["pairs"][0]["dst_html"])


if __name__ == "__main__":
    unittest.main()
