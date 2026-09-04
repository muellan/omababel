"""End-to-end: run backend/omababel.py as a subprocess (JSON protocol + CLI)."""

import json
import os
import shutil
import subprocess
import sys
import unittest

from helpers import BACKEND, TempEnv, fixture

SCRIPT = str(BACKEND / "omababel.py")


class ProtocolTest(TempEnv):
    def call(self, op, params=None, raw=None):
        payload = raw if raw is not None else json.dumps({"op": op, "params": params or {}})
        proc = subprocess.run([sys.executable, SCRIPT], input=payload + "\n", capture_output=True,
                              text=True, env=self.env(), timeout=60)
        lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
        self.assertTrue(lines, f"no output; stderr: {proc.stderr}")
        return json.loads(lines[-1]), lines[:-1], proc

    def cli(self, *args):
        proc = subprocess.run([sys.executable, SCRIPT, *args], capture_output=True, text=True,
                              env=self.env(), timeout=60)
        return proc

    def test_ping_state_and_errors(self):
        reply, _, _ = self.call("ping")
        self.assertTrue(reply["ok"])
        self.assertEqual(reply["data"]["pong"], True)
        reply, _, _ = self.call("state.get")
        self.assertTrue(reply["ok"])
        d = reply["data"]
        self.assertGreater(len(d["languages"]), 20)
        self.assertGreater(len(d["sources"]), 10)
        self.assertTrue(all(s["api_key"] == "" for s in d["sources"]))
        self.assertEqual(d["prefs"]["mode"], "lookup")
        self.assertEqual(d["history"], [])
        self.assertIn("drivers", d)
        # language coverage per mode drives the dimming in the selectors
        for mode in ("lookup", "thesaurus", "translate"):
            self.assertIn(mode, d["coverage"])
            self.assertIn("langs", d["coverage"][mode])
        self.assertIn("pairs", d["coverage"]["translate"])
        reply, _, _ = self.call("nope")
        self.assertFalse(reply["ok"])
        self.assertEqual(reply["error"]["code"], "unknown_op")
        reply, _, proc = self.call("", raw="{bad json")
        self.assertEqual(reply["error"]["code"], "bad_json")
        self.assertEqual(proc.returncode, 1)
        reply, _, _ = self.call("", raw="[1,2]")
        self.assertEqual(reply["error"]["code"], "bad_request")

    def test_search_history_and_copy(self):
        shutil.copy(fixture("mini-de.json"), self.data_dir / "mini-de.json")
        reply, _, _ = self.call("sources.save", {"source": {"name": "Mini DE", "type": "dictionary", "driver": "local",
                                                            "path": "mini-de.json", "languages": ["de"]}})
        self.assertTrue(reply["ok"], reply)
        self.assertEqual(reply["data"]["source"]["id"], "mini-de")
        reply, _, _ = self.call("search", {"mode": "lookup", "query": " Haus ", "lang": "de", "only": ["mini-de"]})
        self.assertTrue(reply["ok"], reply)
        res = reply["data"]
        self.assertEqual(res["results"][0]["entries"][0]["headword"], "Haus")
        self.assertIn("<a href=", res["results"][0]["entries"][0]["senses"][0]["gloss_html"])
        reply, _, _ = self.call("history.list")
        self.assertEqual([h["query"] for h in reply["data"]["history"]], ["Haus"])
        reply, _, _ = self.call("search", {"mode": "translate", "query": "Haus", "lang": "de"})
        self.assertEqual(reply["error"]["code"], "missing_language")
        reply, _, _ = self.call("search", {"mode": "lookup", "query": "  ", "lang": "de"})
        self.assertEqual(reply["error"]["code"], "empty_query")
        reply, _, _ = self.call("history.remove", {"query": "haus"})
        self.assertTrue(reply["data"]["removed"])
        reply, _, _ = self.call("copy", {"text": "Häuser"})
        self.assertTrue(reply["ok"], reply)
        self.assertEqual((self.tmp / "clipboard.txt").read_text(encoding="utf-8"), "Häuser")
        reply, _, _ = self.call("copy", {"text": ""})
        self.assertFalse(reply["ok"])

    def test_source_editing_ops(self):
        reply, _, _ = self.call("sources.enable", {"id": "duden", "enabled": False})
        self.assertTrue(reply["data"]["updated"])
        self.assertFalse([s for s in reply["data"]["sources"] if s["id"] == "duden"][0]["enabled"])
        reply, _, _ = self.call("sources.save", {"source": {"id": "deepl", "name": "DeepL", "type": "translator",
                                                            "driver": "deepl", "api_key": "k:fx"}})
        self.assertTrue(reply["data"]["source"]["has_key"])
        # saving again without a key keeps the stored one; clear_key drops it
        reply, _, _ = self.call("sources.save", {"source": {"id": "deepl", "name": "DeepL 2", "type": "translator", "driver": "deepl"}})
        self.assertTrue(reply["data"]["source"]["has_key"])
        self.assertEqual(reply["data"]["source"]["name"], "DeepL 2")
        reply, _, _ = self.call("sources.save", {"source": {"id": "deepl", "name": "DeepL", "type": "translator", "driver": "deepl"}, "clear_key": True})
        self.assertFalse(reply["data"]["source"]["has_key"])
        reply, _, _ = self.call("sources.save", {"source": {"name": "x", "driver": "bogus"}})
        self.assertEqual(reply["error"]["code"], "bad_driver")
        reply, _, _ = self.call("sources.move", {"id": "leo", "delta": -100})
        self.assertTrue(reply["data"]["moved"])
        self.assertEqual(reply["data"]["sources"][0]["id"], "leo")
        reply, _, _ = self.call("sources.delete", {"id": "leo"})
        self.assertTrue(reply["data"]["deleted"])
        reply, _, _ = self.call("sources.status")
        self.assertIn("cedict", reply["data"]["status"])
        self.assertFalse(reply["data"]["status"]["cedict"]["installed"])
        reply, _, _ = self.call("sources.reset")
        self.assertTrue(any(s["id"] == "leo" for s in reply["data"]["sources"]))
        reply, _, _ = self.call("prefs.set", {"values": {"mode": "thesaurus", "lang": "en"}})
        self.assertEqual(reply["data"]["prefs"]["mode"], "thesaurus")
        self.assertNotIn("history", reply["data"])
        for q in ("a", "b", "c"):
            self.call("search", {"mode": "lookup", "query": q, "lang": "en", "only": ["nothing"]})
        reply, _, _ = self.call("prefs.set", {"values": {"history_max": 2}})
        self.assertEqual(reply["data"]["history_max"], 2)
        self.assertEqual([h["query"] for h in reply["data"]["history"]], ["c", "b"])
        reply, _, _ = self.call("state.get")
        self.assertEqual(reply["data"]["history_max"], 2)
        self.assertEqual(len(reply["data"]["history"]), 2)

    def test_data_install_streams_progress(self):
        reply, progress, _ = self.call("data.install", {"id": "cedict", "path": str(fixture("cedict-sample.u8"))})
        self.assertTrue(reply["ok"], reply)
        self.assertEqual(reply["data"]["dataset"]["entries"], 4)
        events = [json.loads(p) for p in progress]
        self.assertTrue(all(e["event"] == "progress" for e in events))
        self.assertEqual(events[-1]["phase"], "done")
        reply, _, _ = self.call("data.list")
        cedict = [d for d in reply["data"]["datasets"] if d["id"] == "cedict"][0]
        self.assertTrue(cedict["installed"])
        reply, _, _ = self.call("sources.test", {"id": "cedict"})
        self.assertTrue(reply["ok"], reply)
        self.assertEqual(reply["data"]["results"][0]["source"]["id"], "cedict")
        self.assertEqual(reply["data"]["query"], "家")
        reply, _, _ = self.call("search", {"mode": "translate", "query": "China", "lang": "en", "lang2": "zh"})
        pairs = [r for r in reply["data"]["results"] if r["source"]["id"] == "cedict-translator"][0]["pairs"]
        self.assertEqual(pairs[0]["dst"], "中国")
        reply, _, _ = self.call("data.remove", {"id": "cedict"})
        self.assertTrue(reply["data"]["removed"])
        reply, _, _ = self.call("data.install", {"id": "nope"})
        self.assertFalse(reply["ok"])
        reply, _, _ = self.call("data.install", {"id": "cedict"})   # offline -> download fails cleanly
        self.assertFalse(reply["ok"])
        self.assertIn("offline", reply["error"]["message"])

    def test_cli(self):
        shutil.copy(fixture("mini-en.json"), self.data_dir / "mini-en.json")
        self.assertEqual(self.cli("sources", "list").returncode, 0)
        self.assertIn("duden", self.cli("sources", "list").stdout)
        proc = self.cli("data", "import", "ecdict", str(fixture("ecdict-sample.csv")))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("imported ecdict: 2 entries", proc.stdout)
        proc = self.cli("lookup", "house", "--lang", "en", "--only", "ecdict")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("a dwelling that serves", proc.stdout)
        proc = self.cli("translate", "house", "--from", "en", "--to", "zh", "--only", "ecdict-translator")
        self.assertIn("房子", proc.stdout)
        proc = self.cli("thesaurus", "house", "--lang", "en", "--json")
        self.assertEqual(json.loads(proc.stdout)["ok"], True)
        self.assertIn("house", self.cli("history", "list").stdout)
        self.assertEqual(self.cli("history", "clear").returncode, 0)
        self.assertEqual(self.cli("history", "list").stdout.strip(), "")
        self.assertIn("[✔] ecdict", self.cli("data", "list").stdout)
        self.assertEqual(self.cli("data", "remove", "ecdict").returncode, 0)
        self.assertIn("local", self.cli("drivers").stdout)
        self.assertEqual(self.cli("sources", "disable", "duden").returncode, 0)
        self.assertEqual(self.cli("sources", "enable", "nope").returncode, 1)
        self.assertTrue(self.cli("sources", "path").stdout.strip().endswith("sources.json"))
        self.assertIn('"languages"', self.cli("state").stdout)
        proc = self.cli("copy", "hello", "world")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual((self.tmp / "clipboard.txt").read_text(encoding="utf-8"), "hello world")
        self.assertIn("usage", self.cli("--help").stdout.lower())


if __name__ == "__main__":
    unittest.main()
