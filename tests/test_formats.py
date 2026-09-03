"""Importers for every supported local format + format detection."""

import unittest
from pathlib import Path

import helpers
from helpers import fixture

from ob import formats
from ob.formats import cedict, ecdict, kaikki, tei, unihan, dictd


class DetectTest(unittest.TestCase):
    def test_detect(self):
        cases = {
            "kaikki-sample.jsonl": "kaikki", "deu-eng.tei": "tei", "cedict-sample.u8": "cedict",
            "ecdict-sample.csv": "ecdict", "unihan-sample.txt": "unihan", "unihan-github-sample.txt": "unihan",
            "mini.tsv": "tsv", "mini-en.json": "json", "eng-deu-sample.index": "dictd",
        }
        for name, want in cases.items():
            self.assertEqual(formats.detect(fixture(name)), want, name)

    def test_detect_cedict_js(self):
        p = Path(helpers.tempfile.mkdtemp()) / "all.js"
        p.write_text('export default {"all":[["中國","中国","Zhong1 guo2","China",[],[]]],"variantLookup":{}}', encoding="utf-8")
        self.assertEqual(formats.detect(p), "cedict")
        entries = list(formats.iter_entries(p))
        self.assertEqual(entries[0]["word"], "中国")
        self.assertEqual(entries[0]["pron"], "Zhōng guó")

    def test_unknown(self):
        p = Path(helpers.tempfile.mkdtemp()) / "weird.bin"
        p.write_bytes(b"\x00\x01")
        self.assertIsNone(formats.detect(p))
        with self.assertRaises(ValueError):
            list(formats.iter_entries(p))


class KaikkiTest(unittest.TestCase):
    def test_import_all(self):
        entries = list(kaikki.iter_kaikki(fixture("kaikki-sample.jsonl")))
        words = [e["word"] for e in entries]
        self.assertEqual(words, ["Haus", "house", "casa", "broken"])  # nosense + bad line skipped
        haus = entries[0]
        self.assertEqual(haus["lang"], "de")
        self.assertEqual(haus["pron"], "/haʊ̯s/")
        self.assertEqual(haus["forms"], ["Häuser"])         # table-tags form dropped
        self.assertEqual(haus["senses"][0]["synonyms"], ["Gebäude", "Bau"])  # entry-level merged
        self.assertEqual(haus["senses"][0]["examples"], ["ein Haus bauen"])
        self.assertIn("etymology", haus["extra"])
        house = entries[1]
        self.assertEqual(house["translations"], {"de": ["Haus", "Gebäude"], "fr": ["maison"]})
        self.assertEqual(house["senses"][0]["antonyms"], ["office"])
        self.assertEqual(entries[3]["senses"][0]["gloss"], "fallback gloss")

    def test_filter_lang(self):
        entries = list(kaikki.iter_kaikki(fixture("kaikki-sample.jsonl"), lang="German"))
        self.assertEqual([e["word"] for e in entries], ["Haus"])


class TeiTest(unittest.TestCase):
    def test_import(self):
        entries = list(tei.iter_tei(fixture("deu-eng.tei")))
        self.assertEqual([e["word"] for e in entries], ["Haus", "groß"])  # empty entry dropped
        haus = entries[0]
        self.assertEqual((haus["lang"], haus["pron"]), ("de", "haʊs"))
        self.assertEqual(haus["pos"], "n, n")
        self.assertEqual(haus["translations"], {"en": ["house", "home", "building"]})
        self.assertEqual(haus["senses"][1]["tags"], ["arch."])
        self.assertEqual(haus["senses"][1]["examples"], ["Gebäude"])
        self.assertEqual(haus["senses"][0]["synonyms"], ["Gebäude"])
        self.assertIn("von großer Ausdehnung", entries[1]["senses"][0]["gloss"])

    def test_pair_from_name(self):
        self.assertEqual(tei.pair_from_name("freedict-deu-eng-1.9.src.tar.xz"), ("de", "en"))
        self.assertIsNone(tei.pair_from_name("nothing.tei"))


