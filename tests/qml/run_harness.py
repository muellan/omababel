#!/usr/bin/env python3
"""Run tests/qml/Harness.qml offscreen with PySide6 (any Qt >= 6.6).

    python3 tests/qml/run_harness.py <import-dir> <plugin-copy-dir> <fixture-dir>

Exit code 0 when the harness prints ``HARNESS OK`` and no QML error/warning
was emitted.  Used by tests/run.sh; needs ``pip install PySide6``.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_LOGGING_RULES", "qt.qml.*=false;qt.tools.*=false")
os.environ["QML_XHR_ALLOW_FILE_READ"] = "1"

try:
    from PySide6.QtCore import QCoreApplication, QTimer, QUrl, QtMsgType, qInstallMessageHandler
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQml import QQmlComponent, QQmlEngine
    from PySide6.QtQuick import QQuickWindow
except ImportError:  # pragma: no cover
    print("PySide6 not installed – pip install PySide6", file=sys.stderr)
    sys.exit(3)

BAD = re.compile(r"HARNESS FAIL|TypeError|ReferenceError|is not a type|Cannot assign|Unable to assign|"
                 r"is not defined|Error:|is not a function|Cannot read property|undefined")
IGNORE = re.compile(r"XDG_RUNTIME_DIR|qmlscene is deprecated|QQmlComponent\(0x")


def main(argv) -> int:
    if len(argv) != 4:
        print(__doc__)
        return 2
    import_dir, plugin_dir, fixture_dir = (Path(p).resolve() for p in argv[1:])
    messages: list[str] = []
    ok_seen = {"ok": False}

    def handler(mode, ctx, msg):
        text = str(msg)
        if "HARNESS OK" in text:
            ok_seen["ok"] = True
        messages.append(text)
        print(text, file=sys.stderr)

    qInstallMessageHandler(handler)
    app = QGuiApplication(sys.argv[:1])
    engine = QQmlEngine()
    engine.addImportPath(str(import_dir))
    engine.addImportPath(str(plugin_dir))
    exit_code = {"code": None}

    def on_exit(code):
        exit_code["code"] = code
        app.exit(code)

    engine.exit.connect(on_exit)
    engine.quit.connect(lambda: app.exit(0))

    main_qml = plugin_dir / "Main.qml"
    main_qml.write_text(
        'import QtQuick\nHarness { pluginDir: "%s"; fixtureDir: "%s" }\n' % (plugin_dir, fixture_dir),
        encoding="utf-8")
    component = QQmlComponent(engine, QUrl.fromLocalFile(str(main_qml)))
    if component.isError():
        for err in component.errors():
            print("COMPONENT ERROR:", err.toString(), file=sys.stderr)
        return 1
    root = component.create()
    if root is None:
        for err in component.errors():
            print("CREATE ERROR:", err.toString(), file=sys.stderr)
        return 1
    QTimer.singleShot(60000, lambda: app.exit(4))   # watchdog
    rc = app.exec()
    if exit_code["code"] is not None:
        rc = exit_code["code"]
    bad = [m for m in messages if BAD.search(m) and not IGNORE.search(m)]
    if rc != 0 or not ok_seen["ok"] or bad:
        print(f"harness rc={rc} ok={ok_seen['ok']} problems={len(bad)}", file=sys.stderr)
        for m in bad:
            print("  ! " + m, file=sys.stderr)
        return 1 if rc == 0 else rc
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
