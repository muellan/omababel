import QtQuick
import qs.Commons
import qs.Ui

// The Lookup / Thesaurus / Translate selector.
//
// Same contract as the kit's ButtonGroup (`options`, `value`, `changed`,
// keyboard navigation with h/l and Left/Right), but the engaged chip is
// painted in the theme's accent instead of the plain foreground: the kit's
// Button derives both its selected text colour and its selected fill from
// the `foreground` it is given, so handing the selected chip the accent
// yields accent text on a dimmed, semi-transparent accent fill.
Row {
  id: root

  property var options: []
  property string value: ""
  property color foreground: Color.foreground
  property color accent: Color.accent
  property string fontFamily: Style.font.family
  property real fontSize: Style.font.body
  property int focusedIndex: -1

  signal changed(string value)

  spacing: Style.spacing.md
  activeFocusOnTab: true

  function optionValue(o) { return (o && typeof o === "object") ? String(o.value) : String(o) }
  function optionLabel(o) { return (o && typeof o === "object" && o.label !== undefined) ? String(o.label) : String(o) }
  function optionIcon(o) { return (o && typeof o === "object" && o.icon) ? String(o.icon) : "" }
  function optionTooltip(o) { return (o && typeof o === "object" && o.tooltip) ? String(o.tooltip) : "" }

  function selectedOptionIndex() {
    for (var i = 0; i < root.options.length; i++)
      if (root.optionValue(root.options[i]) === root.value) return i
    return -1
  }

  onActiveFocusChanged: {
    if (activeFocus) {
      var idx = root.selectedOptionIndex()
      root.focusedIndex = idx < 0 ? 0 : idx
    } else {
      root.focusedIndex = -1
    }
  }

  Keys.priority: Keys.BeforeItem
  Keys.onPressed: function(event) {
    var cur = root.focusedIndex < 0 ? 0 : root.focusedIndex
    if (event.key === Qt.Key_Left || event.key === Qt.Key_H) {
      root.focusedIndex = Math.max(0, cur - 1)
      event.accepted = true
    } else if (event.key === Qt.Key_Right || event.key === Qt.Key_L) {
      root.focusedIndex = Math.min(root.options.length - 1, cur + 1)
      event.accepted = true
    } else if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter || event.key === Qt.Key_Space) {
      if (root.focusedIndex >= 0 && root.focusedIndex < root.options.length)
        root.changed(root.optionValue(root.options[root.focusedIndex]))
      event.accepted = true
    }
  }

  Repeater {
    model: root.options

    delegate: Button {
      id: chip
      required property var modelData
      required property int index
      readonly property bool isSelected: root.optionValue(modelData) === root.value
      objectName: "modeChip"
      text: root.optionLabel(modelData)
      iconText: root.optionIcon(modelData)
      tooltipText: root.optionTooltip(modelData)
      selected: chip.isSelected
      hasCursor: root.activeFocus && root.focusedIndex === index
      bordered: true
      // The accent only for the engaged chip – the others keep the panel
      // foreground so the row does not turn into a wall of accent colour.
      foreground: chip.isSelected ? root.accent : root.foreground
      background: "transparent"
      accent: root.accent
      fontFamily: root.fontFamily
      fontSize: root.fontSize
      onClicked: root.changed(root.optionValue(modelData))
    }
  }
}
