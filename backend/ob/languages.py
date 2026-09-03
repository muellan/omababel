"""Language catalogue.

Every language is keyed by its ISO 639-1 code.  The other fields are the
identifiers the individual data sources want:

``iso3``   ISO 639-3 (FreeDict names its dictionaries ``deu-eng`` etc.)
``kaikki`` The English name kaikki.org uses in its per-language dumps and
           in the ``lang`` field of every entry.
``leo``    The two letter code LEO uses inside its language-pair ids
           (LEO only offers ``xx <-> de`` pairs; ``ch`` is Chinese there).
``deepl``  DeepL API code (``EN-US``/``EN-GB`` are accepted as targets, ``EN``
           as source).
``google`` Google Translate code.
"""

from __future__ import annotations

from typing import Dict, List, Optional

# code, iso3, english name, native name, kaikki name, leo, deepl, google
_TABLE = [
    ("de", "deu", "German", "Deutsch", "German", "de", "DE", "de"),
    ("en", "eng", "English", "English", "English", "en", "EN", "en"),
    ("zh", "zho", "Chinese (Mandarin)", "中文", "Chinese", "ch", "ZH", "zh-CN"),
    ("fr", "fra", "French", "Français", "French", "fr", "FR", "fr"),
    ("es", "spa", "Spanish", "Español", "Spanish", "es", "ES", "es"),
    ("pt", "por", "Portuguese", "Português", "Portuguese", "pt", "PT-PT", "pt"),
    ("ja", "jpn", "Japanese", "日本語", "Japanese", None, "JA", "ja"),
    ("it", "ita", "Italian", "Italiano", "Italian", "it", "IT", "it"),
    ("ru", "rus", "Russian", "Русский", "Russian", "ru", "RU", "ru"),
    ("pl", "pol", "Polish", "Polski", "Polish", "pl", "PL", "pl"),
    ("nl", "nld", "Dutch", "Nederlands", "Dutch", None, "NL", "nl"),
    ("sv", "swe", "Swedish", "Svenska", "Swedish", None, "SV", "sv"),
    ("da", "dan", "Danish", "Dansk", "Danish", None, "DA", "da"),
    ("nb", "nob", "Norwegian (Bokmål)", "Norsk bokmål", "Norwegian Bokmål", None, "NB", "no"),
    ("fi", "fin", "Finnish", "Suomi", "Finnish", None, "FI", "fi"),
    ("cs", "ces", "Czech", "Čeština", "Czech", None, "CS", "cs"),
    ("sk", "slk", "Slovak", "Slovenčina", "Slovak", None, "SK", "sk"),
    ("hu", "hun", "Hungarian", "Magyar", "Hungarian", None, "HU", "hu"),
    ("ro", "ron", "Romanian", "Română", "Romanian", None, "RO", "ro"),
    ("bg", "bul", "Bulgarian", "Български", "Bulgarian", None, "BG", "bg"),
    ("el", "ell", "Greek", "Ελληνικά", "Greek", None, "EL", "el"),
    ("tr", "tur", "Turkish", "Türkçe", "Turkish", None, "TR", "tr"),
    ("uk", "ukr", "Ukrainian", "Українська", "Ukrainian", None, "UK", "uk"),
    ("ar", "ara", "Arabic", "العربية", "Arabic", None, "AR", "ar"),
    ("he", "heb", "Hebrew", "עברית", "Hebrew", None, "HE", "iw"),
    ("hi", "hin", "Hindi", "हिन्दी", "Hindi", None, None, "hi"),
    ("ko", "kor", "Korean", "한국어", "Korean", None, "KO", "ko"),
    ("vi", "vie", "Vietnamese", "Tiếng Việt", "Vietnamese", None, "VI", "vi"),
    ("th", "tha", "Thai", "ไทย", "Thai", None, "TH", "th"),
    ("id", "ind", "Indonesian", "Bahasa Indonesia", "Indonesian", None, "ID", "id"),
    ("ms", "msa", "Malay", "Bahasa Melayu", "Malay", None, None, "ms"),
    ("ca", "cat", "Catalan", "Català", "Catalan", None, None, "ca"),
    ("la", "lat", "Latin", "Latina", "Latin", None, None, "la"),
    ("eo", "epo", "Esperanto", "Esperanto", "Esperanto", None, None, "eo"),
    ("ga", "gle", "Irish", "Gaeilge", "Irish", None, None, "ga"),
    ("is", "isl", "Icelandic", "Íslenska", "Icelandic", None, None, "is"),
    ("hr", "hrv", "Croatian", "Hrvatski", "Croatian", None, None, "hr"),
    ("sr", "srp", "Serbian", "Српски", "Serbian", None, None, "sr"),
    ("sl", "slv", "Slovene", "Slovenščina", "Slovene", None, "SL", "sl"),
    ("lt", "lit", "Lithuanian", "Lietuvių", "Lithuanian", None, "LT", "lt"),
    ("lv", "lav", "Latvian", "Latviešu", "Latvian", None, "LV", "lv"),
    ("et", "est", "Estonian", "Eesti", "Estonian", None, "ET", "et"),
    ("fa", "fas", "Persian", "فارس", "Persian", None, None, "fa"),
    ("sw", "swa", "Swahili", "Kiswahili", "Swahili", None, None, "sw"),
]

