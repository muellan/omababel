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

  // thesaurus word order inside groups: "alpha" (default) or "length"
  property string sortMode: "alpha"

  // ---- keyboard-traversable card list
  // Cards are produced by three delegates (thesaurus groups, the "All
  // meanings" overview, and one card per source in lookup / translate); each
  // one gets a running cardIndex so selection and collapsing can address them
  // uniformly.
  property int selectedCard: -1
  property var collapsedCards: ({})
  readonly property int groupCount: (root.mode === "thesaurus" && root.result && root.result.consolidated)
    ? root.result.consolidated.groups.length : 0
  readonly property bool overviewVisible: root.mode === "thesaurus" && !!root.result && !!root.result.consolidated
    && root.result.consolidated.groups.length !== 1
  // A function rather than an inline expression: resetCards() needs the count
  // for the result that just arrived, and a sibling binding is not guaranteed
  // to have been re-evaluated when the change handler runs.
  function countCards() {
    if (root.mode === "thesaurus") {
      if (!root.result || !root.result.consolidated) return 0
      var groups = root.result.consolidated.groups.length
      return groups + (groups !== 1 ? 1 : 0)
    }
    return (root.result && root.result.results) ? root.result.results.length : 0
  }
  readonly property int cardCount: root.countCards()
  // cardIndex -> Card item, for scrolling the selection into view.  Not used
  // in bindings, so it is mutated in place.
  property var cardItems: ({})

  signal searchWord(string word)
  signal copyText(string text)
  signal installRequested(string dataset)
  signal sortRequested(string mode)

  onResultChanged: root.resetCards()
  onModeChanged: root.resetCards()

  function resetCards() {
    root.collapsedCards = ({})
    root.cardItems = ({})
    root.selectedCard = root.countCards() > 0 ? 0 : -1
  }

  function registerCard(index, item) { root.cardItems[index] = item }

  function isCollapsed(index) { return root.collapsedCards[index] === true }

  function setCollapsed(index, collapsed) {
    if (index < 0 || index >= root.countCards()) return
    var next = ({})
    for (var k in root.collapsedCards) next[k] = root.collapsedCards[k]
    if (collapsed) next[index] = true
    else delete next[index]
    root.collapsedCards = next
  }

  function toggleCollapsed(index) { root.setCollapsed(index, !root.isCollapsed(index)) }

  function setAllCollapsed(collapsed) {
    var next = ({})
    if (collapsed) for (var i = 0; i < root.countCards(); i++) next[i] = true
    root.collapsedCards = next
  }

  // Ctrl+O and a double click on a card toggle the selected card.
  function toggleSelected() {
    if (root.selectedCard < 0 && root.countCards() > 0) root.selectedCard = 0
    root.toggleCollapsed(root.selectedCard)
    root.showCard(root.selectedCard)
  }

  function collapseSelected(collapsed) {
    if (root.selectedCard < 0 && root.countCards() > 0) root.selectedCard = 0
    root.setCollapsed(root.selectedCard, collapsed)
    root.showCard(root.selectedCard)
  }

  // Ctrl+J / Ctrl+K walk the cards.
  function stepCard(delta) {
    var count = root.countCards()
    if (count === 0) return
    var next = root.selectedCard < 0 ? (delta > 0 ? 0 : count - 1) : root.selectedCard + delta
    root.selectedCard = Math.max(0, Math.min(count - 1, next))
    root.showCard(root.selectedCard)
  }

  function selectCard(index) {
    if (index < 0 || index >= root.countCards()) return
    root.selectedCard = index
  }

  function showCard(index) {
    var item = root.cardItems[index]
    if (!item || !item.visible) return
    var top = item.mapToItem(column, 0, 0).y
    var bottom = top + item.height
    if (top < flick.contentY) flick.contentY = Math.max(0, top - Style.spacing.md)
    else if (bottom > flick.contentY + flick.height)
      flick.contentY = Math.max(0, Math.min(flick.contentHeight - flick.height, bottom - flick.height + Style.spacing.md))
  }

  function sorted(words) {
    var out = (words || []).slice()
    if (root.sortMode === "length") {
      out.sort(function(a, b) {
        if (a.length !== b.length) return a.length - b.length
        return a.localeCompare(b, undefined, {sensitivity: "base"})
      })
    } else {
      out.sort(function(a, b) { return a.localeCompare(b, undefined, {sensitivity: "base"}) })
    }
    return out
  }

  function scrollToTop() { flick.contentY = 0 }

  // Ctrl+D / Ctrl+U: move by a fraction of the visible height.
  function scrollBy(fraction) {
    var max = Math.max(0, flick.contentHeight - flick.height)
    flick.contentY = Math.max(0, Math.min(max, flick.contentY + flick.height * fraction))
  }

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
  // A result card: header row (title, detail, optional web link, collapse
  // arrow) plus the caller's content, which the arrow hides.  The selected
  // card is marked with a brighter border.
  component Card: BorderSurface {
    id: cardRoot
    default property alias content: inner.data
    property int cardIndex: -1
    property string title: ""
    property string detail: ""
    property string detailPlain: ""      // detail rendered in the muted colour
    property bool ok: true
    property string url: ""
    property bool collapsible: true
    readonly property bool selected: root.selectedCard === cardRoot.cardIndex
    readonly property bool collapsed: cardRoot.collapsible && root.isCollapsed(cardRoot.cardIndex)

    width: parent.width
    implicitHeight: head.height + (cardRoot.collapsed ? 0 : inner.implicitHeight + Style.spacing.sm) + Style.spacing.lg * 2
    radius: Style.cornerRadius
    color: cardRoot.selected ? Style.hoverFillFor(root.foreground, root.accent)
                             : Style.normalFillFor(root.foreground, root.accent)
    borderSpec: cardRoot.selected
      ? Border.flat(Style.selectedBorderFor(root.foreground, root.accent), Math.max(1, Style.normalBorderWidth))
      : Border.controlSpec("normal", root.foreground, root.accent)

    Component.onCompleted: if (cardIndex >= 0) root.registerCard(cardIndex, cardRoot)

    // Clicking anywhere on the card selects it, a double click folds it away.
    // Chips, links and buttons sit above this area and keep their own clicks.
    MouseArea {
      anchors.fill: parent
      acceptedButtons: Qt.LeftButton
      propagateComposedEvents: true
      onPressed: function(mouse) { root.selectCard(cardRoot.cardIndex) }
      onDoubleClicked: function(mouse) {
        if (cardRoot.collapsible) root.toggleCollapsed(cardRoot.cardIndex)
      }
    }

    Item {
      id: head
      x: Style.spacing.lg
      y: Style.spacing.lg
      width: parent.width - Style.spacing.lg * 2
      height: Math.max(titleText.implicitHeight, collapseButton.implicitHeight)

      Row {
        anchors.left: parent.left
        anchors.right: headActions.left
        anchors.rightMargin: Style.spacing.md
        anchors.verticalCenter: parent.verticalCenter
        spacing: Style.spacing.md
        Text {
          id: titleText
          textFormat: Text.PlainText
          text: cardRoot.title
          color: root.foreground
          font.family: root.fontFamily
          font.pixelSize: Style.font.subtitle
          font.bold: true
          elide: Text.ElideRight
          width: Math.min(implicitWidth, head.width * 0.6)
        }
        Text {
          textFormat: Text.PlainText
          text: cardRoot.detail
          color: cardRoot.ok ? root.muted : root.errorColor
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
          anchors.baseline: titleText.baseline
          elide: Text.ElideRight
          width: Math.min(implicitWidth, Math.max(0, head.width * 0.4))
        }
      }

      Row {
        id: headActions
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        spacing: Style.spacing.xs
        Button {
          visible: cardRoot.url !== ""
          text: "open ↗"
          fontSize: Style.font.caption
          tooltipText: "open in the browser"
          verticalPadding: Style.spacing.xxs
          foreground: root.muted
          accent: root.accent
          onClicked: Qt.openUrlExternally(cardRoot.url)
        }
        Button {
          id: collapseButton
          visible: cardRoot.collapsible
          iconText: cardRoot.collapsed ? "󰅀" : "󰅃"
          iconSize: Style.font.body
          tooltipText: cardRoot.collapsed ? "Expand (Ctrl+O)" : "Collapse (Ctrl+I)"
          verticalPadding: Style.spacing.xxs
          foreground: root.foreground
          accent: root.accent
          onClicked: {
            root.selectCard(cardRoot.cardIndex)
            root.toggleCollapsed(cardRoot.cardIndex)
          }
        }
      }
    }

    Column {
      id: inner
      x: Style.spacing.lg
      y: head.y + head.height + Style.spacing.sm
      width: parent.width - Style.spacing.lg * 2
      visible: !cardRoot.collapsed
      spacing: Style.spacing.sm
    }
  }

  // "Synonyms (n)" label followed by a flow of word chips; hidden when empty.
  component WordSection: Column {
    property string title: ""
    property var words: []
    visible: words.length > 0
    width: parent.width
    spacing: Style.spacing.xs
    Text {
      textFormat: Text.PlainText
      text: parent.title + "  (" + parent.words.length + ")"
      color: root.muted
      font.family: root.fontFamily
      font.pixelSize: Style.font.caption
      font.bold: true
    }
    Flow {
      width: parent.width
      spacing: Style.spacing.sm
      Repeater {
        model: parent.parent.words
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

  component Hint: Text {
    width: parent.width
    textFormat: Text.PlainText
    wrapMode: Text.WordWrap
    color: root.muted
    font.family: root.fontFamily
    font.pixelSize: Style.font.bodySmall
  }

  // ------------------------------------------------------- card toolbar
  // Pinned above the list so it stays reachable while scrolling.
  Row {
    id: cardToolbar
    anchors.top: parent.top
    anchors.left: parent.left
    anchors.right: parent.right
    visible: root.cardCount > 0 && !root.searching
    height: visible ? implicitHeight : 0
    spacing: Style.spacing.md

    Button {
      id: collapseAllButton
      text: "Collapse all"
      iconText: "󰅃"
      iconSize: Style.font.body
      fontSize: Style.font.bodySmall
      bordered: true
      tooltipText: "Collapse every card (Ctrl+Shift+I)"
      foreground: root.foreground
      accent: root.accent
      onClicked: root.setAllCollapsed(true)
    }
    Button {
      id: expandAllButton
      text: "Expand all"
      iconText: "󰅀"
      iconSize: Style.font.body
      fontSize: Style.font.bodySmall
      bordered: true
      tooltipText: "Expand every card (Ctrl+Shift+O)"
      foreground: root.foreground
      accent: root.accent
      onClicked: root.setAllCollapsed(false)
    }

    Item {
      width: Math.max(0, cardToolbar.width - collapseAllButton.width - expandAllButton.width
                          - (sortRow.visible ? sortRow.width : 0) - Style.spacing.md * 3)
      height: 1
    }

    Row {
      id: sortRow
      visible: root.mode === "thesaurus"
      spacing: Style.spacing.md
      Text {
        textFormat: Text.PlainText
        text: "Sort"
        color: root.muted
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        anchors.verticalCenter: parent.verticalCenter
      }
      ButtonGroup {
        options: [{value: "alpha", label: "A–Z", tooltip: "Sort alphabetically (Ctrl+A)"},
                  {value: "length", label: "Length", tooltip: "Sort by word length (Ctrl+Z)"}]
        value: root.sortMode
        foreground: root.foreground
        background: "transparent"
        accent: root.accent
        fontSize: Style.font.bodySmall
        onChanged: function(v) { root.sortRequested(v) }
      }
    }
  }

  Flickable {
    id: flick
    anchors.left: parent.left
    anchors.right: parent.right
    anchors.bottom: parent.bottom
    // the toolbar stays put while the list scrolls underneath it
    anchors.top: cardToolbar.visible ? cardToolbar.bottom : parent.top
    anchors.topMargin: cardToolbar.visible ? Style.spacing.md : 0
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
        text: "Type a word or phrase and press Enter.\n\nClick a word in the results to look it up · right-click copies it."
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
          ? "No enabled source covers this language yet. " + root.result.skipped.length + " local source(s) are not installed – open the preferences (󰒓) to download dictionary data."
          : "No source is configured for this language and mode. Open the preferences (󰒓) to add or enable sources."
        horizontalAlignment: Text.AlignHCenter
        topPadding: Style.spacing.huge
      }

      // -------------------------------------------------------- thesaurus
      Column {
        visible: root.mode === "thesaurus" && !!root.result && !root.searching && !!root.result.consolidated
        width: parent.width
        spacing: Style.spacing.lg

        // one block per meaning, in source order (thesaurus.com style)
        Repeater {
          model: root.result && root.result.consolidated ? root.result.consolidated.groups : []
          delegate: Card {
            id: groupCard
            required property var modelData
            required property int index
            cardIndex: index
            title: modelData.label ? modelData.label : "Meaning " + (index + 1)
            detail: (modelData.pos ? modelData.pos + "  ·  " : "") + modelData.source

            WordSection {
              title: "Synonyms"
              words: root.sorted(groupCard.modelData.synonyms)
            }
            WordSection {
              title: "Antonyms"
              words: root.sorted(groupCard.modelData.antonyms)
            }
          }
        }

        // everything merged, for a quick overview
        Card {
          visible: root.overviewVisible
          cardIndex: root.groupCount
          title: "All meanings"
          detail: root.result && root.result.consolidated
            ? root.result.consolidated.synonyms.length + " syn · " + root.result.consolidated.antonyms.length + " ant" : ""
          Hint {
            visible: !!(root.result && root.result.consolidated && root.result.consolidated.synonyms.length === 0
                        && root.result.consolidated.antonyms.length === 0)
            text: "No synonyms or antonyms found."
          }
          WordSection {
            title: "Synonyms"
            words: root.result && root.result.consolidated ? root.sorted(root.result.consolidated.synonyms) : []
          }
          WordSection {
            title: "Antonyms"
            words: root.result && root.result.consolidated ? root.sorted(root.result.consolidated.antonyms) : []
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
          cardIndex: index

          // Geometry of the translation columns – computed once per card so
          // all of its rows share it.
          readonly property bool pairsHavePos: {
            var ps = (root.mode === "translate" && modelData.pairs) ? modelData.pairs : []
            for (var i = 0; i < ps.length; i++) if (ps[i].pos) return true
            return false
          }
          readonly property real pairContentWidth: width - Style.spacing.lg * 2
          readonly property real pairArrowWidth: Style.space(18)
          readonly property real pairPosWidth: pairsHavePos ? Style.space(80) : 0
          readonly property real pairSrcWidth: Math.floor((pairContentWidth - pairArrowWidth - pairPosWidth
            - Style.spacing.md * (pairsHavePos ? 3 : 2)) * 0.5)
          readonly property real pairDstWidth: pairContentWidth - pairSrcWidth - pairArrowWidth - pairPosWidth
            - Style.spacing.md * (pairsHavePos ? 3 : 2)
          title: modelData.source.name
          detail: root.sourceLine(modelData) + (modelData.ms !== undefined ? "  ·  " + modelData.ms + " ms" : "")
          ok: modelData.ok
          url: modelData.url || ""

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

              // Headword, part of speech and IPA on one line.  Rich text
              // with wrapping enabled lays out at its minimum width inside a
              // Row – one character per line – so the headword is explicitly
              // unwrapped and sized to its own content.
              Row {
                id: headRow
                width: parent.width
                spacing: Style.spacing.md
                ObLinkText {
                  id: headword
                  html: "<b>" + (entryCol.modelData.headword_html || "") + "</b>"
                  font.pixelSize: Style.font.title
                  color: root.foreground
                  wrapMode: Text.NoWrap
                  elide: Text.ElideRight
                  width: Math.min(implicitWidth, Math.max(Style.space(80), headRow.width * 0.55))
                  onSearchWord: function(w) { root.searchWord(w) }
                  onCopyText: function(t) { root.copyText(t) }
                }
                Text {
                  id: headPos
                  visible: entryCol.modelData.pos !== ""
                  textFormat: Text.PlainText
                  text: entryCol.modelData.pos
                  color: root.muted
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.body
                  font.italic: true
                  anchors.baseline: headword.baseline
                }
                Item {   // gap between the word (with its pos) and the IPA
                  width: entryCol.modelData.pronunciation !== "" ? Style.spacing.huge : 0
                  height: 1
                }
                Text {
                  visible: entryCol.modelData.pronunciation !== ""
                  textFormat: Text.PlainText
                  text: "[" + entryCol.modelData.pronunciation + "]"
                  color: root.muted
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.body
                  anchors.baseline: headword.baseline
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
                      html: (senseCol.modelData.gloss_html || "")
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
                      html: "<i>» " + modelData + "</i>"
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
                    html: "<font color=\"" + root.muted + "\">syn:</font> " + (senseCol.modelData.synonyms_html || "")
                    color: root.foreground
                    font.pixelSize: Style.font.bodySmall
                    onSearchWord: function(w) { root.searchWord(w) }
                    onCopyText: function(t) { root.copyText(t) }
                  }
                  ObLinkText {
                    visible: (senseCol.modelData.antonyms_html || "") !== ""
                    width: senseCol.width - senseCol.leftPadding - Style.space(18) - Style.spacing.md
                    x: Style.space(18) + Style.spacing.md
                    html: "<font color=\"" + root.muted + "\">ant:</font> " + (senseCol.modelData.antonyms_html || "")
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
                  html: "<font color=\"" + root.muted + "\">" + modelData.key + ":</font> " + modelData.value
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
            html: card.modelData.text_html || ""
            plainText: card.modelData.text || ""
            copyWhole: true
            color: root.foreground
            font.pixelSize: Style.font.title
            onSearchWord: function(w) { root.searchWord(w) }
            onCopyText: function(t) { root.copyText(t) }
          }
          Hint {
            visible: root.mode === "translate" && (card.modelData.text_html || "") !== ""
            text: "Right-click copies the whole translation" + (card.modelData.detected ? "  ·  detected: " + card.modelData.detected : "")
          }
          Repeater {
            model: root.mode === "translate" ? (card.modelData.alternatives_html || []) : []
            delegate: ObLinkText {
              required property var modelData
              width: card.width - Style.spacing.lg * 2
              html: "<font color=\"" + root.muted + "\">~</font> " + modelData
              color: root.foreground
              onSearchWord: function(w) { root.searchWord(w) }
              onCopyText: function(t) { root.copyText(t) }
            }
          }

          // ---- translation: word pairs
          // Two fixed columns (source | target) plus an optional part-of-speech
          // column.  Column widths come from the card, not from the row's own
          // content, so every arrow and every target entry line up; long
          // entries wrap inside their column instead of spilling under the
          // next row.  Wrapped rich text reports its real height in
          // contentHeight – implicitHeight is the unwrapped single line.
          Repeater {
            model: root.mode === "translate" ? (card.modelData.pairs || []) : []
            delegate: Item {
              id: pairRow
              objectName: "pairRow"
              required property var modelData
              required property int index
              width: parent.width
              implicitHeight: Math.max(srcText.contentHeight, dstText.contentHeight, posText.contentHeight)
                + Style.spacing.xs

              ObLinkText {
                id: srcText
                x: 0
                y: 0
                width: card.pairSrcWidth
                height: contentHeight
                html: pairRow.modelData.src_html || ""
                plainText: pairRow.modelData.src || ""
                copyWhole: true
                color: root.foreground
                onSearchWord: function(w) { root.searchWord(w) }
                onCopyText: function(t) { root.copyText(t) }
              }
              Text {
                id: arrow
                x: card.pairSrcWidth + Style.spacing.md
                y: 0
                width: card.pairArrowWidth
                textFormat: Text.PlainText
                text: "→"
                color: root.muted
                font.family: root.fontFamily
                font.pixelSize: Style.font.body
                horizontalAlignment: Text.AlignHCenter
              }
              ObLinkText {
                id: dstText
                objectName: "pairDst"
                x: card.pairSrcWidth + card.pairArrowWidth + Style.spacing.md * 2
                y: 0
                width: card.pairDstWidth
                height: contentHeight
                html: (pairRow.modelData.dst_html || "")
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
                y: 0
                visible: card.pairPosWidth > 0
                width: card.pairPosWidth
                textFormat: Text.PlainText
                text: pairRow.modelData.pos || ""
                color: root.muted
                font.family: root.fontFamily
                font.pixelSize: Style.font.caption
                font.italic: true
                horizontalAlignment: Text.AlignRight
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
        topPadding: Style.spacing.huge
        Hint {
          text: "Not installed (open 󰒓 → Data to download): "
            + (root.result && root.result.skipped ? root.result.skipped.map(function(s) { return s.name }).join(", ") : "")
        }
      }
    }
  }
}
