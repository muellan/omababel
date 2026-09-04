"""The AI driver: CLI transport, API transport, and the reply parsing."""

import json
import os
import stat
import tempfile
import unittest
from pathlib import Path

from helpers import FakeResponse, TempEnv, fake_fetch

from ob import http
from ob import sources as S
from ob.sources import ai
from ob.sources.base import SourceError


def stub_cli(body: str, rc: int = 0):
    """A script that prints `body` no matter what it is asked."""
    d = Path(tempfile.mkdtemp(prefix="omababel-cli-"))
    script = d / "fake-ai"
    script.write_text("#!/bin/sh\ncat > /dev/null\n"
                      + "".join(f"printf '%s\\n' {json.dumps(line)}\n" for line in body.split("\n"))
                      + f"exit {rc}\n", encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    os.environ["PATH"] = str(d) + os.pathsep + os.environ["PATH"]
    return script


class ParseJsonTest(unittest.TestCase):
    def test_plain_fenced_and_chatty_replies(self):
        self.assertEqual(ai.parse_json('{"a": 1}'), {"a": 1})
        self.assertEqual(ai.parse_json('```json\n{"a": 1}\n```'), {"a": 1})
        self.assertEqual(ai.parse_json('Sure! Here you go:\n{"a": {"b": 2}}\nHope that helps.'),
                         {"a": {"b": 2}})
        # braces inside strings must not truncate the object
        self.assertEqual(ai.parse_json('{"a": "} not the end {", "b": 3}'),
                         {"a": "} not the end {", "b": 3})
        # a CLI banner before the answer
        self.assertEqual(ai.parse_json('Loading model…\n[info] ready\n{"ok": true}'), {"ok": True})
        self.assertIsNone(ai.parse_json("no json at all"))
        self.assertIsNone(ai.parse_json(""))
        self.assertIsNone(ai.parse_json("[1, 2]"))          # an array is not a reply


class AiCliTest(unittest.TestCase):
    def setUp(self):
        self._path = os.environ["PATH"]
        self._offline = os.environ.pop("OMABABEL_OFFLINE", None)

    def tearDown(self):
        os.environ["PATH"] = self._path
        if self._offline is not None:
            os.environ["OMABABEL_OFFLINE"] = self._offline

    def source(self, type="dictionary", **kw):
        row = {"id": "ai", "name": "AI", "type": type, "driver": "ai", "service": "claude",
               "transport": "cli", "command": "fake-ai"}
        row.update(kw)
        return S.build(row)

    def test_lookup_returns_one_succinct_explanation(self):
        stub_cli('{"explanation": "A building for living in.", "pos": "noun", '
                 '"example": "The house is old."}')
        res = self.source().lookup("house", "en")
        self.assertEqual(len(res["entries"]), 1)
        entry = res["entries"][0]
        self.assertEqual(entry["headword"], "house")
        self.assertEqual(entry["pos"], "noun")
        self.assertEqual(len(entry["senses"]), 1)
        self.assertEqual(entry["senses"][0]["gloss"], "A building for living in.")
        self.assertEqual(entry["senses"][0]["examples"], ["The house is old."])

    def test_thesaurus_groups_by_meaning(self):
        stub_cli(json.dumps({"groups": [
            {"meaning": "a place to live", "pos": "noun",
             "synonyms": ["home", "dwelling"], "antonyms": []},
            {"meaning": "to give shelter", "pos": "verb",
             "synonyms": ["lodge"], "antonyms": ["evict"]}]}))
        res = self.source(type="thesaurus").thesaurus("house", "en")
        self.assertEqual([(g["label"], g["pos"], g["synonyms"], g["antonyms"]) for g in res["groups"]],
                         [("a place to live", "noun", ["home", "dwelling"], []),
                          ("to give shelter", "verb", ["lodge"], ["evict"])])
        # the flat lists are derived from the groups
        self.assertEqual(res["synonyms"], ["home", "dwelling", "lodge"])
        self.assertEqual(res["antonyms"], ["evict"])

    def test_translation_keeps_the_meaning_and_the_alternatives(self):
        stub_cli(json.dumps({"translation": "Wie geht es dir?",
                             "alternatives": ["Wie geht's?", ""], "note": "informal"}))
        res = self.source(type="translator").translate("How are you?", "en", "de")
        self.assertEqual(res["mode"], "text")
        self.assertEqual(res["text"], "Wie geht es dir?")
        self.assertEqual(res["alternatives"], ["Wie geht's?", "informal"])

    def test_a_missing_cli_says_what_to_do(self):
        src = self.source(command="definitely-not-installed-42")
        with self.assertRaises(SourceError) as ctx:
            src.lookup("house", "en")
        self.assertIn("not installed", str(ctx.exception))

    def test_a_failing_or_unparsable_cli_is_reported(self):
        stub_cli("boom", rc=3)
        with self.assertRaises(SourceError):
            self.source().lookup("house", "en")
        stub_cli("I'd rather not answer in JSON.")
        with self.assertRaises(SourceError) as ctx:
            self.source().lookup("house", "en")
        self.assertIn("not JSON", str(ctx.exception))


class AiApiTest(TempEnv):
    """The API transport. TempEnv gives each test its own model cache."""

    def row(self, service, **kw):
        row = {"id": "ai", "name": "AI", "type": "dictionary", "driver": "ai",
               "service": service, "transport": "api", "api_key": "KEY"}
        row.update(kw)
        return row

    def responder(self, chat_payload, models=None):
        """Answer the model listing and the chat call from one handler."""
        def handle(url, **kw):
            if url.rstrip("/").endswith("/models"):
                return FakeResponse(json.dumps(models if models is not None else {"data": []}))
            return FakeResponse(json.dumps(chat_payload))
        return handle

    def test_claude_uses_the_messages_api(self):
        payload = {"content": [{"type": "text", "text": '{"explanation": "x", "pos": "", "example": ""}'}]}
        models = {"data": [{"id": "claude-opus-5"}, {"id": "claude-haiku-4-5-20251001"}]}
        with fake_fetch(self.responder(payload, models)) as calls:
            res = S.build(self.row("claude")).lookup("house", "en")
        listing, chat = calls[0], calls[-1]
        self.assertEqual(listing[0], "https://api.anthropic.com/v1/models")
        self.assertEqual(listing[1]["headers"]["X-Api-Key"], "KEY")
        self.assertEqual(chat[0], "https://api.anthropic.com/v1/messages")
        self.assertEqual(chat[1]["headers"]["X-Api-Key"], "KEY")
        self.assertEqual(chat[1]["headers"]["anthropic-version"], "2023-06-01")
        self.assertEqual(chat[1]["json_body"]["max_tokens"], ai.MAX_TOKENS)
        self.assertEqual(chat[1]["json_body"]["messages"][0]["role"], "user")
        # the cheapest model the key may use, not a hardcoded one
        self.assertEqual(chat[1]["json_body"]["model"], "claude-haiku-4-5-20251001")
        self.assertEqual(res["entries"][0]["senses"][0]["gloss"], "x")

    def test_a_configured_model_is_used_as_is_and_asks_for_no_listing(self):
        payload = {"content": [{"type": "text", "text": '{"explanation": "x"}'}]}
        with fake_fetch(self.responder(payload)) as calls:
            S.build(self.row("claude", model="claude-sonnet-5")).lookup("house", "en")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1]["json_body"]["model"], "claude-sonnet-5")

    def test_a_retired_model_is_rediscovered_once(self):
        """A model id that answers 404 must not be a dead end."""
        payload = {"content": [{"type": "text", "text": '{"explanation": "ok"}'}]}
        state = {"listings": 0}

        def handle(url, **kw):
            if url.endswith("/models"):
                state["listings"] += 1
                if state["listings"] == 1:
                    return FakeResponse(json.dumps({"data": [{"id": "claude-haiku-old"}]}))
                return FakeResponse(json.dumps({"data": [{"id": "claude-haiku-new"}]}))
            if kw["json_body"]["model"] == "claude-haiku-old":
                raise http.FetchError("HTTP 404", status=404, url=url)
            return FakeResponse(json.dumps(payload))

        with fake_fetch(handle) as calls:
            res = S.build(self.row("claude")).lookup("house", "en")
        self.assertEqual(res["entries"][0]["senses"][0]["gloss"], "ok")
        self.assertEqual(calls[-1][1]["json_body"]["model"], "claude-haiku-new")

    def test_a_404_that_survives_the_retry_names_the_usable_models(self):
        def handle(url, **kw):
            if url.endswith("/models"):
                return FakeResponse(json.dumps({"data": [{"id": "claude-sonnet-5"}]}))
            raise http.FetchError("HTTP 404", status=404, url=url)
        with fake_fetch(handle):
            with self.assertRaises(SourceError) as ctx:
                S.build(self.row("claude", model="gone-model")).lookup("house", "en")
        self.assertIn("does not know the model 'gone-model'", str(ctx.exception))
        self.assertIn("claude-sonnet-5", str(ctx.exception))

    def test_openai_compatible_services(self):
        payload = {"choices": [{"message": {"content": '{"explanation": "y"}'}}]}
        for service, host in (("chatgpt", "api.openai.com"), ("grok", "api.x.ai")):
            with fake_fetch(self.responder(payload)) as calls:
                res = S.build(self.row(service, model="custom-model")).lookup("house", "en")
            url, kw = calls[0]
            self.assertIn(host, url)
            self.assertEqual(kw["headers"]["Authorization"], "Bearer KEY")
            self.assertEqual(kw["json_body"]["model"], "custom-model")
            self.assertEqual(res["entries"][0]["senses"][0]["gloss"], "y")

    def test_gemini_uses_its_own_shape(self):
        payload = {"candidates": [{"content": {"parts": [{"text": '{"explanation": "z"}'}]}}]}
        models = {"models": [{"name": "models/gemini-2.5-pro", "supportedGenerationMethods": ["generateContent"]},
                             {"name": "models/gemini-2.5-flash", "supportedGenerationMethods": ["generateContent"]},
                             {"name": "models/embedding-001", "supportedGenerationMethods": ["embedContent"]}]}
        with fake_fetch(self.responder(payload, models)) as calls:
            res = S.build(self.row("gemini")).lookup("house", "en")
        url, kw = calls[-1]
        self.assertIn("gemini-2.5-flash:generateContent", url)
        self.assertEqual(kw["headers"]["x-goog-api-key"], "KEY")
        self.assertEqual(res["entries"][0]["senses"][0]["gloss"], "z")

    def test_the_model_listing_is_cached(self):
        payload = {"content": [{"type": "text", "text": '{"explanation": "x"}'}]}
        models = {"data": [{"id": "claude-haiku-4-5"}]}
        with fake_fetch(self.responder(payload, models)) as calls:
            S.build(self.row("claude")).lookup("house", "en")
            self.assertEqual(sum(1 for c in calls if c[0].endswith("/models")), 1)
            S.build(self.row("claude")).lookup("home", "en")
            self.assertEqual(sum(1 for c in calls if c[0].endswith("/models")), 1)
        ai.forget_models("claude")
        with fake_fetch(self.responder(payload, models)) as calls:
            S.build(self.row("claude")).lookup("house", "en")
            self.assertEqual(sum(1 for c in calls if c[0].endswith("/models")), 1)

    def test_an_unreadable_listing_falls_back_to_the_static_default(self):
        payload = {"content": [{"type": "text", "text": '{"explanation": "x"}'}]}

        def handle(url, **kw):
            if url.endswith("/models"):
                raise http.FetchError("HTTP 500", status=500, url=url)
            return FakeResponse(json.dumps(payload))

        with fake_fetch(handle) as calls:
            S.build(self.row("claude")).lookup("house", "en")
        self.assertEqual(calls[-1][1]["json_body"]["model"], ai.SERVICES["claude"][3])

    def test_a_rejected_key_and_a_missing_key_are_explained(self):
        def deny(url, **kw):
            raise http.FetchError("HTTP 401", status=401, url=url)
        with fake_fetch(deny):
            with self.assertRaises(SourceError) as ctx:
                S.build(self.row("claude")).lookup("house", "en")
        self.assertIn("rejected the key", str(ctx.exception))
        with self.assertRaises(SourceError) as ctx:
            S.build(self.row("claude", api_key="")).lookup("house", "en")
        self.assertIn("needs a key", str(ctx.exception))


