import QtQuick
import QtQuick.Window
// Test stub: a plain Window standing in for Quickshell's PanelWindow.
Window {
  component PanelAnchors: QtObject {
    property bool top: false
    property bool bottom: false
    property bool left: false
    property bool right: false
  }
  property PanelAnchors anchors: PanelAnchors {}
  property int exclusionMode: 0
  width: 1280
  height: 800
  default property alias data: contentItemHolder.data
  Item { id: contentItemHolder; anchors.fill: parent }
}
