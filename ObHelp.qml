import QtQuick
import QtQuick.Controls
import qs.Commons
import qs.Ui

// Help panel: every keyboard shortcut of the panel, grouped by topic, with a
// button that opens the project README on GitHub.
Item {
  id: root

  property color foreground: Color.menu.text
  property color accent: Color.accent
  readonly property color muted: Qt.darker(foreground, 1.45)
  property string fontFamily: Style.font.family
  property string documentationUrl: "https://github.com/muellan/omababel/blob/main/README.md"
  property string version: ""

  signal closeRequested()

  // { title, rows: [[keys, description], ...] }
  readonly property var sections: [
    {
      "title": "Search",
      "rows": [
        ["Enter", "Run the search"],
        ["Ctrl+L", "Focus the search field and select its content"],
        ["Ctrl+C  ·  Ctrl+Backspace", "Clear the search field and the results"],
        ["↓  ·  Ctrl+H", "Open the search history dropdown"],
        ["Ctrl+P  ·  Ctrl+N", "Previous / next entry from the history"],
        ["Esc", "Close the dropdown, leave the preferences, close the panel"]
      ]
    },
    {
      "title": "Modes and languages",
      "rows": [
        ["Ctrl+1  ·  Ctrl+2  ·  Ctrl+3", "Lookup · Thesaurus · Translate"],
        ["Ctrl+[", "Open the primary language selector"],
        ["Ctrl+]", "Open the target language selector (translate mode)"],
        ["Ctrl+S", "Swap the two languages"]
      ]
    },
    {
      "title": "Results",
      "rows": [
        ["Left click", "Look up the clicked word"],
        ["Right click", "Copy the clicked word (or a whole translation)"],
        ["Ctrl+J  ·  Ctrl+K", "Select the next / previous result card"],
        ["Ctrl+D  ·  Ctrl+U", "Scroll the result list down / up"],
        ["Ctrl+O", "Collapse or expand the selected card (double click does the same)"],
        ["Ctrl+Shift+I  ·  Ctrl+Shift+O", "Collapse / expand every card"],
        ["Ctrl+A  ·  Ctrl+Z", "Thesaurus mode: sort alphabetically / by length"]
      ]
    },
    {
      "title": "Panel",
      "rows": [
        ["Ctrl+.", "Show this help"],
        ["Ctrl+,", "Open the preferences (sources, data, history)"]
      ]
    }
  ]

  Column {
    id: layout
    anchors.fill: parent
    spacing: Style.spacing.md

    Row {
      id: topRow
      width: parent.width
      spacing: Style.spacing.md
      Button {
        id: docButton
        anchors.verticalCenter: parent.verticalCenter
        text: "Documentation"
        iconText: "󰈙"
        iconSize: Style.font.body
        bordered: true
        tooltipText: root.documentationUrl
        foreground: root.foreground
        accent: root.accent
        onClicked: Qt.openUrlExternally(root.documentationUrl)
      }
      Text {
        anchors.verticalCenter: parent.verticalCenter
        textFormat: Text.PlainText
        text: "Opens the README of the plugin repository in the browser."
          + (root.version !== "" ? "   ·   version " + root.version : "")
        color: root.muted
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
      }
    }

    Flickable {
      id: helpFlick
      width: parent.width
      height: layout.height - topRow.height - layout.spacing
      contentWidth: width
      contentHeight: helpCol.implicitHeight
      clip: true
      boundsBehavior: Flickable.StopAtBounds
      ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

      Column {
        id: helpCol
        width: helpFlick.width - Style.spacing.md
        spacing: Style.spacing.lg

        Repeater {
          model: root.sections
          delegate: Column {
            id: section
            required property var modelData
            width: parent.width
            spacing: Style.spacing.xs

            Text {
              textFormat: Text.PlainText
              text: section.modelData.title
              color: root.foreground
              font.family: root.fontFamily
              font.pixelSize: Style.font.subtitle
              font.bold: true
              bottomPadding: Style.spacing.xxs
            }

            Repeater {
              model: section.modelData.rows
              delegate: Row {
                id: shortcutRow
                required property var modelData
                width: parent.width
                spacing: Style.spacing.lg
                Text {
                  textFormat: Text.PlainText
                  text: shortcutRow.modelData[0]
                  color: root.accent
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.body
                  width: Math.round(shortcutRow.width * 0.32)
                  elide: Text.ElideRight
                }
                Text {
                  textFormat: Text.PlainText
                  text: shortcutRow.modelData[1]
                  color: root.foreground
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.body
                  width: shortcutRow.width - Math.round(shortcutRow.width * 0.32) - Style.spacing.lg
                  wrapMode: Text.WordWrap
                }
              }
            }
          }
        }

        Text {
          width: parent.width
          textFormat: Text.PlainText
          wrapMode: Text.WordWrap
          text: "Open the panel from anywhere with:  omarchy-shell shell toggle muellan.omababel '{}'"
          color: root.muted
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
          topPadding: Style.spacing.md
        }
      }
    }
  }
}