class ModelPickTest(unittest.TestCase):
    def test_ids_are_read_from_every_listing_shape(self):
        self.assertEqual(ai._model_ids({"data": [{"id": "a"}, {"id": "text-embedding-3"}]}), ["a"])
        self.assertEqual(ai._model_ids({"models": [{"name": "models/b"}]}), ["b"])
        self.assertEqual(ai._model_ids({"data": ["c"]}), ["c"])
        self.assertEqual(ai._model_ids("nonsense"), [])

    def test_the_small_model_of_a_family_wins(self):
        self.assertEqual(ai.pick_model("claude", ["claude-opus-5", "claude-sonnet-5", "claude-haiku-4-5"]),
                         "claude-haiku-4-5")
        # a plain id beats a dated snapshot of the same family
        self.assertEqual(ai.pick_model("claude", ["claude-haiku-4-5-20251001", "claude-haiku-4-5"]),
                         "claude-haiku-4-5")
        self.assertEqual(ai.pick_model("chatgpt", ["gpt-5", "gpt-5-mini"]), "gpt-5-mini")
        self.assertEqual(ai.pick_model("gemini", ["gemini-2.5-pro", "gemini-2.5-flash"]), "gemini-2.5-flash")
        self.assertEqual(ai.pick_model("muse", ["only-one"]), "only-one")
        self.assertEqual(ai.pick_model("claude", []), "")


