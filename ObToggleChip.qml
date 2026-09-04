import QtQuick
import qs.Commons
import qs.Ui

// A chip that is either engaged or not, painted like the panel's mode
// selector: accent text on a dimmed, semi-transparent accent fill when it is
// on, the plain foreground when it is off.
//
// Drawn here rather than through qs.Ui.Button for the same reason as
// ObModeSelector: the kit takes a button's selected colour from the theme's
// `selected-color` token, which themes pin to the foreground, so an engaged
// Button cannot be told to show the accent.  Everything else comes from the
// kit's Style.
BorderSurface {
  id: root

  property string text: ""
  property string iconText: ""
  property string tooltipText: ""
  property bool checked: false
  property color foreground: Color.foreground
  property color accent: Color.accent
  property string fontFamily: Style.font.family
  property real fontSize: Style.font.body

  readonly property real selectedFillAlpha: Math.max(0.18, Style.selectedFillAlpha)
  readonly property real hoverFillAlpha: Math.max(0.10, Style.hoverFillAlpha)
  readonly property bool hot: hover.hovered
  readonly property color chipForeground: root.checked ? root.accent : root.foreground
  readonly property color fillColor: root.checked
    ? Util.alpha(root.accent, mouse.pressed ? root.selectedFillAlpha * 1.6 : root.selectedFillAlpha)
    : (root.hot ? Util.alpha(root.foreground, root.hoverFillAlpha) : Qt.rgba(0, 0, 0, 0))

  signal toggled()

  implicitWidth: label.implicitWidth + Style.spacing.controlPaddingX * 2
                 + Border.left(root.borderSpec) + Border.right(root.borderSpec)
  implicitHeight: label.implicitHeight + Style.spacing.controlPaddingY * 2
                  + Border.top(root.borderSpec) + Border.bottom(root.borderSpec)
  radius: Style.cornerRadius
  color: root.fillColor
  borderSpec: Border.flat(Util.alpha(root.chipForeground,
                                     root.checked ? 0.55 : (root.hot ? 0.35 : 0.18)),
                          Math.max(1, Style.normalBorderWidth))

  Behavior on color { ColorAnimation { duration: 120 } }

  Row {
    id: label
    anchors.centerIn: parent
    spacing: Style.spacing.controlGap

    Text {
      textFormat: Text.PlainText
      visible: text !== ""
      text: root.iconText
      color: root.chipForeground
      font.family: root.fontFamily
      font.pixelSize: Style.font.icon
      anchors.verticalCenter: parent.verticalCenter
    }
    Text {
      textFormat: Text.PlainText
      visible: text !== ""
      text: root.text
      color: root.chipForeground
      font.family: root.fontFamily
      font.pixelSize: root.fontSize
      font.bold: root.checked
      anchors.verticalCenter: parent.verticalCenter
    }
  }

  HoverHandler { id: hover }
  MouseArea {
    id: mouse
    anchors.fill: parent
    cursorShape: Qt.PointingHandCursor
    onClicked: root.toggled()
  }
  ObToolTip {
    visible: hover.hovered && root.tooltipText !== ""
    text: root.tooltipText
  }
}
