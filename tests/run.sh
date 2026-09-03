#!/bin/bash
# omababel test runner.
#
#   tests/run.sh            # python unit tests + QML checks (when Qt tools are available)
#   tests/run.sh --python   # python only
#   tests/run.sh --qml      # QML only
#
# QML checks need an Omarchy shell checkout for the `qs.Commons` / `qs.Ui`
# kit: $OMARCHY_PATH/shell (the installed one), or a shallow clone of the
# quattro branch cached under tests/.cache. They use qmllint (syntax /
# static errors) and, when qmlscene is installed, an offscreen run of the
# panel with fixture data (tests/qml/Harness.qml).

set -o pipefail

here="$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")"
root="$(dirname "$here")"
do_python=1
do_qml=1
[[ ${1:-} == "--python" ]] && do_qml=0
[[ ${1:-} == "--qml" ]] && do_python=0
status=0

if (( do_python )); then
  echo "== python unit tests"
  if ! python3 -m unittest discover -s "$here" -p 'test_*.py' ${VERBOSE:+-v}; then
    status=1
  fi
fi

if (( do_qml )); then
  echo "== QML checks"
  shell_dir=""
  for cand in "${OMARCHY_PATH:-/nonexistent}/shell" "$HOME/.local/share/omarchy/shell" "$here/.cache/omarchy/shell"; do
    if [[ -f "$cand/Commons/qmldir" ]]; then shell_dir="$cand"; break; fi
  done
  if [[ -z $shell_dir ]] && command -v git >/dev/null; then
    echo "   cloning omarchy (quattro) shell kit into tests/.cache ..."
    mkdir -p "$here/.cache"
    if git clone -q --depth 1 -b quattro https://github.com/omacom/omarchy.git "$here/.cache/omarchy" 2>/dev/null; then
      shell_dir="$here/.cache/omarchy/shell"
    fi
  fi
  if [[ -z $shell_dir ]]; then
    echo "   SKIP: no Omarchy shell checkout found (set OMARCHY_PATH)"
  else
    qmllint_bin="$(command -v qmllint || ls /usr/lib/qt6/bin/qmllint 2>/dev/null | head -1)"
    qmlscene_bin="$(command -v qmlscene || ls /usr/lib/qt6/bin/qmlscene 2>/dev/null | head -1)"
    importdir="$(mktemp -d)"
    trap 'rm -rf "$importdir"' EXIT
    ln -s "$shell_dir" "$importdir/qs"
    cp -r "$here/qml/stubs/Quickshell" "$importdir/"

    if [[ -n $qmllint_bin ]]; then
      echo "   qmllint"
      for f in "$root"/*.qml; do
        out="$("$qmllint_bin" -I "$importdir" "$f" 2>&1)"
        if grep -q "^Error" <<<"$out"; then
          echo "   FAIL: $(basename "$f")"; grep -A3 "^Error" <<<"$out"; status=1
        fi
      done
    else
      echo "   SKIP qmllint (not installed)"
    fi

    if python3 -c "import PySide6" 2>/dev/null || [[ -n $qmlscene_bin ]]; then
      echo "   offscreen harness"
      work="$(mktemp -d)"
      cp "$root"/*.qml "$work/"
      # Quickshell-only attached properties have no stub equivalent.
      sed -i -E '/^\s*WlrLayershell\./d; /^\s*exclusionMode:/d' "$work/Omababel.qml"
      cp "$here/qml/Harness.qml" "$work/"
      if python3 -c "import PySide6" 2>/dev/null; then
        log="$(python3 "$here/qml/run_harness.py" "$importdir" "$work" "$here/qml/fixtures" 2>&1)"
        rc=$?
      else
        cat > "$work/Main.qml" <<MAIN
import QtQuick
Harness { pluginDir: "$work"; fixtureDir: "$here/qml/fixtures" }
MAIN
        log="$(cd "$work" && QT_QPA_PLATFORM=offscreen QML_XHR_ALLOW_FILE_READ=1 timeout 90 "$qmlscene_bin" -I "$importdir" -I "$work" --quit Main.qml 2>&1)"
        rc=$?
        if ! grep -q "HARNESS OK" <<<"$log" || grep -Eq "HARNESS FAIL|TypeError|ReferenceError|is not a type|Cannot assign|Unable to assign|is not defined|Error:" <<<"$log"; then
          rc=1
        fi
      fi
      rm -rf "$work"
      if (( rc != 0 )); then
        echo "   FAIL (exit $rc):"; sed 's/^/   | /' <<<"$log" | head -80; status=1
      else
        echo "   ok"
      fi
    else
      echo "   SKIP harness (needs PySide6 or qmlscene)"
    fi
  fi
fi

exit $status
