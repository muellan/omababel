#!/usr/bin/env python3
"""A stand-in for libsecret's `secret-tool`, backed by a JSON file.

Only the three calls ob.secrets makes are implemented:

    secret-tool store --label=… <attr> <value> …      (secret on stdin)
    secret-tool lookup <attr> <value> …
    secret-tool clear  <attr> <value> …

The store lives in $OMABABEL_FAKE_KEYRING.  Exit codes follow the real
tool: 0 on success, 1 when a lookup finds nothing.
"""

import json
import os
import sys


def load(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def main(argv):
    path = os.environ.get("OMABABEL_FAKE_KEYRING")
    if not path:
        sys.stderr.write("OMABABEL_FAKE_KEYRING is not set\n")
        return 2
    if not argv:
        return 2
    action, rest = argv[0], [a for a in argv[1:] if not a.startswith("--")]
    key = "\x1f".join(rest)
    store = load(path)
    if action == "store":
        store[key] = sys.stdin.read()
    elif action == "lookup":
        if key not in store:
            return 1
        sys.stdout.write(store[key])
        return 0
    elif action == "clear":
        store.pop(key, None)
    else:
        return 2
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(store, fh)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
