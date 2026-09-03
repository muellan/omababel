import QtQuick
import qs.Commons

// Rich text whose words are links (`<a href="w:...">`, produced by the
// backend).  Ctrl+click on a word starts a new search with it, Alt+click
// copies it – or the whole text when `copyWhole` is set (full-text
// translations).  Plain clicks do nothing, so accidental navigation is
// impossible; a plain click on a link still selects nothing.
Text {
  id: root

  property bool copyWhole: false
  property string plainText: ""       // what Alt+click copies when copyWhole
  property color linkTint: color

  signal searchWord(string word)
  signal copyText(string text)

  textFormat: Text.RichText
  wrapMode: Text.Wrap
  color: Color.menu.text
  linkColor: linkTint
  font.family: Style.font.family
  font.pixelSize: Style.font.body

  function wordFromHref(href) {
    if (!href || href.indexOf("w:") !== 0) return ""
    try { return decodeURIComponent(href.slice(2)) } catch (e) { return href.slice(2) }
  }

  MouseArea {
    id: area
    anchors.fill: parent
    hoverEnabled: true
    acceptedButtons: Qt.LeftButton
    property string hoverLink: ""
    cursorShape: hoverLink !== "" ? Qt.PointingHandCursor : Qt.ArrowCursor
    onPositionChanged: function(mouse) { hoverLink = root.linkAt(mouse.x, mouse.y) }
    onExited: hoverLink = ""
    onClicked: function(mouse) {
      var link = root.linkAt(mouse.x, mouse.y)
      var word = root.wordFromHref(link)
      if (mouse.modifiers & Qt.ControlModifier) {
        if (word) root.searchWord(word)
        mouse.accepted = true
      } else if (mouse.modifiers & Qt.AltModifier) {
        if (root.copyWhole) root.copyText(root.plainText)
        else if (word) root.copyText(word)
        mouse.accepted = true
      } else {
        mouse.accepted = false
      }
    }
  }
}
