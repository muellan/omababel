"""Google Translate.

Two access paths:

* **Cloud Translation API v2** when an API key is configured
  (``https://translation.googleapis.com/language/translate/v2``).
* Otherwise the unofficial ``translate_a/single`` endpoint the web client
  uses (``client=gtx``) – no key, but not an official interface and it may
  rate-limit.
"""

from __future__ import annotations

import json
from typing import List

from .. import http, languages
from .. import results as R
from .base import Source, SourceError, register

FREE_URL = "https://translate.googleapis.com/translate_a/single"
API_URL = "https://translation.googleapis.com/language/translate/v2"


@register
class GoogleTranslate(Source):
    driver = "google"
    label = "Google Translate"
    kind = "remote"
    types = ("translator",)
    description = "Full text translation (any language). Optional Cloud Translation API key; without it the public web endpoint is used."
    default_url = FREE_URL
    supports_key = True
    key_hint = "Cloud Translation API key (optional)"
    translation_modes = ("text", "word")
    order = 50

    def translate(self, text: str, src: str, dst: str) -> dict:
        text = text.strip()
        if not text:
            return R.translation(self.translation_mode)
        gsrc = languages.google_code(src) or src
        gdst = languages.google_code(dst) or dst
        if self.api_key:
            return self._translate_api(text, gsrc, gdst)
        return self._translate_free(text, gsrc, gdst)

    # ------------------------------------------------------------ official
    def _translate_api(self, text: str, gsrc: str, gdst: str) -> dict:
        try:
            resp = http.fetch(API_URL + "?key=" + http.quote(self.api_key),
                              data={"q": text, "source": gsrc, "target": gdst, "format": "text"},
                              method="POST")
            data = resp.json()
        except http.FetchError as e:
            raise SourceError(f"Google Translate API: {e}")
        except ValueError:
            raise SourceError("Google Translate API: invalid JSON")
        try:
            out = data["data"]["translations"][0]["translatedText"]
        except (KeyError, IndexError, TypeError):
            raise SourceError("Google Translate API: unexpected response")
        return R.translation(self.translation_mode, text=out,
                             url=self._web_url(text, gsrc, gdst))

    # ---------------------------------------------------------------- free
    def _translate_free(self, text: str, gsrc: str, gdst: str) -> dict:
        base = self.url if self.url.startswith("http") else FREE_URL
        query = (f"?client=gtx&sl={http.quote(gsrc)}&tl={http.quote(gdst)}&hl=en"
                 f"&dt=t&dt=bd&dt=at&ie=UTF-8&oe=UTF-8&q={http.quote(text)}")
        try:
            resp = http.fetch(base + query, headers={"Accept": "*/*"})
            data = json.loads(resp.text)
        except http.FetchError as e:
            raise SourceError(f"Google Translate: {e}")
        except ValueError:
            raise SourceError("Google Translate: invalid JSON (endpoint changed?)")
        result = self.parse_gtx(data)
        result["mode"] = self.translation_mode
        result["url"] = self._web_url(text, gsrc, gdst)
        return result

    @staticmethod
    def _web_url(text: str, gsrc: str, gdst: str) -> str:
        return f"https://translate.google.com/?sl={gsrc}&tl={gdst}&text={http.quote(text)}&op=translate"

    @staticmethod
    def parse_gtx(data) -> dict:
        """Parse the ``client=gtx`` array response into a translation dict."""
        if not isinstance(data, list) or not data:
            raise SourceError("Google Translate: unexpected response shape")
        text_parts: List[str] = []
        sentences = data[0] if isinstance(data[0], list) else []
        for chunk in sentences:
            if isinstance(chunk, list) and chunk and isinstance(chunk[0], str):
                text_parts.append(chunk[0])
        translated = "".join(text_parts).strip()
        pairs: List[dict] = []
        dictionary = data[1] if len(data) > 1 and isinstance(data[1], list) else []
        for pos_block in dictionary:
            if not isinstance(pos_block, list) or len(pos_block) < 2:
                continue
            pos = pos_block[0] if isinstance(pos_block[0], str) else ""
            detailed = pos_block[2] if len(pos_block) > 2 and isinstance(pos_block[2], list) else []
            base_word = pos_block[3] if len(pos_block) > 3 and isinstance(pos_block[3], str) else ""
            if detailed:
                for item in detailed:
                    if isinstance(item, list) and item and isinstance(item[0], str):
                        back = item[1] if len(item) > 1 and isinstance(item[1], list) else []
                        pairs.append(R.pair(base_word, item[0], pos=pos,
                                            note=", ".join(str(b) for b in back[:4])))
            elif isinstance(pos_block[1], list):
                for w in pos_block[1]:
                    if isinstance(w, str):
                        pairs.append(R.pair(base_word, w, pos=pos))
        detected = data[2] if len(data) > 2 and isinstance(data[2], str) else ""
        alternatives: List[str] = []
        alts = data[5] if len(data) > 5 and isinstance(data[5], list) else []
        for block in alts:
            if isinstance(block, list) and len(block) > 2 and isinstance(block[2], list):
                for alt in block[2]:
                    if isinstance(alt, list) and alt and isinstance(alt[0], str):
                        alternatives.append(alt[0])
        alternatives = [a for a in R.dedupe(alternatives) if a != translated]
        return R.translation("text", pairs, text=translated, detected=detected,
                             alternatives=alternatives)
