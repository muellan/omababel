"""Packaging checks: manifest (same rules as `omarchy plugin validate`),
no symlinks, LICENSE/README present, QML files structurally sane."""

import json
import os
import re
import unittest
from pathlib import Path

from helpers import ROOT


class ManifestTest(unittest.TestCase):
    def setUp(self):
        self.manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))

    def test_schema(self):
        m = self.manifest
        self.assertEqual(m["schemaVersion"], 1)
        for field in ("id", "name", "version", "kinds", "entryPoints"):
            self.assertIn(field, m)
        self.assertRegex(m["id"], r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
        self.assertFalse(m["id"].startswith("omarchy."))
        self.assertNotIn("..", m["id"])
        self.assertEqual(m["id"], "muellan.omababel")
        self.assertIsInstance(m["kinds"], list)
        self.assertTrue(m["kinds"])
        self.assertEqual(m["kinds"], ["panel"])
        self.assertTrue(m.get("keepLoaded"))
        self.assertEqual(m.get("license"), "MIT")

    def test_entry_points_exist_and_are_safe(self):
        eps = self.manifest["entryPoints"]
        self.assertIsInstance(eps, dict)
        self.assertIn("panel", eps)
        for kind, rel in eps.items():
            self.assertFalse(rel.startswith("/"))
            self.assertNotIn("..", rel)
            self.assertTrue((ROOT / rel).is_file(), rel)

    def test_no_symlinks_in_plugin(self):
        for path in ROOT.rglob("*"):
            if ".git" in path.parts:
                continue
            self.assertFalse(path.is_symlink(), f"symlink found: {path}")

    def test_license_and_readme(self):
        lic = (ROOT / "LICENSE").read_text(encoding="utf-8")
        self.assertIn("MIT License", lic)
        self.assertIn("Permission is hereby granted, free of charge", lic)
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        for needle in ("omarchy plugin add", "muellan.omababel", "omarchy-shell shell toggle muellan.omababel",
                       "omababel data install"):
            self.assertIn(needle, readme, needle)
        lowered = readme.lower()
        for heading in ("## install", "## adding your own sources", "## license"):
            self.assertIn(heading, lowered, heading)

    def test_readme_documents_the_browser_transport(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8").lower()
        for needle in ("browser", "curl-impersonate", "omababel_impersonate", "cookies"):
            self.assertIn(needle, readme, needle)

    def test_readme_documents_credential_storage(self):
        # Whitespace-insensitive: the command examples are column-aligned, so
        # `omababel    sources key` is the same documentation as one space.
        readme = re.sub(r"\s+", " ", (ROOT / "README.md").read_text(encoding="utf-8").lower())
        for needle in ("keyring", "secret-tool", "never written to a file in plain text",
                       "omababel sources key"):
            self.assertIn(needle, readme, needle)

    def test_backend_is_stdlib_only(self):
        stdlib_ok = {"__future__", "annotations", "argparse", "base64", "concurrent", "csv", "email", "gzip",
                     "hashlib", "html", "http", "io", "json",
                     "lzma", "os", "pathlib", "random", "re", "shlex", "shutil", "socket", "sqlite3", "ssl", "subprocess", "sys",
                     "tarfile", "tempfile", "time", "traceback", "typing", "unicodedata", "urllib", "xml",
                     "zipfile", "zlib", "ob"}
        import ast
        for py in (ROOT / "backend").rglob("*.py"):
            tree = ast.parse(py.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.Import):
                    names = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    names = [node.module]
                for name in names:
                    top = name.split(".")[0]
                    self.assertIn(top, stdlib_ok, f"{py.name}: third-party import '{top}'")

    def test_bin_wrapper(self):
        wrapper = ROOT / "bin" / "omababel"
        self.assertTrue(wrapper.is_file())
        self.assertTrue(os.access(wrapper, os.X_OK))
        self.assertTrue(wrapper.read_text(encoding="utf-8").startswith("#!/bin/bash"))


class QmlStructureTest(unittest.TestCase):
    def qml_files(self):
        return sorted(ROOT.glob("*.qml"))

    def strip(self, text):
        """Remove string literals and comments (single pass, so a // inside
        a URL string or a quote inside a comment cannot confuse the count)."""
        out = []
        i, n = 0, len(text)
        while i < n:
            ch = text[i]
            if ch in "\"'":
                j = i + 1
                while j < n and text[j] != ch:
                    j += 2 if text[j] == "\\" else 1
                out.append(ch + ch)
                i = j + 1
            elif text.startswith("//", i) and (i == 0 or text[i - 1] != "\\"):   # not the \/\/ of a regex
                j = text.find("\n", i)
                i = n if j < 0 else j
            elif text.startswith("/*", i):
                j = text.find("*/", i + 2)
                i = n if j < 0 else j + 2
            else:
                out.append(ch)
                i += 1
        return "".join(out)

    def test_braces_balanced(self):
        for f in self.qml_files():
            src = self.strip(f.read_text(encoding="utf-8"))
            for open_ch, close_ch in (("{", "}"), ("(", ")"), ("[", "]")):
                self.assertEqual(src.count(open_ch), src.count(close_ch), f"{f.name}: unbalanced {open_ch}{close_ch}")

    def test_panel_contract(self):
        src = (ROOT / "Omababel.qml").read_text(encoding="utf-8")
        for needle in ("property var shell", "property var manifest", "property bool opened",
                       "function open(", "function close(", "function dismiss(", "function toggle(",
                       "PanelWindow", "WlrLayershell.keyboardFocus", "backend/omababel.py"):
            self.assertIn(needle, src, needle)
        # spec: three modes, two language selectors, history, preferences, help
        for needle in ('"lookup"', '"thesaurus"', '"translate"', "langPicker2", "historyPopup",
                       "ObPrefs", "ObResults", "ObHelp"):
            self.assertIn(needle, src, needle)

    def test_shortcuts_are_documented_in_the_help(self):
        """Every Ctrl sequence the panel binds appears in the help panel."""
        panel = (ROOT / "Omababel.qml").read_text(encoding="utf-8")
        help_src = (ROOT / "ObHelp.qml").read_text(encoding="utf-8")
        bound = set(re.findall(r'Shortcut \{ sequence: "([^"]+)"', panel))
        self.assertGreaterEqual(len(bound), 20)
        for seq in bound:
            self.assertIn(seq, help_src, f"{seq} is bound but missing from the help panel")
        self.assertIn("github.com/muellan/omababel", help_src)

    def test_components_referenced_exist(self):
        names = {f.stem for f in self.qml_files()}
        for f in self.qml_files():
            src = self.strip(f.read_text(encoding="utf-8"))
            for used in set(re.findall(r"\b(Ob[A-Z]\w*)\s*\{", src)):
                self.assertIn(used, names, f"{f.name} uses unknown component {used}")

    def body_of(self, src, marker):
        """Source of the block that starts at `marker`, by brace counting."""
        start = src.index(marker)
        depth, i = 0, src.index("{", start)
        j = i
        while j < len(src):
            if src[j] == "{":
                depth += 1
            elif src[j] == "}":
                depth -= 1
                if depth == 0:
                    return src[i:j + 1]
            j += 1
        raise AssertionError(f"unterminated block for {marker}")

    def test_backend_never_starts_a_process_from_an_exit_handler(self):
        """Re-arming a Process from inside its own `onExited` (directly or
        through a reply callback that issues the next request) crashed the
        shell on the first open.  Every start goes through `pump()`, and even
        the reply is assembled from the event loop."""
        src = self.strip((ROOT / "ObBackend.qml").read_text(encoding="utf-8"))
        exited = self.body_of(src, "onExited:")
        self.assertNotIn("running = true", exited)
        self.assertNotIn("root.pump()", exited)
        self.assertIn("Qt.callLater(root.finish)", exited)
        finish = self.body_of(src, "function finish(")
        self.assertIn("root.schedule()", finish)
        self.assertNotIn("running = true", finish)
        self.assertIn("Qt.callLater(root.pump)", self.body_of(src, "function schedule("))
        pump = self.body_of(src, "function pump(")
        self.assertIn("if (root.inCallback || root.busy || proc.running) return", pump)
        # the only place `running` is set
        self.assertEqual(src.count("proc.running = true"), 1)

    def test_the_backend_can_stream(self):
        """A search shows each source as it answers, so one slow AI service
        cannot hold up the sources that are already done."""
        src = self.strip((ROOT / "ObBackend.qml").read_text(encoding="utf-8"))
        self.assertIn("SplitParser", src)                 # line by line, not in one lump
        self.assertIn("function call(op, params, done, onProgress)", src)
        panel = self.strip((ROOT / "Omababel.qml").read_text(encoding="utf-8"))
        self.assertIn("stream: true", panel)
        self.assertIn("function applySearchEvent(", panel)
        # the installer defers its `finished` signal for the same reason
        inst = self.strip((ROOT / "ObInstaller.qml").read_text(encoding="utf-8"))
        self.assertNotIn("root.finished(reply)", self.body_of(inst, "onExited:"))
        self.assertIn("Qt.callLater(root.emitFinished)", inst)

    def test_the_first_open_does_no_work_a_later_one_does_not(self):
        """The panel crashed the shell on the very first open after an
        install or update.  Everything that only happened on the first open
        -- the backend's cold start and filling the language/source models --
        now runs at load time, so opening is always the same code path."""
        panel = self.strip((ROOT / "Omababel.qml").read_text(encoding="utf-8"))
        self.assertIn("Component.onCompleted: root.preload()", panel)
        preload = self.body_of(panel, "function preload(")
        self.assertIn("backend.warmup()", preload)
        self.assertIn("root.loadState()", preload)
        self.assertIn("function warmup()", (ROOT / "ObBackend.qml").read_text(encoding="utf-8"))
        # open() must not throw into the shell's IPC caller
        self.assertIn("try { root.applyOpen(payload) } catch", panel)
        # focus is taken after the surface is mapped, not from open()
        self.assertNotIn("forceActiveFocus", self.body_of(panel, "function applyOpen("))

    def test_no_stray_hyprland_import(self):
        for f in self.qml_files():
            self.assertNotIn("Quickshell.Hyprland", f.read_text(encoding="utf-8"), f.name)


if __name__ == "__main__":
    unittest.main()