class AiConfigTest(unittest.TestCase):
    def test_defaults_are_the_free_signed_in_cli(self):
        src = S.build({"id": "ai", "name": "AI", "type": "dictionary", "driver": "ai"})
        self.assertEqual(src.service, "claude")
        self.assertEqual(src.transport, "cli")           # no API key, no billing
        self.assertEqual(src.command, "claude -p")
        self.assertEqual(src.describe()["model"], "")   # the CLI picks its own
        # an AI source serves every language, in every mode
        self.assertEqual(src.effective_languages(), [])
        for mode in ("lookup", "thesaurus", "translate"):
            probe = S.build({"id": "ai", "name": "AI", "driver": "ai",
                             "type": {"lookup": "dictionary", "thesaurus": "thesaurus",
                                      "translate": "translator"}[mode]})
            self.assertTrue(probe.supports(mode, "sv", "ja"))

    def test_the_url_field_only_overrides_the_api_endpoint(self):
        cli = S.build({"id": "ai", "name": "AI", "type": "dictionary", "driver": "ai",
                       "url": "https://example.org/dictionary/{word}"})
        self.assertEqual(cli.endpoint, ai.SERVICES["claude"][2])
        api = S.build({"id": "ai", "name": "AI", "type": "dictionary", "driver": "ai",
                       "transport": "api", "url": "https://self.hosted/v1/chat/completions"})
        self.assertEqual(api.endpoint, "https://self.hosted/v1/chat/completions")

    def test_unknown_service_or_transport_falls_back(self):
        src = S.build({"id": "ai", "name": "AI", "type": "dictionary", "driver": "ai",
                       "service": "nope", "transport": "carrier-pigeon"})
        self.assertEqual((src.service, src.transport), ("claude", "cli"))

    def test_every_service_is_offered_to_the_ui(self):
        entry = [d for d in S.registry() if d["driver"] == "ai"][0]
        self.assertEqual([s["value"] for s in entry["services"]],
                         ["claude", "chatgpt", "grok", "gemini", "muse"])
        self.assertEqual(entry["types"], ["dictionary", "thesaurus", "translator"])


if __name__ == "__main__":
    unittest.main()
