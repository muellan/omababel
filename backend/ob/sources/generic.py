"""Generic remote source for user-added URLs.

The URL is a template with ``{word}`` (and ``{from}``/``{to}`` for
translators).  JSON responses are flattened; HTML pages are reduced to
their main readable text.  It will never be as tidy as a dedicated
driver, but it lets people plug in any web dictionary without writing
code.
"""

from __future__ import annotations

import json
import re
from typing import List

from .. import http, htmlutil, impersonate
from .. import results as R
from .base import Source, SourceError, register

MAX_CHARS = 4000


def _flatten_json(obj, depth: int = 0) -> List[str]:
    lines: List[str] = []
    indent = "  " * depth
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, (dict, list)):
                lines.append(f"{indent}{k}:")
                lines.extend(_flatten_json(v, depth + 1))
            else:
                lines.append(f"{indent}{k}: {v}")
    elif isinstance(obj, list):
        for v in obj:
            if isinstance(v, (dict, list)):
                lines.extend(_flatten_json(v, depth + 1))
            else:
                lines.append(f"{indent}- {v}")
    else:
        lines.append(f"{indent}{obj}")
    return lines


def _collect_words(obj, key: str) -> List[str]:
    found: List[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == key and isinstance(v, list):
                for item in v:
                    if isinstance(item, str):
                        found.append(item)
                    elif isinstance(item, dict):
                        for kk in ("term", "word", "text", "name"):
                            if isinstance(item.get(kk), str):
                                found.append(item[kk])
                                break
            else:
                found.extend(_collect_words(v, key))
    elif isinstance(obj, list):
        for v in obj:
            found.extend(_collect_words(v, key))
    return found


def main_text(markup: str) -> str:
    doc = htmlutil.parse(markup)
    for tag in ("nav", "header", "footer", "aside", "script", "style", "noscript", "form"):
        for n in doc.find_all(tag):
            if n.parent is not None:
                n.parent.children.remove(n)
    body = doc.find("main") or doc.find("article") or doc.find(id="content") or doc.find("body") or doc
    text = body.get_text()
    return text[:MAX_CHARS]


@register
class Generic(Source):
    driver = "generic"
    label = "Custom URL"
    kind = "remote"
    types = ("dictionary", "thesaurus", "translator")
    description = "Any web page or JSON API. Use {word} in the URL (plus {from} and {to} for translators); the page's readable text is shown."
    default_url = "https://example.org/dictionary/{word}"
    supports_key = True
    key_hint = "Sent as 'Authorization: Bearer <key>' and as {key} in the URL"
    translation_modes = ("text", "word")
    order = 90

    def _get(self, word: str, src: str = "", dst: str = ""):
        if "{word}" not in self.url and "{q}" not in self.url:
            raise SourceError(f"{self.name}: URL must contain {{word}}")
        # The key goes into the URL or into an Authorization header; either
        # way it must not travel in the clear.
        if self.api_key and not self.url.lower().startswith("https://"):
            raise SourceError(f"{self.name}: a source with an API key needs an https URL")
        url = http.fill_template(self.url.replace("{q}", "{word}"), word=word, **{"from": src, "to": dst})
        url = url.replace("{key}", http.quote(self.api_key))
        headers = {}
        if self.api_key and "{key}" not in self.url:
            headers["Authorization"] = "Bearer " + self.api_key
        # What the caller gets back is what ends up in the result, and the
        # panel offers to open it in a browser: the key stays in the request.
        shown = impersonate.redact_url(url)
        try:
            resp = http.fetch(url, headers=headers)
        except http.FetchError as e:
            if e.status == 404:
                return shown, None
            raise SourceError(f"{self.name}: {e}")
        return shown, resp

    def lookup(self, word: str, lang: str) -> dict:
        url, resp = self._get(word.strip())
        if resp is None:
            return {"entries": [], "url": url}
        text, syn, ant = self.render(resp)
        senses = [R.sense(text)] if text else []
        if syn or ant:
            senses.append(R.sense("", synonyms=syn, antonyms=ant))
        return {"entries": [R.entry(word, senses=senses, lang=lang, url=url)] if senses else [],
                "url": url}

    def thesaurus(self, word: str, lang: str) -> dict:
        url, resp = self._get(word.strip())
        if resp is None:
            return R.thesaurus([], [], url=url)
        _, syn, ant = self.render(resp)
        return R.thesaurus(syn, ant, url=url)

    def translate(self, text: str, src: str, dst: str) -> dict:
        url, resp = self._get(text.strip(), src, dst)
        if resp is None:
            return R.translation(self.translation_mode, url=url)
        body, _, _ = self.render(resp)
        return R.translation(self.translation_mode, text=body, url=url)

    @staticmethod
    def render(resp):
        ctype = resp.headers.get("content-type", "")
        text = resp.text
        stripped = text.lstrip()
        if "json" in ctype or stripped[:1] in "[{":
            try:
                data = json.loads(text)
                syn = R.dedupe(_collect_words(data, "synonyms"))
                ant = R.dedupe(_collect_words(data, "antonyms"))
                flat = "\n".join(_flatten_json(data))
                return flat[:MAX_CHARS], syn, ant
            except ValueError:
                pass
        if "<" in stripped[:200]:
            return main_text(text), [], []
        return re.sub(r"\n{3,}", "\n\n", text)[:MAX_CHARS], [], []
