import QtQuick
import QtQuick.Window

// Offscreen smoke test for the panel QML.
//
// Loads the plugin's Omababel.qml (with Quickshell replaced by the stubs in
// tests/qml/stubs and `qs` pointing at an Omarchy shell checkout), feeds it
// state + result fixtures produced by the real backend and walks through
// every mode and the preferences panel.  Any QML error/warning printed
// while doing so fails the test (tests/run.sh greps stderr).
Item {
  id: harness
  width: 1400
  height: 900

  property string pluginDir: ""        // set via HARNESS_PLUGIN_DIR (see run.sh)
  property string fixtureDir: ""
  property int step: 0
  readonly property var stepOrder: [0, 1, 2, 3, 4, 5, 51, 52, 53, 54, 57, 58, 59, 60, 6, 7, 8, 9, 55, 56, 10, 11, 12, 13, 14]
  function stepId(i) { return i < stepOrder.length ? stepOrder[i] : 999 }
  property var panel: null
  property var manyResults: null

  function readJson(path) {
    var xhr = new XMLHttpRequest()
    xhr.open("GET", "file://" + path, false)
    xhr.send()
    return JSON.parse(xhr.responseText)
  }

  // Collect every descendant with the given objectName (geometry checks).
  function collect(item, name, out) {
    out = out || []
    if (!item) return out
    var kids = item.children || []
    for (var i = 0; i < kids.length; i++) {
      if (kids[i].objectName === name) out.push(kids[i])
      harness.collect(kids[i], name, out)
    }
    return out
  }

  function fail(msg) {
    console.error("HARNESS FAIL: " + msg)
    Qt.exit(1)
  }

  function check(cond, msg) {
    if (!cond) fail(msg)
  }

  Loader {
    id: loader
    source: harness.pluginDir + "/Omababel.qml"
    onStatusChanged: {
      if (status === Loader.Error) harness.fail("cannot load Omababel.qml: " + sourceComponent)
      if (status === Loader.Ready) {
        harness.panel = item
        item.shell = ({ hide: function(id) { console.log("shell.hide(" + id + ")") } })
        item.manifest = ({ id: "muellan.omababel" })
        stepper.start()
      }
    }
  }

  Timer {
    id: stepper
    interval: 150
    repeat: true
    onTriggered: {
      var p = harness.panel
      var fx = harness.fixtureDir
      try {
        // steps run in order; 51/52 are reached through the mapping below
        switch (harness.stepId(harness.step)) {
        case 0:
          p.open("{}")
          harness.check(p.opened === true, "open() sets opened")
          break
        case 1:
          p.applyState(harness.readJson(fx + "/state.json"), true)
          p.stateLoaded = true
          harness.check(p.languages.length > 10, "languages loaded")
          harness.check(p.sources.length > 10, "sources loaded")
          harness.check(p.mode === "lookup", "prefs mode applied")
          break
        case 2:
          p.mode = "lookup"
          p.result = harness.readJson(fx + "/lookup.json")
          harness.check(p.result.results.length > 0, "lookup result has sources")
          break
        case 3:
          p.mode = "thesaurus"
          p.result = harness.readJson(fx + "/thesaurus.json")
          harness.check(p.result.consolidated.synonyms.length > 0, "thesaurus synonyms present")
          harness.check(p.result.consolidated.groups.length > 1, "thesaurus meanings grouped")
          harness.check(p.resultsView.sorted(["bb", "a", "ccc"]).join(",") === "a,bb,ccc", "alphabetical sort")
          p.setThesaurusSort("length")
          harness.check(p.resultsView.sortMode === "length", "sort mode propagated")
          harness.check(p.resultsView.sorted(["ccc", "a", "bb", "dd"]).join(",") === "a,bb,dd,ccc", "length sort")
          p.setThesaurusSort("alpha")
          break
        case 4:
          p.mode = "translate"
          p.result = harness.readJson(fx + "/translate.json")
          break
        case 5:
          p.mode = "translate"
          p.result = harness.readJson(fx + "/translate_text.json")
          break
        case 51:
          // Word pairs: both columns are fixed per card, so every target entry
          // starts at the same x, and a long target wraps inside its column
          // instead of running under the next row.
          var long1 = harness.readJson(fx + "/translate.json")
          // The first card with pairs, not a fixed index: the remote sources
          // in the fixture failed offline and how many of them there are
          // depends on which ones ship enabled.
          var pairs = null
          for (var q = 0; q < long1.results.length && !pairs; q++)
            if (long1.results[q].pairs && long1.results[q].pairs.length) pairs = long1.results[q].pairs
          harness.check(!!pairs, "the fixture has a card with word pairs")
          var longWord = "ein sehr langes Übersetzungsergebnis mit ausgesprochen vielen Wörtern, "
                       + "das in seiner eigenen Spalte umbrechen muss und nicht unter die Quellspalte "
                       + "der nächsten Zeile laufen darf"
          pairs.push({src: "Haus", dst: longWord, pos: "noun", note: "",
                      src_html: "Haus", dst_html: longWord, note_html: ""})
          p.mode = "translate"
          p.result = long1
          p.searching = false
          break
        case 52:
          var rows = harness.collect(p.resultsView, "pairRow")
          var dsts = harness.collect(p.resultsView, "pairDst")
          harness.check(rows.length >= 2, "translation rows rendered: " + rows.length)
          harness.check(dsts.length === rows.length, "one target column per row")
          var x0 = dsts[0].x, w0 = dsts[0].width
          harness.check(w0 > 0, "target column has a width")
          for (var d = 1; d < dsts.length; d++) {
            harness.check(dsts[d].x === x0, "target column aligned (row " + d + ": " + dsts[d].x + " vs " + x0 + ")")
            harness.check(dsts[d].width === w0, "target column width equal (row " + d + ")")
          }
          var wrapped = -1
          for (var w = 0; w < dsts.length; w++)
            if (wrapped < 0 || dsts[w].contentHeight > dsts[wrapped].contentHeight) wrapped = w
          harness.check(dsts[wrapped].contentHeight > dsts[0].contentHeight,
                        "the long target wraps inside its column (" + dsts[wrapped].contentHeight + ")")
          harness.check(rows[wrapped].height >= dsts[wrapped].contentHeight,
                        "the row grows with the wrapped target")
          // the two columns are the same width, on every card: the card with
          // a part-of-speech column must lay out exactly like the one without
          for (var g = 0; g < rows.length; g++) {
            harness.check(Math.abs(rows[g].srcWidth - rows[g].dstWidth) <= 1,
                          "source and target column are equally wide (row " + g + ": "
                          + rows[g].srcWidth + " vs " + rows[g].dstWidth + ")")
            harness.check(rows[g].srcWidth === rows[0].srcWidth,
                          "columns identical across cards (row " + g + ")")
          }
          break
        case 53:
          // languages with no source for the current mode are dimmed
          p.coverage = ({lookup: {any: false, langs: ["de", "en"]},
                         thesaurus: {any: false, langs: ["en"]},
                         translate: {any: false, langs: ["de"], pairs: {de: ["en", "fr"]}}})
          p.mode = "thesaurus"
          harness.check(p.unservedLangs["de"] === true, "German dimmed in thesaurus mode")
          harness.check(p.unservedLangs["en"] === undefined, "English not dimmed in thesaurus mode")
          p.mode = "lookup"
          harness.check(p.unservedLangs["de"] === undefined, "German served in lookup mode")
          harness.check(p.unservedLangs["fr"] === true, "French dimmed in lookup mode")
          p.mode = "translate"
          p.lang = "de"
          harness.check(p.unservedTargetLangs["fr"] === undefined, "de->fr is served")
          harness.check(p.unservedTargetLangs["it"] === true, "de->it is not served")
          p.coverage = ({})
          harness.check(p.unservedLangs["fr"] === undefined, "nothing is dimmed without coverage data")
          p.mode = "lookup"
          break
        case 54:
          // the engaged mode chip is painted in the accent colour.  The test
          // theme uses the same colour for accent and foreground, so drive a
          // distinct accent through the selector to see the binding.
          p.setMode("thesaurus")
          var chips = harness.collect(p.modeSelector, "modeChip")
          harness.check(chips.length === 3, "three mode chips: " + chips.length)
          p.modeSelector.accent = "#ff00ff"
          var accented = 0, selected = 0
          for (var c = 0; c < chips.length; c++) {
            if (chips[c].selected) selected++
            harness.check(chips[c].selected === (String(chips[c].foreground) === "#ff00ff"),
                          "the accent marks exactly the engaged chip (chip " + c + ")")
            if (String(chips[c].foreground) === "#ff00ff") accented++
          }
          harness.check(selected === 1, "one chip is engaged: " + selected)
          harness.check(accented === 1, "exactly one chip carries the accent colour")
          // ... and its background is a dimmed, semi-transparent accent, not
          // a colour the theme pinned for the "selected" state
          for (var f = 0; f < chips.length; f++) {
            if (!chips[f].selected) continue
            harness.check(chips[f].fillColor.a > 0 && chips[f].fillColor.a < 0.6,
                          "the engaged chip's fill is semi-transparent: " + chips[f].fillColor.a)
            harness.check(chips[f].fillColor.r > 0.9 && chips[f].fillColor.b > 0.9
                          && chips[f].fillColor.g < 0.1,
                          "the engaged chip's fill is the accent hue: " + chips[f].fillColor)
          }
          p.modeSelector.accent = p.accent
          p.setMode("lookup")
          break
        case 57:
          // streamed results: the sources appear as pending cards and are
          // filled in one by one, in their final order
          var lookup57 = harness.readJson(fx + "/lookup.json")
          p.mode = "lookup"
          p.result = null
          p.searching = true
          p.applySearchEvent({event: "start", mode: "lookup", query: "Haus", lang: "de", lang2: "",
                              total: lookup57.results.length,
                              sources: lookup57.results.map(function(r) { return r.source }),
                              skipped: lookup57.skipped || []})
          harness.check(p.result !== null, "the start event lays the list out")
          harness.check(p.result.results.length === lookup57.results.length,
                        "one card per source from the start: " + p.result.results.length)
          harness.check(p.result.results[0].pending === true, "cards start out pending")
          harness.check(p.expected === lookup57.results.length && p.answered === 0, "nothing answered yet")
          harness.check(p.resultsView.cardCount === lookup57.results.length,
                        "the pending cards are rendered while the search runs")
          var pendingRows = harness.collect(p.resultsView, "pendingRow").filter(function(x) { return x.visible })
          harness.check(pendingRows.length === lookup57.results.length,
                        "every pending card says so: " + pendingRows.length)
          // the last source answers first: it must still land in its own slot
          var last57 = lookup57.results.length - 1
          p.applySearchEvent({event: "result", index: last57, total: lookup57.results.length,
                              result: lookup57.results[last57]})
          harness.check(p.result.results[last57].pending === undefined,
                        "the answered source is no longer pending")
          harness.check(p.result.results[0].pending === true, "the others still are")
          harness.check(p.answered === 1, "one source answered")
          harness.check(p.status.indexOf("still running") >= 0, "the status counts the rest: " + p.status)
          for (var r57 = 0; r57 < last57; r57++)
            p.applySearchEvent({event: "result", index: r57, total: lookup57.results.length,
                                result: lookup57.results[r57]})
          harness.check(p.answered === lookup57.results.length, "every source answered")
          harness.check(p.status.indexOf("still running") < 0, "the status stops counting: " + p.status)
          var stillPending = harness.collect(p.resultsView, "pendingRow").filter(function(x) { return x.visible })
          harness.check(stillPending.length === 0, "no card is pending any more")
          p.searching = false
          break
        case 58:
          // the busy indicator: accent coloured, spinning, and centred in the
          // gap between the mode chips and the language selectors
          var spinner = p.busyIndicator
          harness.check(!!spinner && spinner.objectName === "busySpinner", "the busy indicator exists")
          harness.check(!spinner.visible, "it is hidden while nothing runs")
          p.searching = true
          harness.check(spinner.visible, "it shows while a search runs")
          harness.check(String(spinner.color) === String(p.accent), "it is accent coloured")
          harness.check(spinner.text === "󰑐", "it is the refresh glyph")
          var modeRight = p.modeSelector.x + p.modeSelector.width
          var langLeft = p.langPickerView.mapToItem(p.modeSelector.parent, 0, 0).x
          var gapCentre = modeRight + (langLeft - modeRight) / 2
          harness.check(Math.abs(spinner.x + spinner.width / 2 - gapCentre) <= 2,
                        "centred in the gap: " + (spinner.x + spinner.width / 2) + " vs " + gapCentre)
          p.searching = false
          harness.check(!spinner.visible, "it goes away when the search is done")
          break
        case 59:
          // A streamed answer with enough cards to make the list scroll,
          // delivered exactly the way the backend delivers it: a start event
          // that lays the cards out, then one result per source.
          var many = harness.readJson(fx + "/lookup.json")
          var one = many.results[many.results.length - 1]
          for (var m = 0; m < 12; m++) {
            var copy = JSON.parse(JSON.stringify(one))
            copy.source = {id: "copy" + m, name: "Source " + m, type: "dictionary",
                           driver: "generic", kind: "remote"}
            many.results.push(copy)
          }
          harness.manyResults = many
          p.mode = "lookup"
          p.searching = true
          p.result = null
          p.applySearchEvent({event: "start", mode: "lookup", query: "Haus", lang: "de", lang2: "",
                              total: many.results.length,
                              sources: many.results.map(function(r) { return r.source }),
                              skipped: []})
          for (var e59 = 0; e59 < many.results.length; e59++)
            p.applySearchEvent({event: "result", index: e59, total: many.results.length,
                                result: many.results[e59]})
          p.searching = false
          break
        case 60:
          // Ctrl+J / Ctrl+K must scroll the selected card into view – the
          // cards were created once, on the start event, and every streamed
          // result since then replaced `result` without recreating them.
          var view = p.resultsView
          var rows60 = harness.manyResults.results.length
          view.layoutNow()      // offscreen: nothing polishes the list for us
          harness.check(view.cardCount === rows60, "all cards rendered: " + view.cardCount)
          harness.check(view.contentHeight > view.viewHeight,
                        "the list is longer than the view: " + view.contentHeight + " / " + view.viewHeight)
          harness.check(view.selectedCard === 0, "the first card is selected")
          harness.check(view.contentY === 0, "and the list starts at the top")
          for (var j = 0; j < rows60 - 1; j++) view.stepCard(1)
          harness.check(view.selectedCard === rows60 - 1, "the last card is selected")
          harness.check(view.contentY > 0, "the view followed the selection down: " + view.contentY)
          var atBottom = view.contentY
          var lastCard = view.cardAt(view.selectedCard)
          harness.check(!!lastCard, "the selected card is found")
          harness.check(lastCard.mapToItem(lastCard.parent, 0, 0).y + lastCard.height
                        <= view.contentY + view.viewHeight + 2 || lastCard.height >= view.viewHeight,
                        "the selected card is in view")
          for (var k = 0; k < rows60 - 1; k++) view.stepCard(-1)
          harness.check(view.selectedCard === 0, "back at the first card")
          harness.check(view.contentY < atBottom, "the view came back up: " + view.contentY)
          // a further streamed result keeps the selection where it is
          view.stepCard(1)
          view.stepCard(1)
          var kept = view.selectedCard
          p.applySearchEvent({event: "result", index: 0, total: rows60,
                              result: harness.manyResults.results[0]})
          harness.check(view.selectedCard === kept,
                        "a streamed update keeps the selection: " + view.selectedCard + " vs " + kept)
          view.layoutNow()
          for (var s60 = 0; s60 < rows60 - 1; s60++) view.stepCard(1)
          harness.check(view.contentY > 0,
                        "the view still follows the selection after an update: " + view.contentY)
          // a different query does start over
          var other = JSON.parse(JSON.stringify(harness.manyResults))
          other.query = "something else"
          p.result = other
          harness.check(view.selectedCard === 0, "a new query starts at the first card again")
          p.result = null
          break
        case 6:
          p.rememberHistory("Haus")
          p.rememberHistory("house")
          harness.check(p.history.length >= 2 && p.history[0].query === "house", "history bookkeeping")
          break
        case 7:
          p.openPrefs()
          harness.check(p.prefsOpen === true, "prefs open")
          break
        case 8:
          p.datasets = harness.readJson(fx + "/datasets.json").datasets
          p.localStatus = harness.readJson(fx + "/status.json").status
          // the data list puts what is installed first, both halves
          // alphabetical, with a line between them
          var prefs8 = p.prefsView
          prefs8.tab = "data"
          var rows = prefs8.sortedDatasets
          harness.check(rows.length === p.datasets.length, "every dataset is listed")
          var installedSeen = 0, previous = "", flipped = false
          for (var d = 0; d < rows.length; d++) {
            var title = prefs8.datasetTitle(rows[d]).toLowerCase()
            if (prefs8.datasetInstalled(rows[d])) {
              harness.check(!flipped, "no installed dataset after a missing one (" + title + ")")
              installedSeen++
            } else if (!flipped) {
              flipped = true
              previous = ""
            }
            harness.check(previous === "" || previous <= title,
                          "alphabetical within the group: " + previous + " / " + title)
            previous = title
          }
          harness.check(installedSeen === prefs8.installedCount(), "the installed count matches")
          var separators = harness.collect(p.prefsView, "notInstalledLabel").filter(function(x) { return x.visible })
          harness.check(separators.length === (installedSeen > 0 ? 1 : 0),
                        "one separator between the two halves: " + separators.length)
          if (separators.length) {
            var sepLabel = separators[0].children[0]
            var caption = harness.collect(p.prefsView, "filterSummary")[0]
            // the label reads at button size, not at the caption size the
            // rest of the metadata uses
            harness.check(sepLabel.font.pixelSize > caption.font.pixelSize,
                          "the separator label is larger than a caption: "
                          + sepLabel.font.pixelSize + " vs " + caption.font.pixelSize)
            harness.check(separators[0].parent.height > sepLabel.implicitHeight * 1.2,
                          "the two halves are set apart: " + separators[0].parent.height
                          + " around a " + sepLabel.implicitHeight + " label")
          }
          prefs8.tab = "sources"
          break
        case 9:
          // preferences editor: validation + field wiring
          var prefs = p.prefsView
          prefs.startNew()
          harness.check(prefs.tab === "edit" && prefs.editingNew, "editor opened for a new row")
          prefs.commitEdit()
          harness.check(prefs.message.indexOf("name") >= 0, "empty name rejected: " + prefs.message)
          prefs.nameInput.text = "My Dict"
          prefs.urlInput.text = "https://example.org/no-placeholder"
          prefs.commitEdit()
          harness.check(prefs.message.indexOf("{word}") >= 0, "missing {word} rejected: " + prefs.message)
          prefs.setEditField("type", "translator")
          harness.check(prefs.editing.type === "translator", "type switch")
          prefs.setEditField("kind", "local")
          harness.check(prefs.editing.driver === "local", "local kind selects local driver")
          prefs.setEditField("kind", "remote")
          prefs.setEditField("driver", "google")
          harness.check(prefs.editing.url.indexOf("translate.googleapis.com") >= 0, "driver default url applied")
          prefs.urlInput.text = "https://example.org/{word}"
          prefs.commitEdit()      // emits saveSource -> backend stub (no reply); must not throw
          prefs.startEdit(p.sources[0])
          harness.check(prefs.editing.id === p.sources[0].id && !prefs.editingNew, "edit existing row")
          // every field belongs to the row being edited: typing into one must
          // not leak into the next source, and the key field always starts
          // empty (the secret lives in the keyring, not in the UI)
          harness.check(prefs.nameInput.text === p.sources[0].name,
                        "name field initialised from the row: " + prefs.nameInput.text)
          prefs.keyInput.text = "sk-typed-secret"
          prefs.nameInput.text = "edited name"
          prefs.startEdit(p.sources[1])
          harness.check(prefs.keyInput.text === "", "the key field does not leak to the next source: "
                        + prefs.keyInput.text)
          harness.check(prefs.nameInput.text === p.sources[1].name,
                        "the name field follows the row: " + prefs.nameInput.text)
          harness.check(prefs.langInput.text === (p.sources[1].languages || []).join(", "),
                        "the languages field follows the row: " + prefs.langInput.text)
          prefs.startNew()
          harness.check(prefs.keyInput.text === "" && prefs.nameInput.text === "",
                        "a new row starts with empty fields")
          prefs.cancelEdit()
          harness.check(prefs.tab === "sources" && prefs.editing === null, "cancel returns to list")
          prefs.tab = "data"
          var requested = -1
          prefs.historyMaxRequested.connect(function(v) { requested = v })
          prefs.tab = "history"
          prefs.historyMaxRequested(250)
          harness.check(requested === 250, "history max request signal")
          harness.check(p.historyMax === 1000, "history max default")
          break
        case 55:
          // the sources filter bar: one toggle per property, all engaged by
          // default, and a Reset that puts them back
          var prefs55 = p.prefsView
          prefs55.tab = "sources"
          prefs55.resetFilters()
          harness.check(prefs55.filtersAreDefault, "everything is shown by default")
          harness.check(prefs55.visibleSources.length === p.sources.length, "no filter shows every source")
          harness.check(prefs55.canReorder, "reordering is allowed with everything shown")
          prefs55.showDisabled = false
          harness.check(!prefs55.filtersAreDefault, "the reset button lights up")
          harness.check(prefs55.visibleSources.length > 0, "some sources are enabled")
          for (var e = 0; e < prefs55.visibleSources.length; e++)
            harness.check(prefs55.visibleSources[e].enabled, "only enabled sources shown")
          harness.check(prefs55.canReorder, "reordering is allowed with all enabled sources shown")
          prefs55.showEnabled = false
          prefs55.showDisabled = true
          harness.check(!prefs55.canReorder, "reordering is refused with a partial list")
          for (var d2 = 0; d2 < prefs55.visibleSources.length; d2++)
            harness.check(!prefs55.visibleSources[d2].enabled, "only disabled sources shown")
          prefs55.showEnabled = true
          // two toggles combine: enabled AND thesaurus
          prefs55.showDictionary = false
          prefs55.showTranslator = false
          prefs55.showDisabled = false
          for (var t = 0; t < prefs55.visibleSources.length; t++) {
            harness.check(prefs55.visibleSources[t].type === "thesaurus", "only thesaurus sources shown")
            harness.check(prefs55.visibleSources[t].enabled, "... and only enabled ones")
          }
          harness.check(!prefs55.canReorder, "a type filter blocks reordering")
          prefs55.resetFilters()
          prefs55.filterGroup = "ai"
          harness.check(prefs55.visibleSources.length === 3, "three AI sources: " + prefs55.visibleSources.length)
          for (var a = 0; a < prefs55.visibleSources.length; a++)
            harness.check(prefs55.visibleSources[a].driver === "ai", "only AI sources shown")
          prefs55.filterGroup = "local"
          for (var l = 0; l < prefs55.visibleSources.length; l++)
            harness.check(prefs55.visibleSources[l].kind === "local", "only local sources shown")
          prefs55.filterGroup = "wiktionary"
          harness.check(prefs55.visibleSources.length > 0, "wiktionary rows found")
          prefs55.filterGroup = "nokey"
          for (var n = 0; n < prefs55.visibleSources.length; n++)
            harness.check(!prefs55.visibleSources[n].has_key, "only keyless sources shown")
          prefs55.resetFilters()
          harness.check(prefs55.visibleSources.length === p.sources.length, "filters reset")
          harness.check(prefs55.filtersAreDefault, "reset restores the default")
          break
        case 56:
          // multi-select, bulk move and drag reordering
          var prefs56 = p.prefsView
          prefs56.resetFilters()
          prefs56.clearSelection()
          prefs56.selectRow(0, false, false)
          harness.check(prefs56.selectedIds.length === 1, "a plain click selects one row")
          prefs56.selectRow(2, true, false)
          harness.check(prefs56.selectedIds.length === 2, "ctrl+click adds a row")
          prefs56.selectRow(2, true, false)
          harness.check(prefs56.selectedIds.length === 1, "ctrl+click again removes it")
          prefs56.selectRow(0, false, false)
          prefs56.selectRow(3, false, true)
          harness.check(prefs56.selectedIds.length === 4, "shift+click takes the range: " + prefs56.selectedIds.length)
          // a row action applies to the selection when the row is part of it
          harness.check(prefs56.selectionFor(p.sources[0].id).length === 4, "the action covers the selection")
          harness.check(prefs56.selectionFor(p.sources[9].id).length === 1, "a row outside it acts alone")
          var moved = null
          prefs56.moveSources.connect(function(ids, delta) { moved = {ids: ids, delta: delta} })
          prefs56.moveSelection(p.sources[0].id, -1)
          harness.check(moved !== null && moved.ids.length === 4 && moved.delta === -1,
                        "the whole selection moves as a block")
          // a drag drops the block in front of the row it was released over
          var dropped = null
          prefs56.reorderSources.connect(function(ids, beforeId) { dropped = {ids: ids, before: beforeId} })
          prefs56.clearSelection()
          prefs56.selectRow(1, false, false)
          prefs56.dragging = true
          prefs56.dropIndex = 5
          prefs56.finishDrag()
          harness.check(dropped !== null, "the drag ends in a reorder")
          harness.check(dropped.ids.length === 1 && dropped.ids[0] === p.sources[1].id, "the dragged row is the selected one")
          harness.check(dropped.before === p.sources[5].id,
                        "dropped in front of the row it was released over: " + dropped.before)
          harness.check(!prefs56.dragging && prefs56.dropIndex === -1, "the drag state is cleared")
          // dropping past the end means "last"
          prefs56.dragging = true
          prefs56.dropIndex = p.sources.length
          prefs56.finishDrag()
          harness.check(dropped.before === "", "dropping past the last row appends")
          prefs56.clearSelection()
          break
        case 10:
          p.closePrefs()
          harness.check(p.prefsOpen === false, "prefs closed")
          break
        case 11:
          // history popup: filter, keyboard walk, pick
          var hp = p.historyView
          hp.openWith("ha")
          harness.check(hp.opened === true, "history popup opens")
          harness.check(hp.rows.length === 1 && hp.rows[0].query === "Haus", "history filtered by substring")
          hp.move(1)
          harness.check(hp.currentIndex === 0, "history cursor moves")
          hp.pickCurrent()
          harness.check(hp.opened === false, "pick closes popup")
          harness.check(p.searchInput.text === "Haus" && p.searching === true, "pick starts a search")
          break
        case 12:
          p.searchWord("house")     // backend stub never answers: must not throw
          harness.check(p.searching === true && p.searchInput.text === "house", "searchWord updates field + searches")
          p.clearResults()
          harness.check(p.searching === false && p.result === null, "clearResults drops results")
          p.searchInput.text = "Haus"
          p.result = harness.readJson(fx + "/lookup.json")
          p.clearSearch()
          harness.check(p.searchInput.text === "" && p.result === null, "clearSearch empties field + results")
          // history walk over a snapshot: house (newest), Haus (older)
          p.historyStep(1)
          harness.check(p.searchInput.text === "house" && p.historyNavIndex === 0, "Ctrl+P goes to the newest entry first: " + p.searchInput.text)
          p.historyStep(1)
          harness.check(p.searchInput.text === "Haus" && p.historyNavIndex === 1, "Ctrl+P walks to the older entry")
          p.historyStep(1)
          harness.check(p.historyNavIndex === 1, "Ctrl+P stops at the oldest entry")
          p.historyStep(-1)
          harness.check(p.searchInput.text === "house" && p.historyNavIndex === 0, "Ctrl+N walks back")
          p.historyStep(-1)
          harness.check(p.historyNavIndex === 0, "Ctrl+N stops at the newest entry")
          p.runSearch("fresh")
          harness.check(p.historyNav === null, "a fresh search resets the history walk")
          // after a history walk the dropdown must show every entry again
          p.historyStep(1)
          harness.check(p.searchTyped === false, "history walk does not count as typing")
          p.toggleHistoryPopup()
          harness.check(p.historyView.opened === true, "history popup opened by keyboard")
          harness.check(p.historyView.rows.length === p.history.length,
                        "unfiltered after a history walk: " + p.historyView.rows.length + " of " + p.history.length)
          p.toggleHistoryPopup()
          // Ctrl+U scrolls instead of clearing the results (Qt binds it to
          // delete-to-start-of-line inside the field)
          p.result = harness.readJson(fx + "/lookup.json")
          p.searching = false
          harness.check(p.panelAction(Qt.Key_U, false) === true, "Ctrl+U handled by the panel")
          harness.check(p.result !== null, "Ctrl+U keeps the results")
          harness.check(p.panelAction(Qt.Key_D, false) === true, "Ctrl+D handled by the panel")
          harness.check(p.result !== null, "Ctrl+D keeps the results")
          // card selection + collapsing
          var view = p.resultsView
          harness.check(view.cardCount === p.result.results.length, "one card per source")
          harness.check(view.selectedCard === 0, "first card selected for a new result list")
          p.panelAction(Qt.Key_J, false)
          harness.check(view.selectedCard === Math.min(1, view.cardCount - 1), "Ctrl+J selects the next card")
          for (var j = 0; j < view.cardCount + 2; j++) p.panelAction(Qt.Key_J, false)
          harness.check(view.selectedCard === view.cardCount - 1, "Ctrl+J stops at the last card")
          p.panelAction(Qt.Key_K, false)
          harness.check(view.selectedCard === Math.max(0, view.cardCount - 2), "Ctrl+K selects the previous card")
          for (var k = 0; k < view.cardCount + 2; k++) p.panelAction(Qt.Key_K, false)
          harness.check(view.selectedCard === 0, "Ctrl+K stops at the first card")
          harness.check(p.panelAction(Qt.Key_I, false) === false, "plain Ctrl+I is not a panel shortcut")
          p.panelAction(Qt.Key_O, false)
          harness.check(view.isCollapsed(0) === true, "Ctrl+O collapses the selected card")
          p.panelAction(Qt.Key_O, false)
          harness.check(view.isCollapsed(0) === false, "Ctrl+O expands it again")
          view.toggleCollapsed(0)
          harness.check(view.isCollapsed(0) === true, "a double click toggles a card")
          view.toggleCollapsed(0)
          p.panelAction(Qt.Key_I, true)
          harness.check(view.isCollapsed(0) && view.isCollapsed(view.cardCount - 1), "Ctrl+Shift+I collapses all")
          p.panelAction(Qt.Key_O, true)
          harness.check(!view.isCollapsed(0) && !view.isCollapsed(1), "Ctrl+Shift+O expands all")
          // sorting shortcuts only bite in thesaurus mode
          p.mode = "lookup"
          harness.check(p.panelAction(Qt.Key_A, false) === false, "Ctrl+A left to the text field outside thesaurus mode")
          p.mode = "thesaurus"
          p.result = harness.readJson(fx + "/thesaurus.json")
          harness.check(view.cardCount === p.result.consolidated.groups.length + 1, "group cards plus the overview")
          harness.check(p.panelAction(Qt.Key_Z, false) === true, "Ctrl+Z sorts by length")
          harness.check(p.thesaurusSort === "length", "length sort applied")
          harness.check(p.panelAction(Qt.Key_A, false) === true, "Ctrl+A sorts alphabetically")
          harness.check(p.thesaurusSort === "alpha", "alphabetical sort applied")
          p.mode = "lookup"
          p.result = harness.readJson(fx + "/lookup.json")
          p.searching = false
          p.resultsView.scrollBy(0.5)
          p.resultsView.scrollBy(-0.5)
          p.mode = "lookup"
          p.openLanguagePicker(true)
          harness.check(p.status.indexOf("translate mode") >= 0, "secondary picker refused outside translate mode")
          p.mode = "translate"
          p.openLanguagePicker(true)
          p.openLanguagePicker(false)
          p.setMode("thesaurus")
          harness.check(p.mode === "thesaurus", "mode switch")
          p.swapLangs()
          harness.check(p.lang === "en" && p.lang2 === "de", "swap languages: " + p.lang + "/" + p.lang2)
          break
        case 13:
          // help panel
          p.toggleHelp()
          harness.check(p.helpOpen === true && p.searchActive === false, "Ctrl+. opens the help")
          harness.check(p.helpView.sections.length >= 4, "help lists shortcut sections")
          var shortcuts = ""
          for (var si = 0; si < p.helpView.sections.length; si++) {
            var rows = p.helpView.sections[si].rows
            for (var ri = 0; ri < rows.length; ri++) shortcuts += rows[ri][0] + " | "
          }
          var expected = ["Ctrl+1", "Ctrl+[", "Ctrl+]", "Ctrl+S", "Ctrl+L", "Ctrl+C", "Ctrl+H", "Ctrl+P",
                          "Ctrl+J", "Ctrl+D", "Ctrl+O", "Ctrl+Shift+I", "Ctrl+A", "Ctrl+.", "Ctrl+,"]
          for (var ei = 0; ei < expected.length; ei++)
            harness.check(shortcuts.indexOf(expected[ei]) >= 0, "help documents " + expected[ei])
          harness.check(p.helpView.documentationUrl.indexOf("github.com/muellan/omababel") >= 0, "documentation link")
          harness.check(p.panelAction(Qt.Key_J, false) === false, "panel shortcuts are inert while the help is open")
          p.toggleHelp()
          harness.check(p.helpOpen === false && p.searchActive === true, "help closes again")
          p.openPrefs()
          harness.check(p.helpOpen === false, "preferences and help are mutually exclusive")
          p.openHelp()
          harness.check(p.prefsOpen === false, "opening the help leaves the preferences")
          p.closeHelp()
          break
        case 14:
          p.dismiss()
          harness.check(p.opened === false, "dismiss closes")
          break
        default:
          console.log("HARNESS OK")
          Qt.exit(0)
        }
      } catch (e) {
        harness.fail("step " + harness.step + " threw: " + e)
      }
      harness.step++
    }
  }
}
