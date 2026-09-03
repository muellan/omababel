"""System clipboard access (Wayland ``wl-copy``, X11 ``xclip`` fallback)."""

from __future__ import annotations

import os
import shutil
import subprocess


class ClipboardError(Exception):
    pass


def copy(text: str) -> str:
    """Copy ``text``; returns the tool used."""
    if os.environ.get("OMABABEL_FAKE_CLIPBOARD"):
        # Test hook: write to a file instead of touching the real clipboard.
        with open(os.environ["OMABABEL_FAKE_CLIPBOARD"], "w", encoding="utf-8") as fh:
            fh.write(text)
        return "fake"
    for tool, argv in (("wl-copy", ["wl-copy"]), ("xclip", ["xclip", "-selection", "clipboard"]),
                       ("xsel", ["xsel", "--clipboard", "--input"])):
        if shutil.which(tool):
            try:
                # wl-copy forks a clipboard owner; do not capture its output or
                # the pipe keeps us alive until the selection is replaced.
                subprocess.run(argv, input=text, text=True, check=True,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
                return tool
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
                raise ClipboardError(f"{tool} failed: {e}")
    raise ClipboardError("no clipboard tool found (install wl-clipboard)")
