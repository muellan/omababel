"""DeepL.

* With an API key: the official REST API (``api-free.deepl.com`` for keys
  ending in ``:fx``, ``api.deepl.com`` otherwise).
* Without a key: the JSON-RPC endpoint the deepl.com web app talks to
  (the same trick the DeepLX projects use).  Unofficial, rate limited,
  may break – but it lets the plugin work out of the box.
"""

from __future__ import annotations

import json
import random
import time
from typing import List

from .. import http, languages
from .. import results as R
from .base import Source, SourceError, register

API_FREE = "https://api-free.deepl.com/v2/translate"
API_PRO = "https://api.deepl.com/v2/translate"
WEB_RPC = "https://www2.deepl.com/jsonrpc"


@register
class DeepL(Source):
    driver = "deepl"
    label = "DeepL"
    kind = "remote"
    types = ("translator",)
    description = "Full text translation. Uses the official API when a key is set (free keys end in ':fx'), otherwise the web app's endpoint."
    default_url = "https://www.deepl.com/translator"
    supports_key = True
    key_hint = "DeepL API key (optional)"
    translation_modes = ("text", "word")
    languages = ("de", "en", "zh", "fr", "es", "pt", "ja", "it", "ru", "pl", "nl", "sv",
                 "da", "nb", "fi", "cs", "sk", "hu", "ro", "bg", "el", "tr", "uk", "ar",
                 "ko", "id", "lt", "lv", "et", "sl")
    order = 51

    def translate(self, text: str, src: str, dst: str) -> dict:
        text = text.strip()
        if not text:
            return R.translation(self.translation_mode)
        dsrc = languages.deepl_code(src)
        ddst = languages.deepl_code(dst)
        if not dsrc or not ddst:
            raise SourceError("DeepL does not support this language pair")
        if self.api_key:
            return self._api(text, dsrc, ddst)
        return self._web(text, dsrc, ddst)

    @staticmethod
    def _web_url(text: str, dsrc: str, ddst: str) -> str:
        return (f"https://www.deepl.com/translator#{dsrc.lower()}/{ddst.lower().split('-')[0]}/"
                f"{http.quote(text)}")

    # ------------------------------------------------------------ official
    def _api(self, text: str, dsrc: str, ddst: str) -> dict:
        endpoint = API_FREE if self.api_key.endswith(":fx") else API_PRO
        if self.url.startswith("http") and "/v2/translate" in self.url:
            endpoint = self.url
        try:
            resp = http.fetch(endpoint, method="POST",
                              data={"text": text, "source_lang": dsrc.split("-")[0],
                                    "target_lang": ddst},
                              headers={"Authorization": "DeepL-Auth-Key " + self.api_key,
                                       "Accept": "application/json"})
            data = resp.json()
        except http.FetchError as e:
            if e.status == 403:
                raise SourceError("DeepL API: invalid API key")
            if e.status == 456:
                raise SourceError("DeepL API: quota exceeded")
            raise SourceError(f"DeepL API: {e}")
        except ValueError:
            raise SourceError("DeepL API: invalid JSON")
        try:
            tr = data["translations"][0]
            out = tr["text"]
            detected = tr.get("detected_source_language", "")
        except (KeyError, IndexError, TypeError):
            raise SourceError("DeepL API: unexpected response")
        return R.translation(self.translation_mode, text=out, detected=detected.lower(),
                             url=self._web_url(text, dsrc, ddst))

    # ------------------------------------------------------------- web rpc
    @staticmethod
    def build_rpc(text: str, dsrc: str, ddst: str, rpc_id: int = 0, now_ms: int = 0) -> str:
        """Build the JSON-RPC body the web client sends (deterministic for tests)."""
        rpc_id = rpc_id or random.randint(8300000, 8399998) * 1000
        now_ms = now_ms or int(time.time() * 1000)
        i_count = text.count("i") + 1
        ts = now_ms - (now_ms % i_count) + i_count
        body = {
            "jsonrpc": "2.0",
            "method": "LMT_handle_jobs",
            "id": rpc_id,
            "params": {
                "jobs": [{
                    "kind": "default",
                    "sentences": [{"text": text, "id": 1, "prefix": ""}],
                    "raw_en_context_before": [],
                    "raw_en_context_after": [],
                    "preferred_num_beams": 4,
                }],
                "lang": {
                    "target_lang": ddst.split("-")[0].upper(),
                    "source_lang_user_selected": dsrc.split("-")[0].upper(),
                    "preference": {"weight": {}, "default": "default"},
                },
                "priority": 1,
                "commonJobParams": {"mode": "translate", "browserType": 1, "formality": None},
                "timestamp": ts,
            },
        }
        raw = json.dumps(body, ensure_ascii=False, separators=(",", ":"))
        # The web client's quirky spacing rule – the server checks it.
        if (rpc_id + 5) % 29 == 0 or (rpc_id + 3) % 13 == 0:
            raw = raw.replace('"method":"', '"method" : "', 1)
        else:
            raw = raw.replace('"method":"', '"method": "', 1)
        return raw

    def _web(self, text: str, dsrc: str, ddst: str) -> dict:
        body = self.build_rpc(text, dsrc, ddst)
        try:
            resp = http.fetch(WEB_RPC + "?method=LMT_handle_jobs", data=body, method="POST",
                              headers={"Content-Type": "application/json",
                                       "Accept": "*/*",
                                       "Origin": "https://www.deepl.com",
                                       "Referer": "https://www.deepl.com/",
                                       "x-app-os-name": "iOS",
                                       "x-app-os-version": "16.3.0",
                                       "x-app-device": "iPhone13,2",
                                       "x-app-build": "510265",
                                       "x-app-version": "2.9.1",
                                       "User-Agent": "DeepL-iOS/2.9.1 iOS 16.3.0 (iPhone13,2)"})
            data = resp.json()
        except http.FetchError as e:
            if e.status == 429:
                raise SourceError("DeepL web endpoint: rate limited (429) – add an API key or retry later")
            raise SourceError(f"DeepL web endpoint: {e}")
        except ValueError:
            raise SourceError("DeepL web endpoint: invalid JSON")
        result = self.parse_rpc(data)
        result["mode"] = self.translation_mode
        result["url"] = self._web_url(text, dsrc, ddst)
        return result

    @staticmethod
    def parse_rpc(data) -> dict:
        if not isinstance(data, dict):
            raise SourceError("DeepL web endpoint: unexpected response")
        if "error" in data:
            msg = data["error"].get("message") if isinstance(data["error"], dict) else str(data["error"])
            raise SourceError(f"DeepL web endpoint: {msg}")
        try:
            translations = data["result"]["translations"]
        except (KeyError, TypeError):
            raise SourceError("DeepL web endpoint: unexpected response")
        texts: List[str] = []
        alternatives: List[str] = []
        for tr in translations:
            beams = tr.get("beams") or []
            for i, beam in enumerate(beams):
                sentences = beam.get("sentences") or []
                joined = " ".join(s.get("text", "") for s in sentences).strip()
                if not joined:
                    continue
                if i == 0:
                    texts.append(joined)
                else:
                    alternatives.append(joined)
        detected = ""
        try:
            detected = data["result"].get("source_lang", "").lower()
        except AttributeError:
            pass
        return R.translation("text", text=" ".join(texts), detected=detected,
                             alternatives=R.dedupe(alternatives))