FIELDS = ("code", "iso3", "name", "native", "kaikki", "leo", "deepl", "google")

LANGUAGES: Dict[str, dict] = {
    row[0]: dict(zip(FIELDS, row)) for row in _TABLE
}

DEFAULT_LANGUAGES = ["de", "en", "zh", "fr", "es", "pt", "ja"]

_ISO3_INDEX = {v["iso3"]: k for k, v in LANGUAGES.items()}
_KAIKKI_INDEX = {v["kaikki"].lower(): k for k, v in LANGUAGES.items()}
_NAME_INDEX = {v["name"].lower(): k for k, v in LANGUAGES.items()}


def get(code: str) -> Optional[dict]:
    return LANGUAGES.get(normalize(code) or "")


def normalize(code: Optional[str]) -> Optional[str]:
    """Map any of the known identifiers of a language to its 639-1 code."""
    if not code:
        return None
    c = str(code).strip()
    low = c.lower()
    if low in LANGUAGES:
        return low
    base = low.split("-")[0].split("_")[0]
    if base in LANGUAGES:
        return base
    if low in _ISO3_INDEX:
        return _ISO3_INDEX[low]
    if low in _KAIKKI_INDEX:
        return _KAIKKI_INDEX[low]
    if low in _NAME_INDEX:
        return _NAME_INDEX[low]
    if low == "iw":
        return "he"
    if low in ("no", "nn", "nor", "nno"):
        return "nb"
    if low in ("zh-cn", "zh-tw", "zh-hans", "zh-hant", "cmn", "yue"):
        return "zh"
    return None


def name(code: str) -> str:
    info = get(code)
    return info["name"] if info else str(code)


def iso3(code: str) -> Optional[str]:
    info = get(code)
    return info["iso3"] if info else None


def kaikki_name(code: str) -> Optional[str]:
    info = get(code)
    return info["kaikki"] if info else None


def leo_code(code: str) -> Optional[str]:
    info = get(code)
    return info["leo"] if info else None


def deepl_code(code: str) -> Optional[str]:
    info = get(code)
    return info["deepl"] if info else None


def google_code(code: str) -> Optional[str]:
    info = get(code)
    return info["google"] if info else None


def options() -> List[dict]:
    """The list the language selectors show: English first, then alphabetical."""
    ordered = ["en"] + sorted((c for c in LANGUAGES if c != "en"), key=lambda c: LANGUAGES[c]["name"])
    return [
        {"value": c, "label": LANGUAGES[c]["name"], "native": LANGUAGES[c]["native"]}
        for c in ordered
    ]
