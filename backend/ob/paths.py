"""XDG-style locations used by omababel.

Nothing is written into the plugin checkout itself: ``omarchy plugin update``
refuses to fast-forward a dirty checkout, so all mutable state lives under the
user's XDG directories.  Every location can be overridden through an
environment variable, which the test-suite uses to stay hermetic.
"""

from __future__ import annotations

import os
from pathlib import Path

APP = "omababel"


def _env_path(name: str, default: Path) -> Path:
    value = os.environ.get(name)
    return Path(value).expanduser() if value else default


def home() -> Path:
    return Path(os.environ.get("HOME", str(Path.home())))


def config_dir() -> Path:
    """``~/.config/omababel`` – sources.json and preferences."""
    override = os.environ.get("OMABABEL_CONFIG_DIR")
    if override:
        return Path(override).expanduser()
    base = _env_path("XDG_CONFIG_HOME", home() / ".config")
    return base / APP


def data_dir() -> Path:
    """``~/.local/share/omababel`` – the app's *local storage*.

    Local sources are addressed relative to this directory.
    """
    override = os.environ.get("OMABABEL_DATA_DIR")
    if override:
        return Path(override).expanduser()
    base = _env_path("XDG_DATA_HOME", home() / ".local" / "share")
    return base / APP


def state_dir() -> Path:
    """``~/.local/state/omababel`` – search history."""
    override = os.environ.get("OMABABEL_STATE_DIR")
    if override:
        return Path(override).expanduser()
    base = _env_path("XDG_STATE_HOME", home() / ".local" / "state")
    return base / APP


def cache_dir() -> Path:
    """``~/.cache/omababel`` – indexes built from raw local files."""
    override = os.environ.get("OMABABEL_CACHE_DIR")
    if override:
        return Path(override).expanduser()
    base = _env_path("XDG_CACHE_HOME", home() / ".cache")
    return base / APP


def plugin_dir() -> Path:
    """Directory of the plugin checkout (``backend/..``)."""
    return Path(__file__).resolve().parent.parent.parent


def ensure_dirs() -> None:
    for d in (config_dir(), data_dir(), state_dir(), cache_dir()):
        d.mkdir(parents=True, exist_ok=True)


def resolve_local(path: str) -> Path:
    """Resolve a source ``path`` relative to the data dir.

    Absolute paths and ``~`` are honoured so power users can point at files
    anywhere on disk.
    """
    p = Path(os.path.expanduser(path))
    if p.is_absolute():
        return p
    return data_dir() / p
