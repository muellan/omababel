"""Shared test scaffolding.

Every test runs against a throw-away XDG tree so nothing touches the real
``~/.config/omababel`` and no network access happens (``OMABABEL_OFFLINE``).
"""

from __future__ import annotations

import contextlib
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
FIXTURES = Path(__file__).resolve().parent / "fixtures"

if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

os.environ.setdefault("OMABABEL_OFFLINE", "1")


class TempEnv(unittest.TestCase):
    """Base class: fresh config/data/state/cache dirs per test."""

    def setUp(self) -> None:
        super().setUp()
        self.tmp = Path(tempfile.mkdtemp(prefix="omababel-test-"))
        self._old_env = {k: os.environ.get(k) for k in
                         ("OMABABEL_CONFIG_DIR", "OMABABEL_DATA_DIR", "OMABABEL_STATE_DIR",
                          "OMABABEL_CACHE_DIR", "OMABABEL_OFFLINE", "OMABABEL_FAKE_CLIPBOARD",
                          "OMABABEL_SECRET_TOOL", "OMABABEL_FAKE_KEYRING")}
        os.environ["OMABABEL_CONFIG_DIR"] = str(self.tmp / "config")
        os.environ["OMABABEL_DATA_DIR"] = str(self.tmp / "data")
        os.environ["OMABABEL_STATE_DIR"] = str(self.tmp / "state")
        os.environ["OMABABEL_CACHE_DIR"] = str(self.tmp / "cache")
        os.environ["OMABABEL_OFFLINE"] = "1"
        os.environ["OMABABEL_FAKE_CLIPBOARD"] = str(self.tmp / "clipboard.txt")
        # a throw-away keyring: credentials never touch the real one
        os.environ["OMABABEL_SECRET_TOOL"] = str(Path(__file__).resolve().parent / "fake_secret_tool.py")
        os.environ["OMABABEL_FAKE_KEYRING"] = str(self.tmp / "keyring.json")
        for d in ("config", "data", "state", "cache"):
            (self.tmp / d).mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        for k, v in self._old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.tmp, ignore_errors=True)
        super().tearDown()

    @property
    def data_dir(self) -> Path:
        return self.tmp / "data"

    def env(self) -> dict:
        return dict(os.environ)


def fixture(name: str) -> Path:
    return FIXTURES / name


def read_fixture(name: str) -> str:
    return fixture(name).read_text(encoding="utf-8")


class FakeResponse:
    def __init__(self, text: str = "", status: int = 200, headers=None, url: str = ""):
        self.text = text
        self.body = text.encode("utf-8")
        self.status = status
        self.headers = headers or {"content-type": "text/html; charset=utf-8"}
        self.url = url

    def json(self):
        import json
        return json.loads(self.text)


@contextlib.contextmanager
def fake_fetch(handler):
    """Replace ``ob.http.fetch`` with ``handler(url, **kw)`` for the block.

    The handler returns a FakeResponse or raises ``http.FetchError``.
    """
    from ob import http
    calls = []
    original = http.fetch

    def fetch(url, **kw):
        calls.append((url, kw))
        return handler(url, **kw)

    http.fetch = fetch
    os.environ.pop("OMABABEL_OFFLINE", None)
    try:
        yield calls
    finally:
        http.fetch = original
        os.environ["OMABABEL_OFFLINE"] = "1"
