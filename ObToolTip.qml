import QtQuick
import QtQuick.Controls
import qs.Commons
import qs.Ui

// Tooltip styled exactly like the one qs.Ui.Button renders, for items that
// are not buttons (the disabled target-language picker, for example).
ToolTip {
  id: root

  property color tooltipBackground: Color.tooltip.background
  property color tooltipForeground: Color.tooltip.text
  property color tooltipBorder: Color.tooltip.border
  property string fontFamily: Style.font.family
  readonly property var borderSpec: Border.localOrSurfaceSpec("tooltip", "border", tooltipBorder, Color.tooltip.border, Math.max(1, Style.normalBorderWidth))

  delay: 400
  padding: 0
  background: BorderSurface {
    color: root.tooltipBackground
    borderSpec: root.borderSpec
    radius: 0
  }
  contentItem: Text {
    textFormat: Text.PlainText
    text: root.text
    color: root.tooltipForeground
    font.family: root.fontFamily
    font.pixelSize: Style.font.bodySmall
    leftPadding: Border.left(root.borderSpec) + Style.spacing.controlPaddingX
    rightPadding: Border.right(root.borderSpec) + Style.spacing.controlPaddingX
    topPadding: Border.top(root.borderSpec) + Style.spacing.controlPaddingY
    bottomPadding: Border.bottom(root.borderSpec) + Style.spacing.controlPaddingY
  }
}
