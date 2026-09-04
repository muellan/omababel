import QtQuick
import qs.Commons
import qs.Ui

// The Lookup / Thesaurus / Translate selector.
//
// Same contract as the kit's ButtonGroup (`options`, `value`, `changed`,
// keyboard navigation with h/l and Left/Right), but the engaged chip is
// painted in the theme's accent – the colour of the panel's logo – rather
// than in the foreground.
//
// The chip is drawn here instead of through qs.Ui.Button on purpose: the
// kit derives a button's selected colour from the theme's `selected-color`
// token, which most themes pin to the foreground (or to a fixed hex), so a
// Button can never be talked into showing the accent.  Everything else –
// the border spec, the corner radius, the fill alphas, the spacing – still
// comes from the kit's Style, so the chips sit in the theme.
Row {
  id: root

  property var options: []
  property string value: ""
  property color foreground: Color.foreground
  property color accent: Color.accent
  property string fontFamily: Style.font.family
  property real fontSize: Style.font.body
  property int focusedIndex: -1

  // How much accent stays in the engaged chip's background.
  readonly property real selectedFillAlpha: Math.max(0.18, Style.selectedFillAlpha)
  readonly property real hoverFillAlpha: Math.max(0.10, Style.hoverFillAlpha)

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

    delegate: BorderSurface {
      id: chip
      required property var modelData
      required property int index
      objectName: "modeChip"

      readonly property bool selected: root.optionValue(modelData) === root.value
      readonly property bool hot: hover.hovered || (root.activeFocus && root.focusedIndex === index)
      // The engaged chip is the accent, everything else the panel foreground.
      readonly property color foreground: chip.selected ? root.accent : root.foreground

      implicitWidth: label.implicitWidth + Style.spacing.controlPaddingX * 2
                     + Border.left(chip.borderSpec) + Border.right(chip.borderSpec)
      implicitHeight: label.implicitHeight + Style.spacing.controlPaddingY * 2
                      + Border.top(chip.borderSpec) + Border.bottom(chip.borderSpec)
      radius: Style.cornerRadius
      // A dimmed, semi-transparent version of the chip's own colour: accent
      // for the engaged one, a plain hover tint for the others.  `color`
      // animates towards it, so the target is kept separately (that is also
      // what the tests assert on).
      readonly property color fillColor: chip.selected
        ? Util.alpha(root.accent, mouse.pressed ? root.selectedFillAlpha * 1.6 : root.selectedFillAlpha)
        : (chip.hot ? Util.alpha(root.foreground, root.hoverFillAlpha) : Qt.rgba(0, 0, 0, 0))
      color: chip.fillColor
      borderSpec: Border.flat(Util.alpha(chip.foreground,
                                         chip.selected ? 0.55 : (chip.hot ? 0.35 : 0.18)),
                              Math.max(1, Style.normalBorderWidth))

      Behavior on color { ColorAnimation { duration: 120 } }

      Row {
        id: label
        anchors.centerIn: parent
        spacing: Style.spacing.controlGap

        Text {
          textFormat: Text.PlainText
          visible: text !== ""
          text: root.optionIcon(chip.modelData)
          color: chip.foreground
          font.family: root.fontFamily
          font.pixelSize: Style.font.icon
          anchors.verticalCenter: parent.verticalCenter
        }
        Text {
          textFormat: Text.PlainText
          text: root.optionLabel(chip.modelData)
          color: chip.foreground
          font.family: root.fontFamily
          font.pixelSize: root.fontSize
          font.bold: chip.selected
          anchors.verticalCenter: parent.verticalCenter
        }
      }

      HoverHandler { id: hover }
      MouseArea {
        id: mouse
        anchors.fill: parent
        cursorShape: Qt.PointingHandCursor
        onClicked: root.changed(root.optionValue(chip.modelData))
      }
      ObToolTip {
        visible: hover.hovered && root.optionTooltip(chip.modelData) !== ""
        text: root.optionTooltip(chip.modelData)
      }
    }
  }
}
