import QtQuick
import QtQuick.Controls
import Quickshell
import Quickshell.Wayland
import qs.Commons
import qs.Ui

// omababel – dictionary, thesaurus and translation panel for Omarchy.
//
//   omarchy-shell shell toggle muellan.omababel '{}'
//   omarchy-shell shell summon muellan.omababel '{"query": "Haus", "mode": "lookup", "lang": "de"}'
//
// All searching happens in backend/omababel.py (plain Python 3, stdlib only);
// this file is the UI: mode toggle, language selectors, search field with
// history, results, and the preferences panel with the source editor.
Item {
  id: root

  property var shell: null
  property var manifest: null
  property bool opened: false

  readonly property string pluginId: (manifest && manifest.id) ? manifest.id : "muellan.omababel"
  readonly property string helperPath: decodeURIComponent(Qt.resolvedUrl("backend/omababel.py").toString().replace(/^file:\/\//, ""))

  // --- state mirrored from the backend
  property bool stateLoaded: false
  property bool stateLoading: false
  property var languages: []
  property var sources: []
  property var drivers: []
  property var history: []
  property var datasets: []
  property var localStatus: ({})

  // --- search state
  property string mode: "lookup"            // lookup | thesaurus | translate
  property string lang: "de"
  property string lang2: "en"
  property var result: null
  property bool searching: false
  property int searchSeq: 0
  property string lastQuery: ""
  property string status: ""
  property bool statusError: false
  property bool prefsOpen: false
  property bool helpOpen: false
  // true while the search view (not the preferences or the help) is showing
  readonly property bool searchActive: root.opened && !root.prefsOpen && !root.helpOpen
  property var pendingPayload: null
  property string thesaurusSort: "alpha"    // "alpha" | "length" (persisted)
  property int historyMax: 1000              // configurable in Preferences → History
  property string backendVersion: ""
  // Ctrl+P / Ctrl+N walk a snapshot of the history taken when the walk
  // starts, so re-running an entry (which moves it to the top) does not
  // reshuffle the list under the cursor.
  property var historyNav: null
  property int historyNavIndex: -1
  // True while the field holds something the user typed.  Text we put there
  // ourselves (history walk, a clicked result word, a payload) must not
  // filter the history dropdown – opening it then shows the full history.
  property bool searchTyped: false

  // --- exposed for tests / IPC callers
  readonly property alias searchInput: searchField
  readonly property alias prefsView: prefs
  readonly property alias historyView: historyPopup
  readonly property alias resultsView: resultsView
  readonly property alias helpView: help
  readonly property alias modeSelector: modeGroup
  readonly property alias langPickerView: langPicker

  // --- look
  readonly property color background: Color.menu.background
  readonly property color foreground: Color.menu.text
  readonly property color accent: Color.accent
  readonly property color muted: Qt.darker(foreground, 1.45)
  readonly property string fontFamily: Style.font.family
  readonly property int cardWidth: Math.min(Style.space(980), panel.width - Style.gapsOut * 2)
  readonly property int cardHeight: Math.min(Style.space(740), panel.height - Style.gapsOut * 2)

  // Which languages an enabled source can answer in, per mode (from the
  // backend).  The selectors dim everything else.
  property var coverage: ({})
  // { available, backend }: where source credentials are stored
  property var keyring: ({})

  function unservedIn(mode, from) {
    var out = ({})
    var cov = root.coverage ? root.coverage[mode] : null
    if (!cov || cov.any) return out          // no data, or a source serves any language
    var served = ({})
    var list = (mode === "translate" && from)
      ? ((cov.pairs && cov.pairs[from]) || [])
      : (cov.langs || [])
    for (var i = 0; i < list.length; i++) served[list[i]] = true
    for (var j = 0; j < root.languages.length; j++) {
      var code = root.languages[j].value
      if (!served[code]) out[code] = true
    }
    return out
  }

  readonly property var unservedLangs: root.unservedIn(root.mode, "")
  readonly property var unservedTargetLangs: root.unservedIn("translate", root.lang)

  readonly property var modeOptions: [
    {value: "lookup", label: "Lookup", icon: "󰗚", tooltip: "Dictionary lookup (Ctrl+1)"},
    {value: "thesaurus", label: "Thesaurus", icon: "󰉹", tooltip: "Synonyms and antonyms (Ctrl+2)"},
    {value: "translate", label: "Translate", icon: "󰗊", tooltip: "Translate between two languages (Ctrl+3)"}
  ]

  // ================================================================ lifecycle
  function open(payloadJson) {
    var payload = {}
    try { payload = payloadJson ? JSON.parse(payloadJson) : {} } catch (e) { payload = {} }
    if (typeof payload !== "object" || payload === null) payload = {}
    root.opened = true
    root.prefsOpen = false
    if (!root.stateLoaded) {
      root.pendingPayload = payload
      root.loadState()
    } else {
      root.applyPayload(payload)
      // pick up history / sources changed by the CLI while we were closed
      backend.call("state.get", {}, function(reply) { if (reply.ok) root.applyState(reply.data, false) })
    }
    Qt.callLater(function() { searchField.forceActiveFocus(); searchField.selectAll() })
  }

  function close() {
    root.opened = false
    historyPopup.close()
  }

  function dismiss() {
    root.opened = false
    historyPopup.close()
    if (root.shell && typeof root.shell.hide === "function") root.shell.hide(root.pluginId)
  }

  function toggle() { root.opened ? root.dismiss() : root.open("{}") }

  // Callable through IPC: omarchy-shell shell call muellan.omababel search '{"query":"Haus"}'
  function search(arg) {
    var payload = {}
    try { payload = typeof arg === "string" ? JSON.parse(arg || "{}") : (arg || {}) } catch (e) { payload = {query: String(arg)} }
    if (!root.opened) root.open("{}")
    root.applyPayload(payload)
    return "ok"
  }

  function applyPayload(payload) {
    if (!payload) return
    if (payload.mode && ["lookup", "thesaurus", "translate"].indexOf(payload.mode) >= 0) root.mode = payload.mode
    if (payload.lang) root.lang = String(payload.lang)
    if (payload.lang2) root.lang2 = String(payload.lang2)
    if (payload.query !== undefined && String(payload.query).trim() !== "") {
      searchField.text = String(payload.query).trim()
      root.searchTyped = false
      root.runSearch(searchField.text)
    }
  }

  // ==================================================================== state
  function loadState() {
    if (root.stateLoading) return
    root.stateLoading = true
    backend.call("state.get", {}, function(reply) {
      root.stateLoading = false
      if (!reply.ok) {
        // A failing backend must never leave the panel unusable: the UI keeps
        // working with its defaults and the next open retries.
        root.setStatus("Backend unavailable: " + reply.error.message, true)
        return
      }
      root.applyState(reply.data, true)
      root.stateLoaded = true
      var payload = root.pendingPayload
      root.pendingPayload = null
      if (payload) root.applyPayload(payload)
      root.refreshLocalStatus()
    })
  }

  function applyState(data, applyPrefs) {
    if (!data || typeof data !== "object") return
    root.languages = data.languages || []
    root.sources = data.sources || []
    root.drivers = data.drivers || []
    root.history = data.history || []
    if (applyPrefs && data.prefs) {
      root.mode = data.prefs.mode || "lookup"
      root.lang = data.prefs.lang || "de"
      root.lang2 = data.prefs.lang2 || "en"
      root.thesaurusSort = data.prefs.thesaurus_sort === "length" ? "length" : "alpha"
    }
    if (data.coverage) root.coverage = data.coverage
    if (data.keyring) root.keyring = data.keyring
    if (data.history_max) root.historyMax = data.history_max
    if (data.version) root.backendVersion = data.version
  }

  function refreshLocalStatus() {
    backend.call("sources.status", {}, function(reply) {
      if (!reply.ok) return
      root.localStatus = reply.data.status || ({})
      if (reply.data.coverage) root.coverage = reply.data.coverage
    })
  }

  function refreshDatasets() {
    backend.call("data.list", {}, function(reply) {
      if (reply.ok) root.datasets = reply.data.datasets || []
    })
  }

  function savePrefs() {
    backend.call("prefs.set", {values: {mode: root.mode, lang: root.lang, lang2: root.lang2,
                                        thesaurus_sort: root.thesaurusSort}}, null)
  }

  function setThesaurusSort(mode) {
    root.thesaurusSort = mode === "length" ? "length" : "alpha"
    root.savePrefs()
  }

  // Clear button / Ctrl+C / Ctrl+Backspace: empty the field and the results.
  function clearSearch() {
    historyPopup.close()
    searchField.text = ""
    root.searchTyped = false
    root.clearResults()
    searchField.forceActiveFocus()
  }

  // Ctrl+P (older) / Ctrl+N (newer): step through the history and re-run
  // the entry with its original mode and languages.
  function historyStep(delta) {
    if (root.history.length === 0) return
    if (root.historyNav === null) {
      root.historyNav = root.history.slice()
      // the current query (if it is the latest entry) is where we start
      root.historyNavIndex = (root.lastQuery !== "" && root.historyNav[0].query === root.lastQuery) ? 0 : -1
    }
    var next = root.historyNavIndex + delta
    if (next < 0 || next >= root.historyNav.length) {
      root.setStatus(delta > 0 ? "Oldest history entry reached." : "Newest history entry reached.", false)
      return
    }
    root.historyNavIndex = next
    var row = root.historyNav[next]
    searchField.text = row.query
    root.searchTyped = false
    if (row.mode && ["lookup", "thesaurus", "translate"].indexOf(row.mode) >= 0) root.mode = row.mode
    if (row.lang) root.lang = row.lang
    if (row.lang2) root.lang2 = row.lang2
    root.runSearch(row.query, true)
    root.setStatus("History " + (next + 1) + " / " + root.historyNav.length + ": " + row.query, false)
  }

  function toggleHistoryPopup() {
    if (historyPopup.opened) historyPopup.close()
    else historyPopup.openWith(root.searchTyped ? searchField.text : "")
  }

  // Qt's line edit binds several Ctrl keys itself (Ctrl+U deletes to the
  // start of the line, Ctrl+K to the end, Ctrl+C copies, Ctrl+H is
  // backspace on X11 …) and consumes them before a window Shortcut is
  // reached.  The field's key handler therefore dispatches through this
  // function, which is also what every Shortcut below calls – so the two
  // paths can never drift apart.  Returns true when the key was handled.
  function panelAction(key, shift) {
    if (root.prefsOpen || root.helpOpen) return false
    switch (key) {
    case Qt.Key_C:
    case Qt.Key_Backspace: root.clearSearch(); return true
    case Qt.Key_D: resultsView.scrollBy(0.5); return true
    case Qt.Key_U: resultsView.scrollBy(-0.5); return true
    case Qt.Key_H: root.toggleHistoryPopup(); return true
    case Qt.Key_P: root.historyStep(1); return true
    case Qt.Key_N: root.historyStep(-1); return true
    case Qt.Key_S: root.swapLangs(); return true
    case Qt.Key_BracketLeft: root.openLanguagePicker(false); return true
    case Qt.Key_BracketRight: root.openLanguagePicker(true); return true
    case Qt.Key_L: searchField.forceActiveFocus(); searchField.selectAll(); return true
    case Qt.Key_J: resultsView.stepCard(1); return true
    case Qt.Key_K: resultsView.stepCard(-1); return true
    // Ctrl+Shift+I / Ctrl+Shift+O fold every card; plain Ctrl+O toggles the
    // selected one.  Plain Ctrl+I is not a panel shortcut.
    case Qt.Key_I:
      if (!shift) return false
      resultsView.setAllCollapsed(true); return true
    case Qt.Key_O:
      if (shift) resultsView.setAllCollapsed(false); else resultsView.toggleSelected()
      return true
    // Sorting only exists in thesaurus mode; elsewhere Ctrl+A / Ctrl+Z keep
    // their text-field meaning (select all / undo).
    case Qt.Key_A:
      if (root.mode !== "thesaurus") return false
      root.setThesaurusSort("alpha"); return true
    case Qt.Key_Z:
      if (root.mode !== "thesaurus") return false
      root.setThesaurusSort("length"); return true
    case Qt.Key_1: root.setMode("lookup"); return true
    case Qt.Key_2: root.setMode("thesaurus"); return true
    case Qt.Key_3: root.setMode("translate"); return true
    }
    return false
  }

  function openLanguagePicker(secondary) {
    if (secondary && root.mode !== "translate") {
      root.setStatus("The target language is only used in translate mode (Ctrl+3).", false)
      return
    }
    historyPopup.close()
    if (secondary) langPicker2.open(); else langPicker.open()
  }

  function setHistoryMax(value) {
    backend.call("prefs.set", {values: {history_max: value}}, function(reply) {
      if (!reply.ok) { prefs.message = reply.error.message; prefs.messageError = true; return }
      root.historyMax = reply.data.history_max || value
      root.history = reply.data.history || root.history
      prefs.message = "History keeps the last " + root.historyMax + " searches."
      prefs.messageError = false
    })
  }

  // Emptying the field (backspace / clear) drops the results that belonged
  // to the previous query.
  function clearResults() {
    root.searchSeq++          // ignore any reply still in flight
    root.searching = false
    root.result = null
    root.lastQuery = ""
    root.setStatus("", false)
  }

  function langName(code) {
    for (var i = 0; i < root.languages.length; i++) if (root.languages[i].value === code) return root.languages[i].label
    return code
  }

  function setStatus(text, isError) {
    root.status = text
    root.statusError = !!isError
  }

  // The kit's dropdowns assign their own `value` when the user picks an
  // option, which silently breaks a `value: root.lang` binding – so push the
  // model into the pickers explicitly whenever it changes.
  onLangChanged: langPicker.value = root.lang
  onLang2Changed: langPicker2.value = root.lang2

  // =================================================================== search
  function runSearch(query, fromHistoryNav) {
    query = String(query || "").trim()
    if (query === "") return
    if (!fromHistoryNav) { root.historyNav = null; root.historyNavIndex = -1 }
    if (root.mode === "translate" && root.lang === root.lang2) {
      root.setStatus("Choose two different languages to translate.", true)
      return
    }
    historyPopup.close()
    root.lastQuery = query
    root.searching = true
    root.setStatus("Searching " + query + "…", false)
    var seq = ++root.searchSeq
    var params = {mode: root.mode, query: query, lang: root.lang, lang2: root.lang2}
    backend.dropPending("search")
    backend.call("search", params, function(reply) {
      if (seq !== root.searchSeq) return   // superseded
      root.searching = false
      if (!reply.ok) {
        root.result = null
        root.setStatus(reply.error.message, true)
        return
      }
      root.result = reply.data
      root.rememberHistory(query)
      var rs = reply.data.results || []
      var okCount = 0, errCount = 0, hits = 0, ms = 0
      for (var i = 0; i < rs.length; i++) {
        if (rs[i].ok) okCount++; else errCount++
        hits += rs[i].count || 0
        ms = Math.max(ms, rs[i].ms || 0)
      }
      var text = rs.length === 0
        ? "No source available for " + root.langName(root.lang) + (root.mode === "translate" ? " → " + root.langName(root.lang2) : "") + "."
        : hits + (hits === 1 ? " result" : " results") + " from " + okCount + (okCount === 1 ? " source" : " sources")
          + (errCount ? " · " + errCount + " failed" : "") + " · " + ms + " ms"
      root.setStatus(text, errCount > 0 && okCount === 0)
      resultsView.scrollToTop()
    })
  }

  function rememberHistory(query) {
    var key = query.toLowerCase()
    var next = [{query: query, mode: root.mode, lang: root.lang, lang2: root.lang2}]
    for (var i = 0; i < root.history.length && next.length < root.historyMax; i++) {
      if (String(root.history[i].query).toLowerCase() !== key) next.push(root.history[i])
    }
    root.history = next
  }

  function searchWord(word) {
    word = String(word || "").trim()
    if (!word) return
    searchField.text = word
    root.searchTyped = false
    root.runSearch(word)
  }

  function copyText(text) {
    if (!text) return
    backend.call("copy", {text: text}, function(reply) {
      if (reply.ok) root.setStatus("Copied: " + (text.length > 60 ? text.slice(0, 57) + "…" : text), false)
      else root.setStatus(reply.error.message, true)
    })
  }

  function setMode(m) {
    if (root.mode === m) return
    root.mode = m
    root.savePrefs()
    if (searchField.text.trim() !== "") root.runSearch(searchField.text)
    searchField.forceActiveFocus()
  }

  function setLang(code, secondary) {
    if (secondary) root.lang2 = code; else root.lang = code
    root.savePrefs()
    if (searchField.text.trim() !== "" && (!secondary || root.mode === "translate")) root.runSearch(searchField.text)
  }

  function swapLangs() {
    var a = root.lang
    root.lang = root.lang2
    root.lang2 = a
    root.savePrefs()
    if (root.mode === "translate" && searchField.text.trim() !== "") root.runSearch(searchField.text)
  }

  // ============================================================= preferences
  function openHelp() {
    root.prefsOpen = false
    root.helpOpen = true
    historyPopup.close()
  }

  function closeHelp() {
    root.helpOpen = false
    Qt.callLater(function() { searchField.forceActiveFocus() })
  }

  function toggleHelp() { root.helpOpen ? root.closeHelp() : root.openHelp() }

  function openPrefs() {
    root.helpOpen = false
    root.prefsOpen = true
    prefs.tab = "sources"
    root.refreshLocalStatus()
  }

  function closePrefs() {
    root.prefsOpen = false
    prefs.editing = null
    Qt.callLater(function() { searchField.forceActiveFocus() })
  }

  function afterSourcesChanged(reply) {
    if (!reply.ok) { prefs.message = reply.error.message; prefs.messageError = true; return }
    root.sources = reply.data.sources || root.sources
    root.refreshLocalStatus()
  }

  // ================================================================ children
  // The plugin is kept loaded by the shell, so this runs long before the
  // panel is opened for the first time: the round trip makes python compile
  // the backend to __pycache__ (which an install or an update invalidates)
  // while nobody is waiting for it.
  Component.onCompleted: backend.warmup()

  ObBackend {
    id: backend
    helperPath: root.helperPath
    onFailed: function(message) { if (!root.prefsOpen) root.setStatus(message, true) }
  }

  ObInstaller {
    id: installer
    helperPath: root.helperPath
    onFinished: function(reply) {
      root.refreshDatasets()
      root.refreshLocalStatus()
      if (reply.ok) {
        prefs.message = "Installed " + installer.datasetId + " (" + (reply.data.dataset.entries || 0).toLocaleString() + " entries)."
        prefs.messageError = false
      } else {
        prefs.message = "Install failed: " + (reply.error ? reply.error.message : "unknown error")
        prefs.messageError = true
      }
    }
  }

  PanelWindow {
    id: panel
    visible: root.opened
    anchors { top: true; bottom: true; left: true; right: true }
    color: "transparent"
    WlrLayershell.namespace: "omababel"
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.Exclusive
    exclusionMode: ExclusionMode.Ignore

    Rectangle { anchors.fill: parent; color: Color.menu.scrim }
    MouseArea { anchors.fill: parent; onClicked: root.dismiss() }

    Shortcut { sequence: "Ctrl+1"; context: Qt.WindowShortcut; enabled: root.searchActive; onActivated: root.panelAction(Qt.Key_1, false) }
    Shortcut { sequence: "Ctrl+2"; context: Qt.WindowShortcut; enabled: root.searchActive; onActivated: root.panelAction(Qt.Key_2, false) }
    Shortcut { sequence: "Ctrl+3"; context: Qt.WindowShortcut; enabled: root.searchActive; onActivated: root.panelAction(Qt.Key_3, false) }
    Shortcut { sequence: "Ctrl+S"; context: Qt.WindowShortcut; enabled: root.searchActive; onActivated: root.panelAction(Qt.Key_S, false) }
    Shortcut { sequence: "Ctrl+L"; context: Qt.WindowShortcut; enabled: root.searchActive; onActivated: root.panelAction(Qt.Key_L, false) }
    Shortcut { sequence: "Ctrl+,"; context: Qt.WindowShortcut; enabled: root.opened; onActivated: root.prefsOpen ? root.closePrefs() : root.openPrefs() }
    Shortcut { sequence: "Ctrl+."; context: Qt.WindowShortcut; enabled: root.opened; onActivated: root.toggleHelp() }
    Shortcut { sequence: "Ctrl+H"; context: Qt.WindowShortcut; enabled: root.searchActive; onActivated: root.panelAction(Qt.Key_H, false) }
    Shortcut { sequence: "Ctrl+C"; context: Qt.WindowShortcut; enabled: root.searchActive; onActivated: root.panelAction(Qt.Key_C, false) }
    Shortcut { sequence: "Ctrl+Backspace"; context: Qt.WindowShortcut; enabled: root.searchActive; onActivated: root.panelAction(Qt.Key_Backspace, false) }
    Shortcut { sequence: "Ctrl+P"; context: Qt.WindowShortcut; enabled: root.searchActive; onActivated: root.panelAction(Qt.Key_P, false) }
    Shortcut { sequence: "Ctrl+N"; context: Qt.WindowShortcut; enabled: root.searchActive; onActivated: root.panelAction(Qt.Key_N, false) }
    Shortcut { sequence: "Ctrl+["; context: Qt.WindowShortcut; enabled: root.searchActive; onActivated: root.panelAction(Qt.Key_BracketLeft, false) }
    Shortcut { sequence: "Ctrl+]"; context: Qt.WindowShortcut; enabled: root.searchActive; onActivated: root.panelAction(Qt.Key_BracketRight, false) }
    Shortcut { sequence: "Ctrl+D"; context: Qt.WindowShortcut; enabled: root.searchActive; onActivated: root.panelAction(Qt.Key_D, false) }
    Shortcut { sequence: "Ctrl+U"; context: Qt.WindowShortcut; enabled: root.searchActive; onActivated: root.panelAction(Qt.Key_U, false) }
    Shortcut { sequence: "Ctrl+J"; context: Qt.WindowShortcut; enabled: root.searchActive; onActivated: root.panelAction(Qt.Key_J, false) }
    Shortcut { sequence: "Ctrl+K"; context: Qt.WindowShortcut; enabled: root.searchActive; onActivated: root.panelAction(Qt.Key_K, false) }
    Shortcut { sequence: "Ctrl+O"; context: Qt.WindowShortcut; enabled: root.searchActive; onActivated: root.panelAction(Qt.Key_O, false) }
    Shortcut { sequence: "Ctrl+Shift+I"; context: Qt.WindowShortcut; enabled: root.searchActive; onActivated: root.panelAction(Qt.Key_I, true) }
    Shortcut { sequence: "Ctrl+Shift+O"; context: Qt.WindowShortcut; enabled: root.searchActive; onActivated: root.panelAction(Qt.Key_O, true) }
    Shortcut { sequence: "Ctrl+A"; context: Qt.WindowShortcut; enabled: root.searchActive && root.mode === "thesaurus"; onActivated: root.panelAction(Qt.Key_A, false) }
    Shortcut { sequence: "Ctrl+Z"; context: Qt.WindowShortcut; enabled: root.searchActive && root.mode === "thesaurus"; onActivated: root.panelAction(Qt.Key_Z, false) }

    BorderSurface {
      id: card
      width: root.cardWidth
      height: root.cardHeight
      anchors.centerIn: parent
      radius: Style.cornerRadius
      color: root.background
      borderSpec: Border.surfaceSpec("menu", "border", Color.menu.border, Math.max(1, Style.space(2)))
      padding: Style.spacing.panelPadding

      MouseArea { anchors.fill: parent; onClicked: {} }

      Keys.priority: Keys.BeforeItem
      Keys.onPressed: function(event) {
        if (event.key === Qt.Key_Escape) {
          if (historyPopup.opened) historyPopup.close()
          else if (root.helpOpen) root.closeHelp()
          else if (root.prefsOpen) root.closePrefs()
          else root.dismiss()
          event.accepted = true
        }
      }

      Column {
        id: content
        anchors.fill: parent
        anchors.topMargin: card.contentTopInset
        anchors.rightMargin: card.contentRightInset
        anchors.bottomMargin: card.contentBottomInset
        anchors.leftMargin: card.contentLeftInset
        spacing: Style.spacing.md

        // ------------------------------------------------------ header row
        Item {
          id: headerRow
          width: parent.width
          height: Math.max(titleText.implicitHeight, gearButton.implicitHeight)

          Row {
            spacing: Style.spacing.md
            anchors.verticalCenter: parent.verticalCenter
            Text {
              textFormat: Text.PlainText
              text: "󰗊"
              color: root.accent
              font.family: root.fontFamily
              font.pixelSize: Style.font.heading
              anchors.verticalCenter: parent.verticalCenter
            }
            Text {
              id: titleText
              textFormat: Text.PlainText
              text: root.prefsOpen ? "Omababel · Preferences" : (root.helpOpen ? "Omababel · Help" : "Omababel")
              color: root.foreground
              font.family: root.fontFamily
              font.pixelSize: Style.font.heading
              font.bold: true
              anchors.verticalCenter: parent.verticalCenter
            }
          }

          Row {
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            spacing: Style.spacing.xs
            Button {
              id: helpButton
              iconText: root.helpOpen ? "󰁍" : "󰋖"
              text: root.helpOpen ? "Back" : ""
              tooltipText: root.helpOpen ? "Back to search (Esc)" : "Keyboard shortcuts and documentation (Ctrl+.)"
              foreground: root.foreground
              accent: root.accent
              onClicked: root.toggleHelp()
            }
            Button {
              id: gearButton
              iconText: root.prefsOpen ? "󰁍" : "󰒓"
              text: root.prefsOpen ? "Back" : ""
              tooltipText: root.prefsOpen ? "Back to search (Esc)" : "Preferences (Ctrl+,)"
              foreground: root.foreground
              accent: root.accent
              onClicked: root.prefsOpen ? root.closePrefs() : root.openPrefs()
            }
            Button {
              iconText: "󰅖"
              tooltipText: "Close (Esc)"
              foreground: root.foreground
              accent: root.accent
              onClicked: root.dismiss()
            }
          }
        }

        // ------------------------------------------------- mode + languages
        Item {
          id: controlsRow
          visible: root.searchActive
          width: parent.width
          height: visible ? Math.max(modeGroup.implicitHeight, langPicker.implicitHeight) : 0

          // The engaged mode is painted in the theme accent (accent text on a
          // dimmed accent fill); an opaque idle fill would make the Button's
          // colour animation flash on hover, so the chips rest on a
          // transparent one like the kit's own buttons.
          ObModeSelector {
            id: modeGroup
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
            options: root.modeOptions
            value: root.mode
            foreground: root.foreground
            accent: root.accent
            onChanged: function(v) { root.setMode(v) }
          }

          Row {
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            spacing: Style.spacing.sm

            ObLangPicker {
              id: langPicker
              width: Style.space(190)
              showLabel: false
              rowHeight: modeGroup.implicitHeight
              options: root.languages
              value: root.lang
              dimmedValues: root.unservedLangs
              dimmedNote: "no source in this mode"
              placeholderText: "Language…"
              foreground: root.foreground
              accent: root.accent
              onChanged: function(v) { root.setLang(v, false) }
            }
            Button {
              iconText: "󰓡"
              tooltipText: (root.mode === "translate" ? "Swap languages" : "Swap with the secondary language") + " (Ctrl+S)"
              foreground: root.foreground
              accent: root.accent
              onClicked: root.swapLangs()
            }
            Item {
              width: Style.space(190)
              height: modeGroup.implicitHeight
              opacity: root.mode === "translate" ? 1 : 0.4
              ObLangPicker {
                id: langPicker2
                anchors.fill: parent
                showLabel: false
                rowHeight: modeGroup.implicitHeight
                enabled: root.mode === "translate"
                options: root.languages
                value: root.lang2
                dimmedValues: root.unservedTargetLangs
                dimmedNote: "not translatable from " + root.langName(root.lang)
                placeholderText: "Target language…"
                foreground: root.foreground
                accent: root.accent
                onChanged: function(v) { root.setLang(v, true) }
              }
              ObToolTip {
                visible: root.mode !== "translate" && langHover.hovered
                text: "Target language – only used in translate mode"
              }
              HoverHandler { id: langHover }
            }
          }
        }

        // -------------------------------------------------------- search row
        Item {
          id: searchRow
          visible: root.searchActive
          // One extra spacing unit above *and* below the field, so the gaps to
          // the mode / language row and to the result list are both twice the
          // normal column spacing.
          width: parent.width
          height: visible ? searchField.height + Style.spacing.md * 2 : 0

          // Fallback fonts for CJK glyphs have taller line boxes than the
          // theme font; size the field from the font metrics with head room
          // and pin its height so it never grows with the content.
          FontMetrics { id: searchMetrics; font: searchField.font }

          TextField {
            id: searchField
            anchors.left: parent.left
            anchors.right: clearButton.left
            anchors.rightMargin: Style.spacing.sm
            anchors.verticalCenter: parent.verticalCenter
            font.pixelSize: Style.font.title
            height: Math.round(searchMetrics.height * 1.5) + topPadding + bottomPadding
            verticalAlignment: TextInput.AlignVCenter
            placeholderText: root.mode === "translate"
              ? "Text to translate from " + root.langName(root.lang) + " to " + root.langName(root.lang2) + "…"
              : (root.mode === "thesaurus" ? "Find synonyms and antonyms in " : "Look up in ") + root.langName(root.lang) + "…"
            foreground: root.foreground
            accent: root.accent
            onAccepted: {
              if (historyPopup.opened && historyPopup.currentIndex >= 0) historyPopup.pickCurrent()
              else root.runSearch(text)
            }
            onTextEdited: {
              root.searchTyped = true
              if (historyPopup.opened) historyPopup.filter(text)
              if (text.trim() === "" && (root.result !== null || root.searching)) root.clearResults()
            }
            Keys.priority: Keys.BeforeItem
            Keys.onPressed: function(event) {
              if (event.modifiers & Qt.ControlModifier) {
                if (root.panelAction(event.key, (event.modifiers & Qt.ShiftModifier) !== 0)) {
                  event.accepted = true
                  return
                }
              }
              if (event.key === Qt.Key_Down) {
                if (!historyPopup.opened) root.toggleHistoryPopup()
                else historyPopup.move(1)
                event.accepted = true
              } else if (event.key === Qt.Key_Up) {
                if (historyPopup.opened) historyPopup.move(-1)
                event.accepted = true
              } else if (event.key === Qt.Key_Escape && historyPopup.opened) {
                historyPopup.close()
                event.accepted = true
              } else if (event.key === Qt.Key_Tab && historyPopup.opened) {
                historyPopup.close()
              }
            }
          }

          Button {
            id: clearButton
            anchors.right: historyButton.left
            anchors.rightMargin: Style.spacing.sm
            anchors.verticalCenter: searchField.verticalCenter
            width: searchField.height
            height: searchField.height
            iconText: "󰭜"
            iconSize: Style.font.title
            tooltipText: "Clear search and results (Ctrl+C / Ctrl+Backspace)"
            bordered: true
            enabled: searchField.text !== "" || root.result !== null
            opacity: enabled ? 1 : 0.45
            foreground: root.foreground
            accent: root.accent
            onClicked: root.clearSearch()
          }

          Button {
            id: historyButton
            anchors.right: parent.right
            anchors.verticalCenter: searchField.verticalCenter
            width: searchField.height
            height: searchField.height
            iconText: historyPopup.opened ? "󰅃" : "󰅀"
            iconSize: Style.font.title
            tooltipText: "Search history (↓ / Ctrl+H)"
            bordered: true
            foreground: root.foreground
            accent: root.accent
            onClicked: historyPopup.opened ? historyPopup.close() : historyPopup.openWith("")
          }

          // ----------------------------------------------- history popup
          Popup {
            id: historyPopup
            x: 0
            y: searchField.y + searchField.height + Style.spacing.xxs
            width: searchRow.width
            property var rows: []
            property int currentIndex: -1
            readonly property var popupBorderSpec: Border.localOrSurfaceSpec("popups", "border", Color.popups.border, Color.popups.border, Style.normalBorderWidth)
            implicitHeight: Math.min(Style.spacing.popupRowHeight * 12, Math.max(Style.spacing.popupRowHeight, historyList.contentHeight) + footer.height) + topPadding + bottomPadding
            padding: Style.spacing.hairline
            leftPadding: Border.left(popupBorderSpec) + Style.spacing.hairline
            rightPadding: Border.right(popupBorderSpec) + Style.spacing.hairline
            topPadding: Border.top(popupBorderSpec) + Style.spacing.hairline
            bottomPadding: Border.bottom(popupBorderSpec) + Style.spacing.hairline
            focus: false
            closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutsideParent
            modal: false

            background: BorderSurface {
              color: Color.popups.background
              borderSpec: historyPopup.popupBorderSpec
              radius: Style.cornerRadius
            }

            function openWith(prefix) {
              filter(prefix)
              currentIndex = -1
              open()
              searchField.forceActiveFocus()
            }
            function filter(prefix) {
              var p = String(prefix || "").toLowerCase()
              var out = []
              for (var i = 0; i < root.history.length; i++) {
                var q = String(root.history[i].query)
                if (!p || q.toLowerCase().indexOf(p) >= 0) out.push(root.history[i])
              }
              rows = out
              if (currentIndex >= rows.length) currentIndex = rows.length - 1
            }
            function move(delta) {
              if (rows.length === 0) return
              currentIndex = Math.max(0, Math.min(rows.length - 1, currentIndex + delta))
              historyList.positionViewAtIndex(currentIndex, ListView.Contain)
            }
            function pickCurrent() {
              if (currentIndex < 0 || currentIndex >= rows.length) return
              pick(rows[currentIndex])
            }
            function pick(row) {
              close()
              searchField.text = row.query
              root.searchTyped = false
              if (row.mode && ["lookup", "thesaurus", "translate"].indexOf(row.mode) >= 0) root.mode = row.mode
              if (row.lang) root.lang = row.lang
              if (row.lang2) root.lang2 = row.lang2
              root.runSearch(row.query)
            }
            function removeRow(row) {
              backend.call("history.remove", {query: row.query}, function(reply) {
                if (!reply.ok) return
                root.history = root.history.filter(function(h) { return h.query !== row.query })
                filter(searchField.text)
              })
            }

            contentItem: Column {
              spacing: 0
              ListView {
                id: historyList
                width: parent.width
                height: Math.min(Style.spacing.popupRowHeight * 11, Math.max(Style.spacing.popupRowHeight, contentHeight))
                clip: true
                model: historyPopup.rows
                currentIndex: historyPopup.currentIndex
                boundsBehavior: Flickable.StopAtBounds
                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

                Text {
                  visible: historyPopup.rows.length === 0
                  anchors.centerIn: parent
                  textFormat: Text.PlainText
                  text: root.history.length === 0 ? "No searches yet" : "No history entry matches"
                  color: root.muted
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.body
                }

                delegate: Rectangle {
                  id: hRow
                  required property var modelData
                  required property int index
                  width: historyList.width
                  height: Style.spacing.popupRowHeight
                  color: index === historyPopup.currentIndex ? Style.hoverFillFor(root.foreground, root.accent) : "transparent"
                  Row {
                    anchors.left: parent.left
                    anchors.leftMargin: Style.spacing.controlPaddingX
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: Style.spacing.md
                    Text {
                      textFormat: Text.PlainText
                      text: hRow.modelData.query
                      color: root.foreground
                      font.family: root.fontFamily
                      font.pixelSize: Style.font.body
                      elide: Text.ElideRight
                      width: Math.min(implicitWidth, historyList.width - Style.space(220))
                    }
                    Text {
                      textFormat: Text.PlainText
                      text: (hRow.modelData.mode || "") + (hRow.modelData.lang ? " · " + hRow.modelData.lang : "")
                        + (hRow.modelData.mode === "translate" && hRow.modelData.lang2 ? "→" + hRow.modelData.lang2 : "")
                      color: root.muted
                      font.family: root.fontFamily
                      font.pixelSize: Style.font.caption
                      anchors.verticalCenter: parent.verticalCenter
                    }
                  }
                  Button {
                    anchors.right: parent.right
                    anchors.rightMargin: Style.spacing.xs
                    anchors.verticalCenter: parent.verticalCenter
                    iconText: "󰅖"
                    tooltipText: "Remove from history"
                    foreground: root.muted
                    accent: root.accent
                    verticalPadding: 0
                    onClicked: historyPopup.removeRow(hRow.modelData)
                  }
                  MouseArea {
                    anchors.fill: parent
                    anchors.rightMargin: Style.space(36)
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onPositionChanged: historyPopup.currentIndex = hRow.index
                    onClicked: historyPopup.pick(hRow.modelData)
                  }
                }
              }
              Item {
                id: footer
                width: parent.width
                height: root.history.length > 0 ? Style.spacing.popupRowHeight : 0
                visible: root.history.length > 0
                Text {
                  anchors.left: parent.left
                  anchors.leftMargin: Style.spacing.controlPaddingX
                  anchors.verticalCenter: parent.verticalCenter
                  textFormat: Text.PlainText
                  text: root.history.length + " of max. " + root.historyMax + " entries"
                  color: root.muted
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.caption
                }
                Button {
                  anchors.right: parent.right
                  anchors.rightMargin: Style.spacing.xs
                  anchors.verticalCenter: parent.verticalCenter
                  text: "Clear history"
                  fontSize: Style.font.caption
                  verticalPadding: 0
                  foreground: root.muted
                  accent: root.accent
                  onClicked: backend.call("history.clear", {}, function(reply) {
                    if (reply.ok) { root.history = []; historyPopup.filter("") }
                  })
                }
              }
            }
          }
        }

        // ---------------------------------------------------------- results
        ObResults {
          id: resultsView
          visible: root.searchActive
          width: parent.width
          height: content.height - headerRow.height - controlsRow.height - searchRow.height - statusRow.height - content.spacing * 4
          result: root.result
          mode: root.mode
          searching: root.searching
          sortMode: root.thesaurusSort
          foreground: root.foreground
          accent: root.accent
          fontFamily: root.fontFamily
          onSearchWord: function(w) { root.searchWord(w) }
          onCopyText: function(t) { root.copyText(t) }
          onSortRequested: function(m) { root.setThesaurusSort(m) }
        }

        // ------------------------------------------------------------ help
        ObHelp {
          id: help
          visible: root.helpOpen
          width: parent.width
          height: content.height - headerRow.height - statusRow.height - content.spacing * 2
          version: root.backendVersion
          foreground: root.foreground
          accent: root.accent
          fontFamily: root.fontFamily
          onCloseRequested: root.closeHelp()
        }

        // ------------------------------------------------------ preferences
        ObPrefs {
          id: prefs
          visible: root.prefsOpen
          width: parent.width
          height: content.height - headerRow.height - statusRow.height - content.spacing * 2
          sources: root.sources
          drivers: root.drivers
          languages: root.languages
          datasets: root.datasets
          localStatus: root.localStatus
          installer: installer
          keyring: root.keyring
          historyCount: root.history.length
          historyMax: root.historyMax
          onHistoryMaxRequested: function(v) { root.setHistoryMax(v) }
          onClearHistoryRequested: backend.call("history.clear", {}, function(reply) {
            if (reply.ok) { root.history = []; root.historyNav = null; root.historyNavIndex = -1; prefs.message = "History cleared."; prefs.messageError = false }
            else { prefs.message = reply.error.message; prefs.messageError = true }
          })
          foreground: root.foreground
          accent: root.accent
          fontFamily: root.fontFamily
          onSaveSource: function(source, clearKey) {
            backend.call("sources.save", {source: source, clear_key: clearKey}, function(reply) {
              root.afterSourcesChanged(reply)
              if (reply.ok) { prefs.editing = null; prefs.tab = "sources"; prefs.message = "Saved " + source.name + "."; prefs.messageError = false }
            })
          }
          onDeleteSource: function(id) { backend.call("sources.delete", {id: id}, root.afterSourcesChanged) }
          onEnableSource: function(id, enabled) { backend.call("sources.enable", {id: id, enabled: enabled}, root.afterSourcesChanged) }
          onMoveSource: function(id, delta) { backend.call("sources.move", {id: id, delta: delta}, root.afterSourcesChanged) }
          onResetSources: backend.call("sources.reset", {}, function(reply) {
            root.afterSourcesChanged(reply)
            if (reply.ok) { prefs.message = "Sources reset to the built-in defaults."; prefs.messageError = false }
          })
          onRefreshDatasets: root.refreshDatasets()
          onInstallDataset: function(id) {
            if (installer.running) { prefs.message = "An install is already running."; prefs.messageError = true; return }
            prefs.message = ""
            installer.install(id)
          }
          onRemoveDataset: function(id) {
            backend.call("data.remove", {id: id}, function(reply) {
              root.refreshDatasets()
              root.refreshLocalStatus()
              prefs.message = reply.ok ? "Removed " + id + "." : reply.error.message
              prefs.messageError = !reply.ok
            })
          }
          onTestSource: function(id) {
            prefs.message = "Testing " + id + "…"
            prefs.messageError = false
            backend.call("sources.test", {id: id}, function(reply) {
              if (!reply.ok) { prefs.message = reply.error.message; prefs.messageError = true; return }
              var rs = reply.data.results || []
              if (rs.length === 0) { prefs.message = "Test: source not applicable (not installed or no language match)."; prefs.messageError = true; return }
              var r = rs[0]
              prefs.message = r.ok
                ? "Test OK: '" + reply.data.query + "' → " + r.count + " result(s) in " + r.ms + " ms"
                : "Test failed: " + r.error
              prefs.messageError = !r.ok
            })
          }
        }

        // ------------------------------------------------------- status row
        Item {
          id: statusRow
          width: parent.width
          height: statusText.implicitHeight
          Text {
            id: statusText
            anchors.left: parent.left
            anchors.right: hintText.left
            anchors.rightMargin: Style.spacing.md
            textFormat: Text.PlainText
            text: root.status
            color: root.statusError ? Color.urgent : root.muted
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
            elide: Text.ElideRight
          }
          Text {
            id: hintText
            anchors.right: parent.right
            textFormat: Text.PlainText
            text: (root.prefsOpen || root.helpOpen) ? "Esc: back" : "Click: look up · Right-click: copy · Ctrl+1/2/3: mode · Ctrl+P/N: history · Ctrl+D/J/K/U: scroll · Ctrl+,: preferences"
            color: root.muted
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
          }
        }
      }
    }
  }
}
