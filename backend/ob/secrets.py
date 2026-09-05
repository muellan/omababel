"""Credential storage.

API keys and other credentials never go into ``sources.json``.  They are
kept in the login keyring of the session (Omarchy ships gnome-keyring, which
implements the freedesktop Secret Service) and are read back only when a
source is actually queried.

The keyring is reached through ``secret-tool`` (libsecret's CLI, part of
every Secret Service install) so the backend stays stdlib-only:

    secret-tool store --label='omababel: mw' service omababel id mw
    secret-tool lookup service omababel id mw
    secret-tool clear  service omababel id mw

Two alternatives are supported for setups without a running keyring, and
for people who keep their secrets somewhere else (``pass``, ``age``, a
password manager's CLI):

* ``api_key_env`` – the name of an environment variable, or
* ``api_key_cmd`` – a command whose first line of output is the secret.

Nothing here ever writes a secret to a file.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from typing import Optional

SERVICE = "omababel"
TOOL_ENV = "OMABABEL_SECRET_TOOL"      # tests point this at a stub
TIMEOUT = 10
# A source id names a keyring entry and is passed to secret-tool as an
# argument; it is an identifier, so it looks like one.
_BAD_ID = re.compile(r"[^A-Za-z0-9._-]")


class SecretError(Exception):
    """The secret could not be stored, read or removed."""


def tool() -> Optional[str]:
    """Path of the secret-tool binary, or None when there is none."""
    override = os.environ.get(TOOL_ENV)
    if override:
        return override if (os.path.isabs(override) and os.access(override, os.X_OK)) else shutil.which(override)
    return shutil.which("secret-tool")


def available() -> bool:
    """True when secrets can be stored (tool present and a service running)."""
    if os.environ.get("OMABABEL_NO_KEYRING"):
        return False
    binary = tool()
    if not binary:
        return False
    # A lookup for a key that does not exist exits 1 without touching
    # anything; a broken/absent Secret Service fails differently (2, or a
    # D-Bus error on stderr).
    try:
        proc = _run([binary, "lookup", "service", SERVICE, "id", "__probe__"])
    except SecretError:
        return False
    return proc.returncode in (0, 1) and "org.freedesktop" not in (proc.stderr or "")


def backend_name() -> str:
    return "secret-service (secret-tool)" if available() else ""


def _run(argv, stdin: str = "") -> subprocess.CompletedProcess:
    try:
        return subprocess.run(argv, input=stdin, capture_output=True, text=True, timeout=TIMEOUT)
    except (OSError, subprocess.SubprocessError) as e:
        raise SecretError(str(e))


def _attrs(source_id: str):
    """The attribute pair that identifies one source's secret.

    `--` first: the id is appended as a positional argument, and secret-tool
    parses GLib options anywhere on the line, so an id of `--help` would turn
    a lookup into a usage message printed on stdout – which `load` would then
    hand back as the API key.
    """
    ident = str(source_id)
    if not ident or ident.startswith("-") or _BAD_ID.search(ident):
        raise SecretError(f"invalid source id: {source_id!r}")
    return ["--", "service", SERVICE, "id", ident]


def store(source_id: str, secret: str) -> None:
    binary = tool()
    if not binary:
        raise SecretError("no keyring available (install libsecret / gnome-keyring)")
    if not secret:
        remove(source_id)
        return
    proc = _run([binary, "store", "--label=omababel: " + str(source_id)] + _attrs(source_id),
                stdin=secret)
    if proc.returncode != 0:
        raise SecretError((proc.stderr or "secret-tool store failed").strip())


def load(source_id: str) -> str:
    binary = tool()
    if not binary:
        return ""
    try:
        proc = _run([binary, "lookup"] + _attrs(source_id))
    except SecretError:
        return ""
    if proc.returncode != 0:
        return ""
    return (proc.stdout or "").rstrip("\n")


def remove(source_id: str) -> None:
    binary = tool()
    if not binary:
        return
    try:
        _run([binary, "clear"] + _attrs(source_id))
    except SecretError:
        pass


def from_env(name: str) -> str:
    return os.environ.get(str(name or ""), "") if name else ""


def from_command(command: str) -> str:
    """First line of the command's output (``pass show …`` and friends)."""
    command = str(command or "").strip()
    if not command:
        return ""
    try:
        proc = _run(["sh", "-c", command])
    except SecretError:
        return ""
    if proc.returncode != 0:
        return ""
    return (proc.stdout or "").split("\n", 1)[0].strip()


def resolve(row: dict) -> str:
    """The secret for a source row: env var, command, then the keyring.

    Rows that never had a secret stored (``has_key`` is false and no env /
    command is configured) skip the keyring entirely – otherwise every
    request would pay for one round trip per source.
    """
    return (from_env(row.get("api_key_env", ""))
            or from_command(row.get("api_key_cmd", ""))
            or (load(row.get("id", "")) if row.get("has_key") else ""))


def describe(row: dict) -> str:
    """Where this row's secret comes from – for the preferences panel."""
    if row.get("api_key_env") and from_env(row["api_key_env"]):
        return "environment"
    if row.get("api_key_cmd"):
        return "command"
    if row.get("has_key") and load(row.get("id", "")):
        return "keyring"
    return ""
