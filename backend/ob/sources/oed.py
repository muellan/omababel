"""Oxford English Dictionary.

The OED is a subscription product.  Without credentials only the free
search-result snippets on oed.com are available, so this source ships
**disabled** by default.  With an OED Researcher API credential
(``app_id:app_key``) the official API is used instead.
"""

from __future__ import annotations

import re
from typing import List

from .. import http, htmlutil
from .. import results as R
from .base import Source, SourceError, register

SEARCH_URL = "https://www.oed.com/search/dictionary/?scope=Entries&q={word}"
API_WORDS = "https://oed-researcher-api.oxfordlanguages.com/oed/api/v0.2/words/?lemma={word}&limit=20"
API_SENSES = "https://oed-researcher-api.oxfordlanguages.com/oed/api/v0.2/word/{id}/senses/?limit=50"


@register
class OED(Source):
    driver = "oed"
    label = "Oxford English Dictionary"
    kind = "remote"
    types = ("dictionary",)
    description = "OED entries. Free access only yields search snippets; enter an OED Researcher API credential as 'app_id:app_key' for full senses."
    default_url = SEARCH_URL
    supports_key = True
    key_hint = "OED Researcher API 'app_id:app_key' (optional)"
    languages = ("en",)
    order = 12

    def lookup(self, word: str, lang: str) -> dict:
        word = word.strip()
        url = http.fill_template(SEARCH_URL, word=word)
        if self.api_key:
            return {"entries": self._api(word), "url": url}
        template = self.url if "{word}" in self.url else SEARCH_URL
        try:
            markup = http.fetch(http.fill_template(template, word=word)).text
        except http.FetchError as e:
            raise SourceError(f"OED: {e}")
        return {"entries": self.parse_search(markup, word, url), "url": url}

    # ---------------------------------------------------------------- api
    def _headers(self) -> dict:
        if ":" not in self.api_key:
            raise SourceError("OED API credential must be 'app_id:app_key'")
        app_id, app_key = self.api_key.split(":", 1)
        return {"app_id": app_id.strip(), "app_key": app_key.strip(), "Accept": "application/json"}

    def _api(self, word: str) -> List[dict]:
        try:
            data = http.fetch(http.fill_template(API_WORDS, word=word), headers=self._headers()).json()
        except http.FetchError as e:
            if e.status in (401, 403):
                raise SourceError("OED API: credential rejected")
            raise SourceError(f"OED API: {e}")
        except ValueError:
            raise SourceError("OED API: invalid JSON")
        entries: List[dict] = []
        for item in (data.get("data") or [])[:10] if isinstance(data, dict) else []:
            if not isinstance(item, dict):
                continue
            lemma = item.get("lemma", word)
            pos = ", ".join(item.get("parts_of_speech") or [])
            senses: List[dict] = []
            wid = item.get("id")
            if wid:
                try:
                    sd = http.fetch(API_SENSES.replace("{id}", http.quote(str(wid))), headers=self._headers()).json()
                    for s in (sd.get("data") or []):
                        d = s.get("definition")
                        if d:
                            senses.append(R.sense(d, label=str(s.get("sense_number") or "")))
                except (http.FetchError, ValueError):
                    pass
            if not senses and item.get("definition"):
                senses.append(R.sense(item["definition"]))
            extra = {}
            if item.get("etymology_summary"):
                extra["Etymology"] = item["etymology_summary"]
            dr = item.get("daterange") or {}
            if isinstance(dr, dict) and dr.get("start"):
                extra["First use"] = str(dr.get("start"))
            if senses:
                entries.append(R.entry(lemma, pos=pos, senses=senses, lang="en", extra=extra))
        return entries

    # ------------------------------------------------------------- scrape
    @staticmethod
    def parse_search(markup: str, word: str = "", url: str = "") -> List[dict]:
        doc = htmlutil.parse(markup)
        entries: List[dict] = []
        seen = set()
        for a in doc.find_all("a", pred=lambda n: re.search(r"/dictionary/[^/?#\"]+", n.get("href", "")) is not None):
            href = a.get("href")
            key = href.split("?")[0]
            if key in seen:
                continue
            title = a.inline_text()
            if not title or len(title) > 80:
                continue
            seen.add(key)
            container = a.closest(cls="resultsSetItem") or a.closest("li") or a.closest("article") or a.parent
            snippet = ""
            if container is not None:
                text = container.get_text()
                snippet = text.replace(title, "", 1).strip()
                snippet = re.sub(r"\s+", " ", snippet)[:500]
            m = re.match(r"^(.+),\s*([^,]+)$", title)
            head, pos = (m.group(1), m.group(2)) if m else (title, "")
            senses = [R.sense(snippet)] if snippet else []
            full = href if href.startswith("http") else "https://www.oed.com" + href
            entries.append(R.entry(head, pos=pos, senses=senses, lang="en", url=full))
            if len(entries) >= 8:
                break
        return entries