class DictdTest(unittest.TestCase):
    def test_import(self):
        entries = list(dictd.iter_dictd(fixture("eng-deu-sample.index")))
        self.assertEqual([e["word"] for e in entries], ["Hund", "Katze"])
        self.assertEqual(entries[0]["pos"], "n")
        self.assertEqual(entries[0]["translations"]["de"], ["dog", "hound"])
        self.assertEqual(entries[0]["lang"], "en")
        self.assertEqual(dictd.b64_to_int("BA"), 64)


class CedictTest(unittest.TestCase):
    def test_pinyin(self):
        self.assertEqual(cedict.pinyin_marks("Zhong1 guo2"), "Zhōng guó")
        self.assertEqual(cedict.pinyin_marks("nu:3 er2"), "nǚ ér")
        self.assertEqual(cedict.pinyin_marks("ma5 xiu1"), "ma xiū")
        self.assertEqual(cedict.pinyin_marks("lou2"), "lóu")

    def test_import(self):
        entries = list(cedict.iter_cedict(fixture("cedict-sample.u8")))
        self.assertEqual(len(entries), 4)
        zg = entries[0]
        self.assertEqual((zg["word"], zg["forms"], zg["pron"]), ("中国", ["中國"], "Zhōng guó"))
        self.assertEqual(zg["translations"]["en"], ["China"])
        self.assertEqual(entries[1]["senses"][0]["lang"], "en")
        self.assertEqual(entries[3]["word"], "女儿")


class EcdictTest(unittest.TestCase):
    def test_import(self):
        entries = list(ecdict.iter_ecdict(fixture("ecdict-sample.csv")))
        self.assertEqual(len(entries), 2)
        house = entries[0]
        self.assertEqual(house["pos"], "n., v.")
        self.assertEqual(house["forms"], ["houses", "housing", "housed"])
        self.assertEqual(house["senses"][0]["tags"], ["n."])
        self.assertEqual(house["senses"][0]["gloss"], "a dwelling that serves as living quarters for one or more families")
        self.assertEqual(house["translations"]["zh"][:3], ["房子", "住宅", "机构"])
        self.assertEqual(house["extra"]["collins"], "5")
        went = entries[1]
        self.assertEqual(went["senses"][0]["gloss"], "change location; move, travel, or proceed")
        self.assertEqual(went["senses"][0]["tags"], ["v."])


class UnihanTest(unittest.TestCase):
    def test_canonical(self):
        entries = {e["word"]: e for e in unihan.iter_unihan(fixture("unihan-sample.txt"))}
        self.assertEqual(set(entries), {"中", "国"})
        zhong = entries["中"]
        self.assertEqual(zhong["pron"], "zhōng")
        self.assertEqual(zhong["senses"][0]["gloss"], "central")
        self.assertEqual(zhong["extra"]["JapaneseOn"], "CHUU")
        self.assertEqual(entries["国"]["forms"], ["國"])
        self.assertEqual(entries["国"]["extra"]["TraditionalVariant"], "國")

    def test_github_layout(self):
        entries = list(unihan.iter_unihan(fixture("unihan-github-sample.txt")))
        self.assertEqual([e["word"] for e in entries], ["㐀", "中"])

    def test_directory(self):
        d = Path(helpers.tempfile.mkdtemp())
        (d / "kDefinition.txt").write_text("U+4E2D 中\tkDefinition\tcentral\n", encoding="utf-8")
        (d / "kMandarin.txt").write_text("U+4E2D\tkMandarin\tzhōng\n", encoding="utf-8")
        entries = list(unihan.iter_unihan(d))
        self.assertEqual(entries[0]["pron"], "zhōng")


class SimpleTest(unittest.TestCase):
    def test_tsv_and_json(self):
        tsv = list(formats.iter_entries(fixture("mini.tsv"), lang="de"))
        self.assertEqual([e["word"] for e in tsv], ["Katze", "Hund"])
        self.assertEqual(len(tsv[0]["senses"]), 2)
        self.assertEqual(tsv[0]["pos"], "Substantiv")
        js = list(formats.iter_entries(fixture("mini-en.json")))
        self.assertEqual(js[0]["senses"][0]["synonyms"], ["home", "dwelling", "residence"])
        self.assertEqual(js[0]["translations"]["de"], ["Haus", "Gebäude"])


if __name__ == "__main__":
    unittest.main()
