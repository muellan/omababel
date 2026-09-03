import QtQuick
import qs.Commons

// Rich text whose words are links (`<a href="w:...">`, produced by the
// backend).  Left click on a word starts a new search with it, right click
// copies it – or the whole text when `copyWhole` is set (full-text
// translations).  Links are painted in the theme foreground without
// underline, so the text reads like ordinary prose.
Text {
  id: root

  property bool copyWhole: false
  property string plainText: ""       // what a right click copies when copyWhole
  property color linkTint: color
  // Set `html` instead of `text`: the anchors get the theme colour and no
  // underline (Qt's rich text defaults are blue + underlined).
  property string html: ""

  signal searchWord(string word)
  signal copyText(string text)

  textFormat: Text.RichText
  wrapMode: Text.Wrap
  color: Color.menu.text
  linkColor: linkTint
  font.family: Style.font.family
  font.pixelSize: Style.font.body
  text: root.styled(html)

  function styled(markup) {
    if (!markup) return ""
    return markup.replace(/<a href=/g, '<a style="color:' + String(root.linkTint) + ';text-decoration:none" href=')
  }

  function wordFromHref(href) {
    if (!href || href.indexOf("w:") !== 0) return ""
    try { return decodeURIComponent(href.slice(2)) } catch (e) { return href.slice(2) }
  }

  MouseArea {
    id: area
    anchors.fill: parent
    hoverEnabled: true
    acceptedButtons: Qt.LeftButton | Qt.RightButton
    property string hoverLink: ""
    cursorShape: hoverLink !== "" ? Qt.PointingHandCursor : Qt.ArrowCursor
    onPositionChanged: function(mouse) { hoverLink = root.linkAt(mouse.x, mouse.y) }
    onExited: hoverLink = ""
    onClicked: function(mouse) {
      var link = root.linkAt(mouse.x, mouse.y)
      var word = root.wordFromHref(link)
      if (mouse.button === Qt.RightButton) {
        if (root.copyWhole) root.copyText(root.plainText)
        else if (word) root.copyText(word)
        mouse.accepted = true
      } else if (word) {
        root.searchWord(word)
        mouse.accepted = true
      } else {
        mouse.accepted = false
      }
    }
  }
}
