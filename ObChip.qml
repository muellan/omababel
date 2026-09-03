import QtQuick
import qs.Commons
import qs.Ui

// A single word as a small bordered chip (thesaurus lists).
// Ctrl+click -> search that word, Alt+click -> copy it.
BorderSurface {
  id: root

  property string word: ""
  property color foreground: Color.menu.text
  property color accent: Color.accent

  signal searchWord(string word)
  signal copyText(string text)

  readonly property bool hot: area.containsMouse

  implicitWidth: label.implicitWidth + Style.spacing.controlPaddingX * 2
  implicitHeight: label.implicitHeight + Style.spacing.xs * 2
  radius: Style.cornerRadius
  color: hot ? Style.hoverFillFor(foreground, accent) : Style.normalFillFor(foreground, accent)
  borderSpec: Border.controlSpec(hot ? "hover-cursor" : "normal", foreground, accent)

  Text {
    id: label
    anchors.centerIn: parent
    textFormat: Text.PlainText
    text: root.word
    color: root.foreground
    font.family: Style.font.family
    font.pixelSize: Style.font.body
  }

  MouseArea {
    id: area
    anchors.fill: parent
    hoverEnabled: true
    cursorShape: Qt.PointingHandCursor
    onClicked: function(mouse) {
      if (mouse.modifiers & Qt.ControlModifier) root.searchWord(root.word)
      else if (mouse.modifiers & Qt.AltModifier) root.copyText(root.word)
    }
  }
}
