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
  property var panel: null

  function readJson(path) {
    var xhr = new XMLHttpRequest()
    xhr.open("GET", "file://" + path, false)
    xhr.send()
    return JSON.parse(xhr.responseText)
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
        switch (harness.step) {
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
