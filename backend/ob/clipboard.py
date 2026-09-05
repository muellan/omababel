"""System clipboard access (Wayland ``wl-copy``, X11 ``xclip`` fallback)."""

from __future__ import annotations

import os
import re
import shutil
import subprocess


class ClipboardError(Exception):
    pass


# Everything a dictionary entry may contain, and nothing a terminal acts on.
# What gets copied is scraped text, and a paste into a terminal is the most
# likely destination for it: an escape sequence would be interpreted there,
# and an embedded newline would submit whatever precedes it as a command.
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")


def sanitize(text: str) -> str:
    """``text`` with the control characters a terminal would act on removed.

    Tab and newline stay – a full-text translation has line structure worth
    keeping – so a paste into a shell can still span lines; what it cannot do
    is move the cursor, rewrite the line or set the window title.
    """
    return _CONTROL.sub("", str(text))


def copy(text: str) -> str:
    """Copy ``text``; returns the tool used."""
    text = sanitize(text)
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
