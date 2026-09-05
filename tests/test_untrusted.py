"""What a scraped page must not be able to do.

Everything in this file starts from the same assumption: the text a source
returns was written by somebody else, and the panel renders it, copies it and
offers to open its links.
"""

import unittest

from helpers import TempEnv

from ob import clipboard, htmlutil, render, results as R, secrets
from ob.sources.oed import OED, WEB_ORIGIN


class RichTextTest(unittest.TestCase):
    """The panel's one rich-text element renders `*_html` fields, so every
    field that reaches it has to be escaped on the way out."""

    def decorate(self, sense):
        result = {"mode": "lookup", "results": [{"entries": [R.entry("Haus", senses=[sense])]}]}
        render.decorate_lookup(result)
        return result["results"][0]["entries"][0]["senses"][0]

    def test_a_tag_is_escaped(self):
        # Duden's "Gebrauch"/"Grammatik" notes become tags, and Qt rich text
        # fetches <img src="…"> – a page could otherwise beacon out, or read
        # a local file into the render, the moment a card appears.
        s = self.decorate(R.sense("a house", tags=['<img src="https://evil.example/px">']))
        self.assertIn("tags_html", s)
        self.assertNotIn("<img", s["tags_html"][0])
        self.assertIn("&lt;img", s["tags_html"][0])

    def test_an_empty_tag_is_dropped(self):
        self.assertEqual(self.decorate(R.sense("x", tags=["", None, "ok"]))["tags_html"], ["ok"])

    def test_the_other_fields_are_escaped_too(self):
        s = self.decorate(R.sense('<script>alert(1)</script>', examples=["<img src=x>"],
                                  synonyms=["<b>bold</b>"]))
        for markup in [s["gloss_html"], s["synonyms_html"]] + s["examples_html"]:
            self.assertNotIn("<img", markup)
            self.assertNotIn("<script", markup)

    def test_the_panel_renders_tags_html_not_tags(self):
        from helpers import ROOT
        src = (ROOT / "ObResults.qml").read_text(encoding="utf-8")
        self.assertIn("modelData.tags_html", src)
        self.assertNotIn("modelData.tags.join", src)

    def test_the_link_element_drops_unknown_tags(self):
        """ObLinkText keeps a tag allowlist as a second lock."""
        from helpers import ROOT
        src = (ROOT / "ObLinkText.qml").read_text(encoding="utf-8")
        self.assertIn("allowedTags", src)
        self.assertIn("function safe(", src)
        self.assertIn("root.safe(markup)", src)


class ExternalLinkTest(unittest.TestCase):
    def test_a_scraped_href_stays_on_oed(self):
        markup = ('<a href="http://evil.example/dictionary/haus">haus</a>'
                  '<a href="/dictionary/house_n">house</a>')
        urls = [e["url"] for e in OED.parse_search(markup)]
        for url in urls:
            self.assertTrue(url.startswith(WEB_ORIGIN), url)
        self.assertIn(WEB_ORIGIN + "/dictionary/house_n", urls)

    def test_the_panel_checks_the_scheme_before_opening(self):
        from helpers import ROOT
        src = (ROOT / "ObResults.qml").read_text(encoding="utf-8")
        self.assertIn("function openExternally(", src)
        self.assertIn("root.openExternally(cardRoot.url)", src)
        self.assertNotIn("Qt.openUrlExternally(cardRoot.url)", src)


class ClipboardTest(unittest.TestCase):
    """Copied text is scraped text, and a terminal is where it usually goes."""

    def test_escape_sequences_are_removed(self):
        self.assertEqual(clipboard.sanitize("safe\x1b]0;title\x07 text"), "safe]0;title text")
        self.assertEqual(clipboard.sanitize("a\x08\x00b\x7f"), "ab")

    def test_line_structure_survives(self):
        self.assertEqual(clipboard.sanitize("one\ntwo\tthree"), "one\ntwo\tthree")

    def test_copy_sanitizes(self):
        import os
        import tempfile
        with tempfile.NamedTemporaryFile("r", suffix=".txt", delete=False) as fh:
            path = fh.name
        os.environ["OMABABEL_FAKE_CLIPBOARD"] = path
        try:
            clipboard.copy("word\x1b[2Jgone")
            with open(path, encoding="utf-8") as fh:
                self.assertEqual(fh.read(), "word[2Jgone")
        finally:
            os.environ.pop("OMABABEL_FAKE_CLIPBOARD", None)
            os.unlink(path)


class DeepMarkupTest(unittest.TestCase):
    def test_a_deeply_nested_page_still_yields_its_text(self):
        # A recursive walk hit RecursionError here, which took the source's
        # whole answer with it.
        markup = "<div>" * 5000 + "Haus" + "</div>" * 5000
        self.assertEqual(htmlutil.parse(markup).get_text(), "Haus")

    def test_ordinary_markup_is_unchanged(self):
        doc = htmlutil.parse("<p>one <b>two</b></p><p>three</p>")
        self.assertEqual(doc.get_text(), "one two\nthree")
        self.assertEqual(doc.inline_text(), "one two three")


class SecretToolArgumentTest(TempEnv):
    def test_an_option_shaped_id_is_refused(self):
        for bad in ("--help", "-v", "a b", "../x", ""):
            with self.assertRaises(secrets.SecretError):
                secrets._attrs(bad)

    def test_an_ordinary_id_gets_an_option_terminator(self):
        self.assertEqual(secrets._attrs("mw"), ["--", "service", "omababel", "id", "mw"])


if __name__ == "__main__":
    unittest.main()
