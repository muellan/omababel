import QtQuick
import qs.Commons
import qs.Ui

// Optional book icon for the bar. The shell loads this separately from the
// panel, and only once someone adds the widget. A click asks the shell to
// toggle this plugin — the same path a keybinding takes — which opens and
// closes Omababel.qml. A bar that has no shell facade falls back to IPC.
BarWidget {
  id: root
  moduleName: "muellan.omababel"

  function togglePanel() {
    var id = root.moduleName || "muellan.omababel"
    var shell = root.bar ? root.bar.shell : null
    if (shell && typeof shell.toggle === "function") {
      shell.toggle(id, "{}")
      return
    }
    if (root.bar && typeof root.bar.run === "function")
      root.bar.run("omarchy-shell shell toggle " + id + " '{}'")
  }

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: "\uf02d"
    slotSize: Style.bar.statusSlot
    tooltipText: "Omababel"
    onPressed: root.togglePanel()
  }
}
