import QtQuick
import QtQuick.Controls
import qs.Commons
import qs.Ui

// Renders one search result (lookup / thesaurus / translate).
// lookup:     one card per source, entries with numbered senses
// thesaurus:  consolidated alphabetical synonym + antonym chip lists
// translate:  one card per translator – word pairs or full text
Item {
  id: root

  property var result: null
  property string mode: "lookup"
  property bool searching: false
  property color foreground: Color.menu.text
  property color accent: Color.accent
  readonly property color muted: Qt.darker(foreground, 1.45)
  readonly property color okColor: Color.accent
  readonly property color errorColor: Color.urgent
  property string fontFamily: Style.font.family

  signal searchWord(string word)
  signal copyText(string text)
  signal installRequested(string dataset)

  function scrollToTop() { flick.contentY = 0 }

  function isEmpty() {
    if (!result) return true
    var rs = result.results || []
    for (var i = 0; i < rs.length; i++) if (rs[i].count > 0) return false
    return true
  }

  function sourceLine(r) {
    if (!r.ok) return "error"
    if (root.mode === "lookup") return r.count + (r.count === 1 ? " entry" : " entries")
    if (root.mode === "thesaurus") return (r.synonyms ? r.synonyms.length : 0) + " syn · " + (r.antonyms ? r.antonyms.length : 0) + " ant"
    return r.count + (r.count === 1 ? " result" : " results")
  }

  // ---------------------------------------------------------- components
  component SectionHeader: Row {
    property string title: ""
    property string detail: ""
    property bool ok: true
    property string url: ""
    spacing: Style.spacing.md
    width: parent.width
    Text {
      textFormat: Text.PlainText
      text: parent.title
      color: root.foreground
      font.family: root.fontFamily
      font.pixelSize: Style.font.subtitle
      font.bold: true
    }
    Text {
      textFormat: Text.PlainText
      text: parent.detail
      color: parent.ok ? root.muted : root.errorColor
      font.family: root.fontFamily
      font.pixelSize: Style.font.caption
      anchors.baseline: parent.children[0].baseline
    }
    Item { width: Math.max(0, parent.width - parent.children[0].width - parent.children[1].width - openLink.width - Style.spacing.md * 3); height: 1 }
    Text {
      id: openLink
      visible: parent.url !== ""
      textFormat: Text.PlainText
      text: "open ↗"
      color: root.muted
      font.family: root.fontFamily
      font.pixelSize: Style.font.caption
      anchors.baseline: parent.children[0].baseline
      MouseArea {
        anchors.fill: parent
        cursorShape: Qt.PointingHandCursor
        onClicked: Qt.openUrlExternally(parent.parent.url)
      }
    }
  }

  component Card: BorderSurface {
    default property alias content: inner.data
    width: parent.width
    implicitHeight: inner.implicitHeight + Style.spacing.lg * 2
    radius: Style.cornerRadius
    color: Style.normalFillFor(root.foreground, root.accent)
    borderSpec: Border.controlSpec("normal", root.foreground, root.accent)
    Column {
      id: inner
      x: Style.spacing.lg
      y: Style.spacing.lg
      width: parent.width - Style.spacing.lg * 2
      spacing: Style.spacing.sm
    }
  }

  component Hint: Text {
    width: parent.width
    textFormat: Text.PlainText
    wrapMode: Text.WordWrap
    color: root.muted
    font.family: root.fontFamily
    font.pixelSize: Style.font.bodySmall
  }

  Flickable {
    id: flick
    anchors.fill: parent
    contentWidth: width
    contentHeight: column.implicitHeight + Style.spacing.lg
    clip: true
    boundsBehavior: Flickable.StopAtBounds
    ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

    Column {
      id: column
      width: flick.width - Style.spacing.md
      spacing: Style.spacing.lg

      // ------------------------------------------------------ empty states
      Hint {
        visible: root.result === null && !root.searching
        text: "Type a word or phrase and press Enter.\n\nCtrl+click a word in the results to look it up · Alt+click copies it."
        horizontalAlignment: Text.AlignHCenter
        topPadding: Style.spacing.huge
      }
      Hint {
        visible: root.searching
        text: "Searching…"
        horizontalAlignment: Text.AlignHCenter
        topPadding: Style.spacing.huge
      }
      Hint {
        visible: !!(root.result && !root.searching && root.isEmpty() && !(root.result.results && root.result.results.length > 0))
        text: root.result && root.result.skipped && root.result.skipped.length > 0
          ? "No enabled source covers this language yet. " + root.result.skipped.length + " local source(s) are not installed – open the preferences (⚙) to download dictionary data."
          : "No source is configured for this language and mode. Open the preferences (⚙) to add or enable sources."
        horizontalAlignment: Text.AlignHCenter
        topPadding: Style.spacing.huge
      }

      // -------------------------------------------------------- thesaurus
      Column {
        visible: root.mode === "thesaurus" && !!root.result && !root.searching && !!root.result.consolidated
        width: parent.width
        spacing: Style.spacing.lg

        Column {
          width: parent.width
          spacing: Style.spacing.sm
          Text {
            textFormat: Text.PlainText
            text: "Synonyms" + (root.result && root.result.consolidated ? "  (" + root.result.consolidated.synonyms.length + ")" : "")
            color: root.foreground
            font.family: root.fontFamily
            font.pixelSize: Style.font.title
            font.bold: true
          }
          Hint {
            visible: !!(root.result && root.result.consolidated && root.result.consolidated.synonyms.length === 0)
            text: "No synonyms found."
          }
          Flow {
            width: parent.width
            spacing: Style.spacing.sm
            Repeater {
              model: root.result && root.result.consolidated ? root.result.consolidated.synonyms : []
              delegate: ObChip {
                required property var modelData
                word: modelData
                foreground: root.foreground
                accent: root.accent
                onSearchWord: function(w) { root.searchWord(w) }
                onCopyText: function(t) { root.copyText(t) }
              }
            }
          }
        }

        Column {
          width: parent.width
          spacing: Style.spacing.sm
          Text {
            textFormat: Text.PlainText
            text: "Antonyms" + (root.result && root.result.consolidated ? "  (" + root.result.consolidated.antonyms.length + ")" : "")
            color: root.foreground
            font.family: root.fontFamily
            font.pixelSize: Style.font.title
            font.bold: true
          }
          Hint {
            visible: !!(root.result && root.result.consolidated && root.result.consolidated.antonyms.length === 0)
            text: "No antonyms found."
          }
          Flow {
            width: parent.width
            spacing: Style.spacing.sm
            Repeater {
              model: root.result && root.result.consolidated ? root.result.consolidated.antonyms : []
              delegate: ObChip {
                required property var modelData
                word: modelData
                foreground: root.foreground
                accent: root.accent
                onSearchWord: function(w) { root.searchWord(w) }
                onCopyText: function(t) { root.copyText(t) }
              }
            }
          }
        }

        // per-source status line
        Column {
          width: parent.width
          spacing: Style.spacing.xs
          Repeater {
            model: root.result ? root.result.results : []
            delegate: Row {
              required property var modelData
              spacing: Style.spacing.md
              Text {
                textFormat: Text.PlainText
                text: (modelData.ok ? "✔ " : "✘ ") + modelData.source.name + "  ·  " + root.sourceLine(modelData)
                color: modelData.ok ? root.muted : root.errorColor
                font.family: root.fontFamily
                font.pixelSize: Style.font.caption
              }
              Text {
                visible: !modelData.ok
                textFormat: Text.PlainText
                text: modelData.error
                color: root.errorColor
                font.family: root.fontFamily
                font.pixelSize: Style.font.caption
                elide: Text.ElideRight
                width: Math.max(80, column.width - parent.children[0].width - Style.spacing.md * 2)
              }
            }
          }
        }
      }

      // ------------------------------------------------- lookup / translate
      Repeater {
        model: root.result && !root.searching && root.mode !== "thesaurus" ? root.result.results : []
        delegate: Card {
          id: card
          required property var modelData
          required property int index

          SectionHeader {
            title: card.modelData.source.name
            detail: root.sourceLine(card.modelData) + (card.modelData.ms !== undefined ? "  ·  " + card.modelData.ms + " ms" : "")
            ok: card.modelData.ok
            url: card.modelData.url || ""
          }

          Text {
            visible: !card.modelData.ok
            width: parent.width
            textFormat: Text.PlainText
            wrapMode: Text.WordWrap
            text: card.modelData.error || ""
            color: root.errorColor
            font.family: root.fontFamily
            font.pixelSize: Style.font.bodySmall
          }

          Hint {
            visible: card.modelData.ok && card.modelData.count === 0
            text: "No match."
          }

          // ---- lookup entries
          Repeater {
            model: root.mode === "lookup" && card.modelData.entries ? card.modelData.entries : []
            delegate: Column {
              id: entryCol
              required property var modelData
              required property int index
              width: parent.width
              spacing: Style.spacing.xs
              topPadding: index > 0 ? Style.spacing.md : 0

              Row {
                width: parent.width
                spacing: Style.spacing.md
                ObLinkText {
                  text: "<b>" + (entryCol.modelData.headword_html || "") + "</b>"
                  font.pixelSize: Style.font.title
                  color: root.foreground
                  onSearchWord: function(w) { root.searchWord(w) }
                  onCopyText: function(t) { root.copyText(t) }
                }
                Text {
                  visible: entryCol.modelData.pos !== ""
                  textFormat: Text.PlainText
                  text: entryCol.modelData.pos
                  color: root.muted
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.body
                  font.italic: true
                  anchors.baseline: parent.children[0].baseline
                }
                Text {
                  visible: entryCol.modelData.pronunciation !== ""
                  textFormat: Text.PlainText
                  text: "[" + entryCol.modelData.pronunciation + "]"
                  color: root.muted
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.body
                  anchors.baseline: parent.children[0].baseline
                }
              }

              Repeater {
                model: entryCol.modelData.senses || []
                delegate: Column {
                  id: senseCol
                  required property var modelData
                  required property int index
                  width: parent.width
                  spacing: Style.spacing.xxs
                  leftPadding: Style.spacing.lg

                  Row {
                    width: parent.width - senseCol.leftPadding
                    spacing: Style.spacing.md
                    Text {
                      id: senseLabel
                      textFormat: Text.PlainText
                      text: senseCol.modelData.label ? senseCol.modelData.label : (senseCol.index + 1) + "."
                      color: root.muted
                      font.family: root.fontFamily
                      font.pixelSize: Style.font.body
                      width: Math.max(implicitWidth, Style.space(18))
                    }
                    ObLinkText {
                      width: parent.width - senseLabel.width - Style.spacing.md
                      text: (senseCol.modelData.gloss_html || "")
                        + (senseCol.modelData.tags && senseCol.modelData.tags.length
                            ? "  <font color=\"" + root.muted + "\"><i>[" + senseCol.modelData.tags.join(", ") + "]</i></font>" : "")
                      color: root.foreground
                      onSearchWord: function(w) { root.searchWord(w) }
                      onCopyText: function(t) { root.copyText(t) }
                    }
                  }
                  Repeater {
                    model: senseCol.modelData.examples_html || []
                    delegate: ObLinkText {
                      required property var modelData
                      width: senseCol.width - senseCol.leftPadding - Style.space(18) - Style.spacing.md
                      x: Style.space(18) + Style.spacing.md
                      text: "<i>» " + modelData + "</i>"
                      color: root.muted
                      font.pixelSize: Style.font.bodySmall
                      onSearchWord: function(w) { root.searchWord(w) }
                      onCopyText: function(t) { root.copyText(t) }
                    }
                  }
                  ObLinkText {
                    visible: (senseCol.modelData.synonyms_html || "") !== ""
                    width: senseCol.width - senseCol.leftPadding - Style.space(18) - Style.spacing.md
                    x: Style.space(18) + Style.spacing.md
                    text: "<font color=\"" + root.muted + "\">syn:</font> " + (senseCol.modelData.synonyms_html || "")
                    color: root.foreground
                    font.pixelSize: Style.font.bodySmall
                    onSearchWord: function(w) { root.searchWord(w) }
                    onCopyText: function(t) { root.copyText(t) }
                  }
                  ObLinkText {
                    visible: (senseCol.modelData.antonyms_html || "") !== ""
                    width: senseCol.width - senseCol.leftPadding - Style.space(18) - Style.spacing.md
                    x: Style.space(18) + Style.spacing.md
                    text: "<font color=\"" + root.muted + "\">ant:</font> " + (senseCol.modelData.antonyms_html || "")
                    color: root.foreground
                    font.pixelSize: Style.font.bodySmall
                    onSearchWord: function(w) { root.searchWord(w) }
                    onCopyText: function(t) { root.copyText(t) }
                  }
                }
              }

              Repeater {
                model: entryCol.modelData.extra_html || []
                delegate: ObLinkText {
                  required property var modelData
                  width: entryCol.width - Style.spacing.lg
                  x: Style.spacing.lg
                  text: "<font color=\"" + root.muted + "\">" + modelData.key + ":</font> " + modelData.value
                  color: root.foreground
                  font.pixelSize: Style.font.bodySmall
                  onSearchWord: function(w) { root.searchWord(w) }
                  onCopyText: function(t) { root.copyText(t) }
                }
              }
            }
          }

          // ---- translation: full text
          ObLinkText {
            visible: root.mode === "translate" && (card.modelData.text_html || "") !== ""
            width: parent.width
            text: card.modelData.text_html || ""
            plainText: card.modelData.text || ""
            copyWhole: true
            color: root.foreground
            font.pixelSize: Style.font.title
            onSearchWord: function(w) { root.searchWord(w) }
            onCopyText: function(t) { root.copyText(t) }
          }
          Hint {
            visible: root.mode === "translate" && (card.modelData.text_html || "") !== ""
            text: "Alt+click copies the whole translation" + (card.modelData.detected ? "  ·  detected: " + card.modelData.detected : "")
          }
          Repeater {
            model: root.mode === "translate" ? (card.modelData.alternatives_html || []) : []
            delegate: ObLinkText {
              required property var modelData
              width: card.width - Style.spacing.lg * 2
              text: "<font color=\"" + root.muted + "\">~</font> " + modelData
              color: root.foreground
              onSearchWord: function(w) { root.searchWord(w) }
              onCopyText: function(t) { root.copyText(t) }
            }
          }

          // ---- translation: word pairs
          Repeater {
            model: root.mode === "translate" ? (card.modelData.pairs || []) : []
            delegate: Item {
              id: pairRow
              required property var modelData
              required property int index
              width: parent.width
              implicitHeight: Math.max(srcText.implicitHeight, dstText.implicitHeight, posText.implicitHeight) + Style.spacing.xs
              readonly property real half: (width - posText.width - Style.spacing.md * 2 - arrow.width) / 2

              ObLinkText {
                id: srcText
                x: 0
                width: pairRow.half
                text: pairRow.modelData.src_html || ""
                plainText: pairRow.modelData.src || ""
                copyWhole: true
                color: root.foreground
                onSearchWord: function(w) { root.searchWord(w) }
                onCopyText: function(t) { root.copyText(t) }
              }
              Text {
                id: arrow
                x: srcText.width + Style.spacing.md
                textFormat: Text.PlainText
                text: "→"
                color: root.muted
                font.family: root.fontFamily
                font.pixelSize: Style.font.body
              }
              ObLinkText {
                id: dstText
                x: arrow.x + arrow.width + Style.spacing.md
                width: pairRow.half
                text: (pairRow.modelData.dst_html || "")
                  + (pairRow.modelData.note_html ? "  <font color=\"" + root.muted + "\">" + pairRow.modelData.note_html + "</font>" : "")
                plainText: pairRow.modelData.dst || ""
                copyWhole: true
                color: root.foreground
                onSearchWord: function(w) { root.searchWord(w) }
                onCopyText: function(t) { root.copyText(t) }
              }
              Text {
                id: posText
                anchors.right: parent.right
                textFormat: Text.PlainText
                text: pairRow.modelData.pos || ""
                color: root.muted
                font.family: root.fontFamily
                font.pixelSize: Style.font.caption
                font.italic: true
                width: text === "" ? 0 : Math.min(implicitWidth, Style.space(140))
                elide: Text.ElideRight
              }
            }
          }
        }
      }

      // ---------------------------------------------- not-installed notice
      Column {
        visible: !!(root.result && !root.searching && root.result.skipped && root.result.skipped.length > 0)
        width: parent.width
        spacing: Style.spacing.xs
        Hint {
          text: "Not installed (open ⚙ → Data to download): "
            + (root.result && root.result.skipped ? root.result.skipped.map(function(s) { return s.name }).join(", ") : "")
        }
      }
    }
  }
}
