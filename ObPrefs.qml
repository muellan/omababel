import QtQuick
import QtQuick.Controls
import qs.Commons
import qs.Ui

// Preferences: the editable source list (add / edit / delete / enable) and
// the data tab that downloads the local dictionary datasets.
Item {
  id: root

  property var sources: []          // rows from the backend (api keys masked)
  property var drivers: []          // driver registry
  property var languages: []        // language options
  property var datasets: []         // data.list rows
  property var localStatus: ({})    // sources.status result
  property var installer: null      // ObInstaller
  property var keyring: ({})        // { available, backend } from the backend
  property string tab: "sources"    // "sources" | "data" | "history" | "edit"
  property int historyCount: 0
  property int historyMax: 1000
  property var editing: null        // row being edited (copy)
  property bool editingNew: false
  property string message: ""
  property bool messageError: false
  property color foreground: Color.menu.text
  property color accent: Color.accent
  readonly property color muted: Qt.darker(foreground, 1.45)
  property string fontFamily: Style.font.family

  readonly property alias nameInput: nameField
  readonly property alias urlInput: urlField
  readonly property alias pathInput: pathField
  readonly property alias langInput: langField
  readonly property alias keyInput: keyField

  // --- source list: filters, selection, drag and drop
  property string filterEnabled: "all"      // all | enabled | disabled
  property string filterType: "all"         // all | dictionary | thesaurus | translator
  property string filterGroup: "all"        // all | ai | web | local | wiktionary | freedict | key | nokey
  property var selectedIds: []
  property int lastClickedIndex: -1
  property bool dragging: false
  property int dropIndex: -1
  property real dragPointY: 0
  property real autoScrollStep: 0

  readonly property var visibleSources: root.filterSources()
  // Rows may only be reordered when the shown set is complete enough for a
  // new order to mean anything: every source, or every enabled one.
  readonly property bool canReorder: root.filterType === "all" && root.filterGroup === "all"
                                     && (root.filterEnabled === "all" || root.filterEnabled === "enabled")

  signal saveSource(var source, bool clearKey)
  signal deleteSource(string id)
  signal enableSource(string id, bool enabled)
  signal moveSource(string id, int delta)
  signal moveSources(var ids, int delta)
  signal reorderSources(var ids, string beforeId)
  signal resetSources()
  signal installDataset(string id)
  signal removeDataset(string id)
  signal refreshDatasets()
  signal testSource(string id)
  signal closeRequested()
  signal historyMaxRequested(int value)
  signal clearHistoryRequested()

  // ------------------------------------------------------------- filtering
  function matchesGroup(row) {
    switch (root.filterGroup) {
    case "ai": return row.driver === "ai"
    case "web": return row.kind !== "local" && row.driver !== "ai"
    case "local": return row.kind === "local"
    case "wiktionary": return String(row.dataset || row.id).indexOf("wiktionary") >= 0
    case "freedict": return String(row.dataset || row.id).indexOf("freedict") >= 0
    case "key": return !!row.has_key
    case "nokey": return !row.has_key
    default: return true
    }
  }

  function filterSources() {
    var out = []
    for (var i = 0; i < root.sources.length; i++) {
      var row = root.sources[i]
      if (root.filterEnabled === "enabled" && !row.enabled) continue
      if (root.filterEnabled === "disabled" && row.enabled) continue
      if (root.filterType !== "all" && row.type !== root.filterType) continue
      if (!root.matchesGroup(row)) continue
      out.push(row)
    }
    return out
  }

  function resetFilters() {
    root.filterEnabled = "all"
    root.filterType = "all"
    root.filterGroup = "all"
  }

  // ------------------------------------------------------------- selection
  function isSelected(id) { return root.selectedIds.indexOf(id) >= 0 }

  function clearSelection() {
    root.selectedIds = []
    root.lastClickedIndex = -1
  }

  // Ctrl adds or removes one row, Shift takes the range from the last click,
  // a plain click selects just this one – the way a file manager does it.
  function selectRow(index, ctrl, shift) {
    var visible = root.visibleSources
    if (index < 0 || index >= visible.length) return
    var id = visible[index].id
    if (shift && root.lastClickedIndex >= 0) {
      var from = Math.min(root.lastClickedIndex, index)
      var to = Math.max(root.lastClickedIndex, index)
      var range = []
      for (var i = from; i <= to; i++) range.push(visible[i].id)
      root.selectedIds = ctrl ? root.selectedIds.filter(function(x) { return range.indexOf(x) < 0 }).concat(range) : range
      return
    }
    if (ctrl) {
      root.selectedIds = root.isSelected(id)
        ? root.selectedIds.filter(function(x) { return x !== id })
        : root.selectedIds.concat([id])
    } else {
      root.selectedIds = [id]
    }
    root.lastClickedIndex = index
  }

  // What a row action applies to: the selection when the row is part of it,
  // otherwise just that row.
  function selectionFor(id) {
    return root.isSelected(id) && root.selectedIds.length > 1 ? root.selectedIds.slice() : [id]
  }

  function moveSelection(id, delta) {
    if (!root.canReorder) return
    root.moveSources(root.selectionFor(id), delta)
  }

  // --------------------------------------------------------- drag and drop
  function dropIndexAt(y) {
    var visible = root.visibleSources
    for (var i = 0; i < visible.length; i++) {
      var item = sourceRepeater.itemAt(i)
      if (!item) continue
      if (y < item.y + item.height / 2) return i
    }
    return visible.length
  }

  function dropLineY() {
    var i = Math.max(0, root.dropIndex)
    var item = sourceRepeater.itemAt(Math.min(i, root.visibleSources.length - 1))
    if (!item) return 0
    return i >= root.visibleSources.length ? item.y + item.height : Math.max(0, item.y - Style.spacing.xs / 2)
  }

  // The row the block lands in front of, resolved in the *full* list: with
  // only the enabled rows shown, dropping at the end of the list means "after
  // the last enabled row", not "at the very end".
  function beforeIdFor(index) {
    var visible = root.visibleSources
    var moving = root.selectedIds
    for (var i = index; i < visible.length; i++) {
      if (moving.indexOf(visible[i].id) < 0) return visible[i].id
    }
    // past the last visible row: take the next row of the full list
    var lastVisible = visible.length ? visible[visible.length - 1].id : ""
    var seen = false
    for (var j = 0; j < root.sources.length; j++) {
      if (seen && moving.indexOf(root.sources[j].id) < 0) return root.sources[j].id
      if (root.sources[j].id === lastVisible) seen = true
    }
    return ""
  }

  function finishDrag() {
    var target = root.dropIndex
    root.cancelDrag()
    if (target < 0 || root.selectedIds.length === 0) return
    root.reorderSources(root.selectedIds.slice(), root.beforeIdFor(target))
  }

  function cancelDrag() {
    root.dragging = false
    root.dropIndex = -1
    root.autoScrollStep = 0
  }

  // ------------------------------------------------------------ datasets
  // Installed datasets first, then the rest, both alphabetical: what is
  // already there is what one comes back to look at.
  readonly property var sortedDatasets: root.sortDatasets()

  function datasetTitle(ds) { return String((ds && (ds.title || ds.id)) || "") }

  function datasetInstalled(ds) { return !!(ds && ds.installed) }

  function sortDatasets() {
    var rows = (root.datasets || []).slice()
    rows.sort(function(a, b) {
      var ia = root.datasetInstalled(a), ib = root.datasetInstalled(b)
      if (ia !== ib) return ia ? -1 : 1
      var ta = root.datasetTitle(a).toLowerCase(), tb = root.datasetTitle(b).toLowerCase()
      return ta < tb ? -1 : (ta > tb ? 1 : 0)
    })
    return rows
  }

  function installedCount() {
    var n = 0
    for (var i = 0; i < (root.datasets || []).length; i++) if (root.datasetInstalled(root.datasets[i])) n++
    return n
  }

  // AI services offered by the "ai" driver, as reported by the backend.
  function aiServices() {
    var info = driverInfo("ai")
    return (info && info.services) ? info.services : []
  }

  function aiPreset(id) {
    var list = root.aiServices()
    for (var i = 0; i < list.length; i++) if (list[i].value === id) return list[i]
    return null
  }

  function driverInfo(name) {
    for (var i = 0; i < drivers.length; i++) if (drivers[i].driver === name) return drivers[i]
    return null
  }

  function driverOptions(kind, type) {
    var out = []
    for (var i = 0; i < drivers.length; i++) {
      var d = drivers[i]
      if (d.kind !== kind) continue
      if (type && d.types.indexOf(type) < 0) continue
      out.push({value: d.driver, label: d.label})
    }
    return out
  }

  function startNew() {
    editing = {
      id: "", name: "", enabled: true, type: "dictionary", kind: "remote", driver: "generic",
      url: "https://example.org/dictionary/{word}", path: "", format: "", dataset: "",
      translation_mode: "text", api_key: "", api_key_env: "", api_key_cmd: "",
      service: "", transport: "", model: "", command: "",
      languages: [], pairs: [], builtin: false, notes: "", has_key: false, key_storage: ""
    }
    editingNew = true
    message = ""
    tab = "edit"
    loadEditorFields()
    Qt.callLater(function() { nameField.forceActiveFocus() })
  }

  function startEdit(row) {
    var copy = JSON.parse(JSON.stringify(row))
    copy.api_key = ""
    editing = copy
    editingNew = false
    message = ""
    tab = "edit"
    loadEditorFields()
    Qt.callLater(function() { nameField.forceActiveFocus() })
  }

  // Typing into a TextField replaces its `text` binding with the typed
  // value, so a field the user has touched would keep that value when the
  // editor moves to another source.  Every field is therefore *assigned*
  // from the row being edited whenever the editor opens.  The API key field
  // starts empty by definition: the secret lives in the keyring and is never
  // handed to the UI, so an empty field means "keep whatever is stored".
  function loadEditorFields() {
    var e = root.editing || ({})
    nameField.text = e.name || ""
    urlField.text = e.url || ""
    aiEndpointField.text = e.url || ""
    pathField.text = e.path || ""
    modelField.text = e.model || ""
    commandField.text = e.command || ""
    langField.text = (e.languages || []).join(", ")
    pairsField.text = (e.pairs || []).map(function(p) { return p[0] + "-" + p[1] }).join(", ")
    keyField.text = ""
    keyEnvField.text = e.api_key_env || ""
    keyCmdField.text = e.api_key_cmd || ""
    notesField.text = e.notes || ""
    clearKeyCheck.checked_ = false
  }

  function cancelEdit() {
    editing = null
    tab = "sources"
  }

  function setEditField(key, value) {
    var copy = JSON.parse(JSON.stringify(editing))
    copy[key] = value
    if (key === "kind") {
      copy.driver = value === "local" ? "local" : "generic"
    }
    if (key === "type" || key === "kind") {
      var opts = driverOptions(copy.kind, copy.type)
      var ok = false
      for (var i = 0; i < opts.length; i++) if (opts[i].value === copy.driver) ok = true
      if (!ok && opts.length) copy.driver = opts[0].value
    }
    if (key === "driver") {
      var info = driverInfo(value)
      if (info && info.default_url && (!copy.url || copy.url.indexOf("example.org") >= 0)) copy.url = info.default_url
      // an AI source is not a URL source: the endpoint is optional and only
      // used by the API transport
      if (value === "ai" && copy.url.indexOf("example.org") >= 0) copy.url = ""
    }
    editing = copy
  }

  function commitEdit() {
    var row = JSON.parse(JSON.stringify(editing))
    row.name = nameField.text.trim()
    row.url = row.driver === "ai" ? aiEndpointField.text.trim() : urlField.text.trim()
    row.path = pathField.text.trim()
    row.languages = langField.text.split(/[,;\s]+/).filter(function(x) { return x !== "" })
    row.pairs = pairsField.text.split(/[,;\s]+/).filter(function(x) { return x !== "" })
    row.api_key = keyField.text
    row.model = modelField.text.trim()
    row.command = commandField.text.trim()
    row.api_key_env = keyEnvField.text.trim()
    row.api_key_cmd = keyCmdField.text.trim()
    row.notes = notesField.text.trim()
    if (row.name === "") { message = "Give the source a name."; messageError = true; return }
    if (row.kind === "remote" && row.driver !== "ai" && row.url === "") { message = "Enter the source URL."; messageError = true; return }
    if (row.kind === "local" && row.path === "") { message = "Enter the file path (relative to the data directory)."; messageError = true; return }
    if (row.kind === "remote" && row.driver === "generic" && row.url.indexOf("{word}") < 0) {
      message = "The URL must contain {word} (and {from}/{to} for translators)."; messageError = true; return
    }
    root.saveSource(row, clearKeyCheck.checked_)
  }

  function datasetById(id) {
    for (var i = 0; i < datasets.length; i++) if (datasets[i].id === id) return datasets[i]
    return null
  }

  function humanBytes(n) {
    if (!n) return ""
    if (n >= 1073741824) return (n / 1073741824).toFixed(2) + " GB"
    if (n >= 1048576) return (n / 1048576).toFixed(0) + " MB"
    return Math.round(n / 1024) + " kB"
  }

  function localInfo(row) {
    var st = localStatus[row.id]
    if (!st) return ""
    if (!st.installed) return "not installed"
    return (st.entries ? st.entries.toLocaleString() + " entries" : "installed")
  }

  // Dropdowns assign their own `value` on selection (breaking the binding
  // to `editing`), so re-sync them whenever the edited row changes.
  onEditingChanged: {
    if (!editing) return
    driverPicker.value = editing.driver || "generic"
    formatPicker.value = editing.format || ""
  }

  component FieldLabel: Text {
    textFormat: Text.PlainText
    color: root.muted
    font.family: root.fontFamily
    font.pixelSize: Style.font.caption
    font.bold: true
  }

  // --------------------------------------------------------------- layout
  Column {
    id: layout
    anchors.fill: parent
    spacing: Style.spacing.md

    Row {
      id: tabsRow
      width: parent.width
      spacing: Style.spacing.md
      ButtonGroup {
        id: tabsGroup
        anchors.verticalCenter: parent.verticalCenter
        options: [{value: "sources", label: "Sources"}, {value: "data", label: "Data"}, {value: "history", label: "History"}]
        value: root.tab === "edit" ? "sources" : root.tab
        foreground: root.foreground
        background: "transparent"
        accent: root.accent
        onChanged: function(v) { root.tab = v; root.message = ""; if (v === "data") root.refreshDatasets() }
      }
      Item { width: Style.spacing.md; height: 1 }
      // Same height and baseline as the tab chips: the icon is kept at body
      // size so it cannot make the button taller than its neighbours.
      Button {
        visible: root.tab === "sources" || root.tab === "data"
        anchors.verticalCenter: parent.verticalCenter
        height: tabsGroup.implicitHeight
        text: "Add source"
        iconText: "󰐕"
        iconSize: Style.font.body
        bordered: true
        foreground: root.foreground
        accent: root.accent
        onClicked: root.startNew()
      }
      Button {
        visible: root.tab === "sources"
        anchors.verticalCenter: parent.verticalCenter
        height: tabsGroup.implicitHeight
        text: "Reset to defaults"
        bordered: true
        foreground: root.foreground
        accent: root.accent
        onClicked: root.resetSources()
      }
    }

    // The status of the last action (a source test, an install, a save).  It
    // sits outside the scrolling list on purpose: a test result that scrolls
    // away with the list is a test result one never reads.
    BorderSurface {
      id: msgStrip
      visible: root.message !== ""
      width: parent.width
      implicitHeight: msgText.implicitHeight + Style.spacing.sm * 2
      radius: Style.cornerRadius
      color: Util.alpha(root.messageError ? Color.urgent : root.accent, 0.10)
      borderSpec: Border.flat(Util.alpha(root.messageError ? Color.urgent : root.accent, 0.45),
                              Math.max(1, Style.normalBorderWidth))

      Text {
        id: msgText
        objectName: "prefsStatus"
        x: Style.spacing.sm
        y: Style.spacing.sm
        width: parent.width - Style.spacing.sm * 2 - dismiss.width
        textFormat: Text.PlainText
        wrapMode: Text.WordWrap
        text: root.message
        color: root.messageError ? Color.urgent : root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.bodySmall
      }
      Button {
        id: dismiss
        anchors.right: parent.right
        anchors.rightMargin: Style.spacing.xs
        anchors.verticalCenter: parent.verticalCenter
        iconText: "󰅖"
        iconSize: Style.font.body
        tooltipText: "Dismiss"
        foreground: root.foreground
        accent: root.accent
        onClicked: root.message = ""
      }
    }

    // ------------------------------------------------------ filter bar
    // Always visible above the list: which sources are shown, and whether
    // the shown set is complete enough to reorder in.
    Flow {
      id: filterBar
      visible: root.tab === "sources"
      width: parent.width
      spacing: Style.spacing.md

      ButtonGroup {
        options: [{value: "all", label: "All"}, {value: "enabled", label: "Enabled"},
                  {value: "disabled", label: "Disabled"}]
        value: root.filterEnabled
        foreground: root.foreground
        background: "transparent"
        accent: root.accent
        onChanged: function(v) { root.filterEnabled = v; root.clearSelection() }
      }
      ButtonGroup {
        options: [{value: "all", label: "All"}, {value: "dictionary", label: "Dictionary"},
                  {value: "thesaurus", label: "Thesaurus"}, {value: "translator", label: "Translation"}]
        value: root.filterType
        foreground: root.foreground
        background: "transparent"
        accent: root.accent
        onChanged: function(v) { root.filterType = v; root.clearSelection() }
      }
      Dropdown {
        id: groupPicker
        showLabel: false
        width: Style.spacing.dropdownWidth
        options: [{value: "all", label: "All sources"}, {value: "ai", label: "AI services"},
                  {value: "web", label: "Web sources"}, {value: "local", label: "Local dictionaries"},
                  {value: "wiktionary", label: "Wiktionary"}, {value: "freedict", label: "FreeDict"},
                  {value: "nokey", label: "Without a stored key"}, {value: "key", label: "With a stored key"}]
        value: root.filterGroup
        foreground: root.foreground
        accent: root.accent
        onChanged: function(v) { root.filterGroup = v; root.clearSelection() }
      }
      Row {
        spacing: Style.spacing.md
        Text {
          objectName: "filterSummary"
          anchors.verticalCenter: parent.verticalCenter
          textFormat: Text.PlainText
          text: root.visibleSources.length === root.sources.length
            ? root.sources.length + " sources"
            : root.visibleSources.length + " of " + root.sources.length + " sources"
          color: root.muted
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
        }
        Text {
          anchors.verticalCenter: parent.verticalCenter
          visible: !root.canReorder
          textFormat: Text.PlainText
          text: "· reordering needs all (or all enabled) sources shown"
          color: root.muted
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
        }
        Text {
          anchors.verticalCenter: parent.verticalCenter
          visible: root.canReorder && root.selectedIds.length > 0
          textFormat: Text.PlainText
          text: "· " + root.selectedIds.length + " selected – drag to reorder"
          color: root.accent
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
        }
      }
    }

    // ------------------------------------------------------- source list
    Flickable {
      id: listFlick
      visible: root.tab === "sources"
      width: parent.width
      height: layout.height - tabsRow.height - filterBar.height
              - (root.message !== "" ? msgStrip.height + layout.spacing : 0) - layout.spacing * 2
      contentWidth: width
      contentHeight: listCol.implicitHeight
      clip: true
      boundsBehavior: Flickable.StopAtBounds
      ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

      // Dragging near an edge scrolls the list, so a row can be dragged
      // further than one screenful.
      Timer {
        id: autoScroll
        interval: 16
        repeat: true
        running: root.dragging && root.autoScrollStep !== 0
        onTriggered: {
          var next = listFlick.contentY + root.autoScrollStep
          listFlick.contentY = Math.max(0, Math.min(Math.max(0, listFlick.contentHeight - listFlick.height), next))
        }
      }

      Column {
        id: listCol
        width: listFlick.width - Style.spacing.md
        spacing: Style.spacing.xs

        Repeater {
          id: sourceRepeater
          model: root.visibleSources
          delegate: BorderSurface {
            id: row
            required property var modelData
            required property int index
            readonly property bool selected: root.isSelected(modelData.id)
            width: parent.width
            implicitHeight: rowContent.implicitHeight + Style.spacing.sm * 2
            radius: Style.cornerRadius
            color: row.selected ? Util.alpha(root.accent, 0.16)
              : (rowHover.hovered ? Style.hoverFillFor(root.foreground, root.accent) : "transparent")
            borderSpec: row.selected
              ? Border.flat(Util.alpha(root.accent, 0.6), Math.max(1, Style.normalBorderWidth))
              : Border.controlSpec("normal", root.foreground, root.accent)
            opacity: row.modelData.enabled ? 1 : 0.6
            HoverHandler { id: rowHover }

            // Selection and dragging.  Declared before the content, so the
            // switches and buttons on top keep their own clicks.
            MouseArea {
              anchors.fill: parent
              acceptedButtons: Qt.LeftButton
              property real pressY: 0
              property bool collapseOnRelease: false

              onPressed: function(mouse) {
                pressY = mouse.y
                collapseOnRelease = false
                var ctrl = (mouse.modifiers & Qt.ControlModifier) !== 0
                var shift = (mouse.modifiers & Qt.ShiftModifier) !== 0
                if (ctrl || shift) {
                  root.selectRow(row.index, ctrl, shift)
                } else if (row.selected) {
                  collapseOnRelease = true     // keep the block draggable
                } else {
                  root.selectRow(row.index, false, false)
                }
              }

              onPositionChanged: function(mouse) {
                if (!pressed) return
                var inList = mapToItem(listFlick, mouse.x, mouse.y)
                if (!root.dragging) {
                  if (!root.canReorder || Math.abs(mouse.y - pressY) < Style.space(6)) return
                  if (!row.selected) root.selectRow(row.index, false, false)
                  root.dragging = true
                }
                root.dragPointY = inList.y
                root.autoScrollStep = inList.y < Style.space(28) ? -Style.space(10)
                  : (inList.y > listFlick.height - Style.space(28) ? Style.space(10) : 0)
                root.dropIndex = root.dropIndexAt(mapToItem(listCol, mouse.x, mouse.y).y)
              }

              onReleased: {
                if (root.dragging) {
                  root.finishDrag()
                } else if (collapseOnRelease) {
                  root.selectRow(row.index, false, false)
                }
                collapseOnRelease = false
              }
              onCanceled: root.cancelDrag()
              onDoubleClicked: root.startEdit(row.modelData)
            }

            Row {
              id: rowContent
              x: Style.spacing.sm
              y: Style.spacing.sm
              width: parent.width - Style.spacing.sm * 2
              spacing: Style.spacing.md

              // Drag handle: the whole row drags, but a handle says so.
              Text {
                anchors.verticalCenter: parent.verticalCenter
                textFormat: Text.PlainText
                text: "󰇙"
                visible: root.canReorder
                color: row.selected ? root.accent : root.muted
                font.family: root.fontFamily
                font.pixelSize: Style.font.body
              }
              ToggleSwitch {
                id: rowSwitch
                anchors.verticalCenter: parent.verticalCenter
                checked: row.modelData.enabled
                foreground: root.foreground
                accent: root.accent
                onToggled: root.enableSource(row.modelData.id, !row.modelData.enabled)
              }
              Column {
                width: parent.width - rowSwitch.width - actions.width - parent.spacing * 3 - Style.space(20)
                anchors.verticalCenter: parent.verticalCenter
                spacing: Style.spacing.xxs
                Row {
                  spacing: Style.spacing.md
                  Text {
                    id: rowName
                    textFormat: Text.PlainText
                    text: row.modelData.name
                    color: row.selected ? root.accent : root.foreground
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.body
                    font.bold: true
                  }
                  Text {
                    textFormat: Text.PlainText
                    text: row.modelData.type + " · " + (row.modelData.kind === "local" ? "local" : "remote")
                      + (row.modelData.type === "translator" ? " · " + (row.modelData.translation_mode === "text" ? "full text" : "word") : "")
                      + (row.modelData.languages && row.modelData.languages.length ? " · " + row.modelData.languages.join(",") : "")
                      + (row.modelData.pairs && row.modelData.pairs.length ? " · " + row.modelData.pairs.map(function(p) { return p[0] + "→" + p[1] }).slice(0, 4).join(" ") + (row.modelData.pairs.length > 4 ? " …" : "") : "")
                      + (row.modelData.has_key ? " · key set" : "")
                    color: root.muted
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.caption
                    anchors.baseline: rowName.baseline
                  }
                }
                Text {
                  width: parent.width
                  textFormat: Text.PlainText
                  text: row.modelData.kind === "local"
                    ? row.modelData.path + "  —  " + root.localInfo(row.modelData)
                    : (row.modelData.driver === "ai"
                       ? (root.aiPreset(row.modelData.service || "claude")
                          ? root.aiPreset(row.modelData.service || "claude").label : "AI service")
                         + " · " + (row.modelData.transport === "api" ? "HTTP API" : "signed-in CLI")
                       : row.modelData.url)
                  color: root.muted
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.caption
                  elide: Text.ElideMiddle
                }
              }
              Row {
                id: actions
                anchors.verticalCenter: parent.verticalCenter
                spacing: Style.spacing.xs
                Button {
                  visible: row.modelData.kind === "local" && row.modelData.dataset !== "" && !(root.localStatus[row.modelData.id] && root.localStatus[row.modelData.id].installed)
                  text: "Install"
                  bordered: true
                  foreground: root.foreground
                  accent: root.accent
                  tooltipText: "Download and index " + row.modelData.dataset
                  onClicked: { root.tab = "data"; root.refreshDatasets(); root.installDataset(row.modelData.dataset) }
                }
                Button { iconText: "󰙨"; tooltipText: "Test with a sample word"; foreground: root.foreground; accent: root.accent; onClicked: root.testSource(row.modelData.id) }
                Button { iconText: "󰏫"; tooltipText: "Edit"; foreground: root.foreground; accent: root.accent; onClicked: root.startEdit(row.modelData) }
                Button {
                  iconText: "󰁝"
                  enabled: root.canReorder
                  tooltipText: root.canReorder
                    ? (root.selectionFor(row.modelData.id).length > 1 ? "Move the selection up" : "Move up")
                    : "Show all (or all enabled) sources to reorder"
                  foreground: root.foreground
                  accent: root.accent
                  onClicked: root.moveSelection(row.modelData.id, -1)
                }
                Button {
                  iconText: "󰁅"
                  enabled: root.canReorder
                  tooltipText: root.canReorder
                    ? (root.selectionFor(row.modelData.id).length > 1 ? "Move the selection down" : "Move down")
                    : "Show all (or all enabled) sources to reorder"
                  foreground: root.foreground
                  accent: root.accent
                  onClicked: root.moveSelection(row.modelData.id, 1)
                }
                Button { iconText: "󰆴"; tooltipText: "Delete"; foreground: root.foreground; accent: root.accent; onClicked: root.deleteSource(row.modelData.id) }
              }
            }
          }
        }
      }

      // Where the dragged block would land.
      Rectangle {
        objectName: "dropIndicator"
        parent: listCol.parent
        visible: root.dragging && root.dropIndex >= 0
        x: listCol.x
        y: root.dropLineY()
        width: listCol.width
        height: Math.max(2, Style.space(2))
        color: root.accent
        radius: height / 2
      }
    }

    // ------------------------------------------------------------ editor
    Flickable {
      id: editFlick
      visible: root.tab === "edit" && root.editing !== null
      width: parent.width
      height: listFlick.height
      contentWidth: width
      contentHeight: editCol.implicitHeight + Style.spacing.lg
      clip: true
      boundsBehavior: Flickable.StopAtBounds
      ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

      Column {
        id: editCol
        width: editFlick.width - Style.spacing.md
        spacing: Style.spacing.lg

        Text {
          textFormat: Text.PlainText
          text: root.editingNew ? "New source" : "Edit source" + (root.editing && root.editing.builtin ? "  (built-in)" : "")
          color: root.foreground
          font.family: root.fontFamily
          font.pixelSize: Style.font.title
          font.bold: true
        }

        Column {
          width: parent.width
          spacing: Style.spacing.labelGap
          FieldLabel { text: "Name" }
          TextField {
            id: nameField
            width: parent.width
            text: ""
            placeholderText: "e.g. Wordnik"
            foreground: root.foreground
            accent: root.accent
          }
        }

        Row {
          spacing: Style.spacing.huge
          Column {
            spacing: Style.spacing.labelGap
            FieldLabel { text: "Enabled" }
            ToggleSwitch {
              checked: root.editing ? root.editing.enabled : true
              foreground: root.foreground
              accent: root.accent
              onToggled: root.setEditField("enabled", !root.editing.enabled)
            }
          }
          Column {
            spacing: Style.spacing.labelGap
            FieldLabel { text: "Source type" }
            ButtonGroup {
              options: [{value: "dictionary", label: "Dictionary"}, {value: "thesaurus", label: "Thesaurus"}, {value: "translator", label: "Translator"}]
              value: root.editing ? root.editing.type : "dictionary"
              foreground: root.foreground
              background: "transparent"
              accent: root.accent
              onChanged: function(v) { root.setEditField("type", v) }
            }
          }
          Column {
            spacing: Style.spacing.labelGap
            FieldLabel { text: "Location" }
            ButtonGroup {
              options: [{value: "remote", label: "Remote (URL)"}, {value: "local", label: "Local file"}]
              value: root.editing ? root.editing.kind : "remote"
              foreground: root.foreground
              background: "transparent"
              accent: root.accent
              onChanged: function(v) { root.setEditField("kind", v) }
            }
          }
        }

        Row {
          visible: !!(root.editing && root.editing.kind === "remote")
          width: parent.width
          spacing: Style.spacing.huge
          Dropdown {
            id: driverPicker
            label: "Driver"
            width: Style.spacing.dropdownWidth
            options: root.driverOptions("remote", root.editing ? root.editing.type : "")
            value: root.editing ? root.editing.driver : "generic"
            foreground: root.foreground
            accent: root.accent
            onChanged: function(v) { root.setEditField("driver", v) }
          }
          Text {
            width: parent.width - Style.spacing.dropdownWidth - Style.spacing.huge
            textFormat: Text.PlainText
            wrapMode: Text.WordWrap
            text: root.editing && root.driverInfo(root.editing.driver) ? root.driverInfo(root.editing.driver).description : ""
            color: root.muted
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
            anchors.bottom: parent.bottom
          }
        }

        // ------------------------------------------------------ AI service
        Column {
          visible: !!(root.editing && root.editing.driver === "ai")
          width: parent.width
          spacing: Style.spacing.md

          Row {
            width: parent.width
            spacing: Style.spacing.huge
            Dropdown {
              id: aiServicePicker
              label: "Service"
              width: Style.spacing.dropdownWidth
              options: root.aiServices()
              value: root.editing ? (root.editing.service || "claude") : "claude"
              foreground: root.foreground
              accent: root.accent
              onChanged: function(v) { root.setEditField("service", v) }
            }
            Column {
              spacing: Style.spacing.labelGap
              anchors.bottom: parent.bottom
              FieldLabel { text: "Access" }
              ButtonGroup {
                options: [{value: "cli", label: "Signed-in CLI", tooltip: "Runs the service's own command line tool, which uses your account – free plans included. No API key."},
                          {value: "api", label: "HTTP API + key", tooltip: "Calls the service's API with the key stored in the keyring."}]
                value: root.editing ? (root.editing.transport || "cli") : "cli"
                foreground: root.foreground
                background: "transparent"
                accent: root.accent
                onChanged: function(v) { root.setEditField("transport", v) }
              }
            }
          }

          Text {
            width: parent.width
            textFormat: Text.PlainText
            wrapMode: Text.WordWrap
            text: root.editing && root.editing.transport === "api"
              ? "The API is billed per request by the service. The key is kept in the keyring, never in a file."
              : "Uses the account you are signed in to in the service's CLI – a free plan works, a paid one (Claude Pro, for instance) is simply used as it is."
            color: root.muted
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
          }

          Row {
            width: parent.width
            spacing: Style.spacing.huge
            Column {
              width: (parent.width - Style.spacing.huge) / 2
              spacing: Style.spacing.labelGap
              FieldLabel { text: "Model  (empty = the service's small default)" }
              TextField {
                id: modelField
                width: parent.width
                text: ""
                placeholderText: root.editing && root.aiPreset(root.editing.service || "claude")
                  ? root.aiPreset(root.editing.service || "claude").model : ""
                foreground: root.foreground
                accent: root.accent
              }
            }
            Column {
              width: (parent.width - Style.spacing.huge) / 2
              spacing: Style.spacing.labelGap
              FieldLabel { text: "Command  (empty = the service's CLI)" }
              TextField {
                id: commandField
                width: parent.width
                enabled: !(root.editing && root.editing.transport === "api")
                text: ""
                placeholderText: root.editing && root.aiPreset(root.editing.service || "claude")
                  ? root.aiPreset(root.editing.service || "claude").command : ""
                foreground: root.foreground
                accent: root.accent
              }
            }
          }

          Column {
            visible: !!(root.editing && root.editing.transport === "api")
            width: parent.width
            spacing: Style.spacing.labelGap
            FieldLabel { text: "API endpoint  (empty = the service's own; {model} is substituted)" }
            TextField {
              id: aiEndpointField
              width: parent.width
              text: ""
              placeholderText: "https://…"
              foreground: root.foreground
              accent: root.accent
            }
          }
        }

        Column {
          visible: !!(root.editing && root.editing.kind === "remote" && root.editing.driver !== "ai")
          width: parent.width
          spacing: Style.spacing.labelGap
          FieldLabel { text: "URL  (use {word}; translators may also use {from} and {to})" }
          TextField {
            id: urlField
            width: parent.width
            text: ""
            placeholderText: "https://example.org/dictionary/{word}"
            foreground: root.foreground
            accent: root.accent
          }
        }

        Column {
          visible: !!(root.editing && root.editing.kind === "local")
          width: parent.width
          spacing: Style.spacing.labelGap
          FieldLabel { text: "File path  (relative to the data directory; kaikki JSONL, FreeDict TEI, CC-CEDICT, ECDICT CSV, Unihan, dictd, TSV, JSON or an omababel index)" }
          TextField {
            id: pathField
            width: parent.width
            text: ""
            placeholderText: "my-dictionary.tsv"
            foreground: root.foreground
            accent: root.accent
          }
          Row {
            spacing: Style.spacing.huge
            topPadding: Style.spacing.sm
            Dropdown {
              id: formatPicker
              label: "Format"
              width: Style.spacing.dropdownWidth
              options: [{value: "", label: "auto-detect"}, {value: "kaikki", label: "kaikki / wiktextract JSONL"},
                        {value: "tei", label: "FreeDict TEI"}, {value: "dictd", label: "dictd"},
                        {value: "cedict", label: "CC-CEDICT"}, {value: "ecdict", label: "ECDICT CSV"},
                        {value: "unihan", label: "Unihan"}, {value: "tsv", label: "TSV"}, {value: "json", label: "JSON"}]
              value: root.editing ? root.editing.format : ""
              foreground: root.foreground
              accent: root.accent
              onChanged: function(v) { root.setEditField("format", v) }
            }
          }
        }

        Row {
          width: parent.width
          spacing: Style.spacing.huge
          Column {
            width: (parent.width - Style.spacing.huge) / 2
            spacing: Style.spacing.labelGap
            FieldLabel { text: "Languages  (codes, comma separated; empty = any)" }
            TextField {
              id: langField
              width: parent.width
              text: ""
              placeholderText: "de, en"
              foreground: root.foreground
              accent: root.accent
            }
          }
          Column {
            visible: !!(root.editing && root.editing.type === "translator")
            width: (parent.width - Style.spacing.huge) / 2
            spacing: Style.spacing.labelGap
            FieldLabel { text: "Language pairs  (from-to, e.g. de-en; empty = derive from languages)" }
            TextField {
              id: pairsField
              width: parent.width
              text: ""
              placeholderText: "de-en, en-de"
              foreground: root.foreground
              accent: root.accent
            }
          }
        }

        Column {
          visible: !!(root.editing && root.editing.type === "translator")
          spacing: Style.spacing.labelGap
          FieldLabel { text: "Translation kind" }
          ButtonGroup {
            options: [{value: "word", label: "Word translations (like LEO)"}, {value: "text", label: "Full text service (like Google / DeepL)"}]
            value: root.editing ? root.editing.translation_mode : "word"
            foreground: root.foreground
            background: "transparent"
            accent: root.accent
            onChanged: function(v) { root.setEditField("translation_mode", v) }
          }
        }

        Column {
          visible: !!(root.editing && root.editing.kind === "remote")
          width: parent.width
          spacing: Style.spacing.labelGap
          FieldLabel {
            text: "API key" + (root.editing && root.driverInfo(root.editing.driver) && root.driverInfo(root.editing.driver).key_hint
              ? "  —  " + root.driverInfo(root.editing.driver).key_hint : "  (optional, for paid services)")
          }
          Text {
            width: parent.width
            textFormat: Text.PlainText
            wrapMode: Text.WordWrap
            text: root.keyring && root.keyring.available
              ? "Stored in the login keyring (" + root.keyring.backend + "), never in a file."
              : "No keyring found on this system: install libsecret (secret-tool) and run gnome-keyring, "
                + "or point the source at an environment variable or a command below."
            color: root.keyring && root.keyring.available ? root.muted : Color.urgent
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
          }
          Text {
            width: parent.width
            visible: !!(root.editing && root.editing.key_insecure)
            textFormat: Text.PlainText
            wrapMode: Text.WordWrap
            text: "This key is still stored in plain text in sources.json because it could not be moved "
                + "to a keyring. Set it again once a keyring is running."
            color: Color.urgent
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
          }
          Row {
            width: parent.width
            spacing: Style.spacing.md
            TextField {
              id: keyField
              width: parent.width - clearKeyRow.width - Style.spacing.md
              password: true
              enabled: !(root.editing && (root.editing.api_key_env || root.editing.api_key_cmd))
              placeholderText: root.editing && root.editing.has_key
                ? "key stored in the " + (root.editing.key_storage || "keyring") + " – enter a new one to replace it"
                : "no key"
              foreground: root.foreground
              accent: root.accent
            }
            Row {
              id: clearKeyRow
              spacing: Style.spacing.sm
              visible: !!(root.editing && root.editing.has_key)
              anchors.verticalCenter: parent.verticalCenter
              ToggleSwitch {
                id: clearKeyCheck
                property bool checked_: false
                checked: checked_
                foreground: root.foreground
                accent: root.accent
                onToggled: checked_ = !checked_
                anchors.verticalCenter: parent.verticalCenter
              }
              Text {
                textFormat: Text.PlainText
                text: "remove stored key"
                color: root.muted
                font.family: root.fontFamily
                font.pixelSize: Style.font.caption
                anchors.verticalCenter: parent.verticalCenter
              }
            }
          }

          FieldLabel { text: "…or read the key from an environment variable" }
          TextField {
            id: keyEnvField
            width: parent.width
            text: ""
            placeholderText: "e.g. DEEPL_API_KEY"
            foreground: root.foreground
            accent: root.accent
          }
          FieldLabel { text: "…or from the output of a command (pass, gopass, age …)" }
          TextField {
            id: keyCmdField
            width: parent.width
            text: ""
            placeholderText: "e.g. pass show omababel/deepl"
            foreground: root.foreground
            accent: root.accent
          }
        }

        Column {
          width: parent.width
          spacing: Style.spacing.labelGap
          FieldLabel { text: "Notes" }
          TextField {
            id: notesField
            width: parent.width
            text: ""
            foreground: root.foreground
            accent: root.accent
          }
        }

        Row {
          spacing: Style.spacing.md
          Button { text: "Save"; bordered: true; focusable: true; foreground: root.foreground; accent: root.accent; onClicked: root.commitEdit() }
          Button { text: "Cancel"; bordered: true; focusable: true; foreground: root.foreground; accent: root.accent; onClicked: root.cancelEdit() }
          Button {
            visible: !root.editingNew
            text: "Delete"
            bordered: true
            foreground: root.foreground
            accent: root.accent
            onClicked: { root.deleteSource(root.editing.id); root.cancelEdit() }
          }
        }
      }
    }

    // ---------------------------------------------------------- history
    Column {
      id: historyTab
      visible: root.tab === "history"
      width: parent.width
      spacing: Style.spacing.lg

      Text {
        width: parent.width
        textFormat: Text.PlainText
        wrapMode: Text.WordWrap
        text: "The search history feeds the ▾ dropdown of the search field and the Ctrl+P / Ctrl+N shortcuts. "
          + "It is stored in ~/.local/state/omababel/history.json."
        color: root.muted
        font.family: root.fontFamily
        font.pixelSize: Style.font.bodySmall
      }

      Row {
        spacing: Style.spacing.huge
        NumberField {
          id: historyMaxField
          label: "Maximum number of entries"
          from: 1
          to: 100000
          stepSize: 100
          value: root.historyMax
          foreground: root.foreground
          accent: root.accent
          onModified: function(v) { root.historyMaxRequested(v) }
        }
        Column {
          anchors.bottom: parent.bottom
          spacing: Style.spacing.labelGap
          FieldLabel { text: "Stored" }
          Text {
            textFormat: Text.PlainText
            text: root.historyCount + " of " + root.historyMax + " entries"
            color: root.foreground
            font.family: root.fontFamily
            font.pixelSize: Style.font.body
            height: Style.spacing.controlHeight
            verticalAlignment: Text.AlignVCenter
          }
        }
      }

      Text {
        width: parent.width
        textFormat: Text.PlainText
        wrapMode: Text.WordWrap
        text: "Lowering the limit drops the oldest entries immediately. Use the arrows or type a number and press Enter."
        color: root.muted
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
      }

      Button {
        text: "Clear history"
        iconText: "󰆴"
        iconSize: Style.font.body
        bordered: true
        enabled: root.historyCount > 0
        opacity: enabled ? 1 : 0.5
        foreground: root.foreground
        accent: root.accent
        onClicked: root.clearHistoryRequested()
      }
    }

    // ------------------------------------------------------------- data
    Flickable {
      id: dataFlick
      visible: root.tab === "data"
      width: parent.width
      height: listFlick.height
      contentWidth: width
      contentHeight: dataCol.implicitHeight + Style.spacing.lg
      clip: true
      boundsBehavior: Flickable.StopAtBounds
      ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

      Column {
        id: dataCol
        width: dataFlick.width - Style.spacing.md
        spacing: Style.spacing.sm

        Text {
          width: parent.width
          textFormat: Text.PlainText
          wrapMode: Text.WordWrap
          text: "Local dictionaries are downloaded on demand and indexed into the data directory. Wiktionary and FreeDict dumps are large (100 MB – 2 GB) and CC BY-SA / GPL licensed; CC-CEDICT, ECDICT and Unihan are small."
          color: root.muted
          font.family: root.fontFamily
          font.pixelSize: Style.font.bodySmall
        }

        BorderSurface {
          visible: !!(root.installer && (root.installer.running || root.installer.phase === "error"))
          width: parent.width
          implicitHeight: installCol.implicitHeight + Style.spacing.md * 2
          radius: Style.cornerRadius
          color: Style.selectedFillFor(root.foreground, root.accent)
          borderSpec: Border.controlSpec("selected", root.foreground, root.accent)
          Column {
            id: installCol
            x: Style.spacing.md
            y: Style.spacing.md
            width: parent.width - Style.spacing.md * 2
            spacing: Style.spacing.xs
            Row {
              width: parent.width
              spacing: Style.spacing.md
              Text {
                id: installTitle
                textFormat: Text.PlainText
                text: root.installer ? (root.installer.running ? "Installing " : "Failed: ") + root.installer.datasetId : ""
                color: root.foreground
                font.family: root.fontFamily
                font.pixelSize: Style.font.body
                font.bold: true
              }
              Text {
                textFormat: Text.PlainText
                text: root.installer ? root.installer.message : ""
                color: root.installer && root.installer.phase === "error" ? Color.urgent : root.muted
                font.family: root.fontFamily
                font.pixelSize: Style.font.bodySmall
                anchors.baseline: installTitle.baseline
              }
            }
            Rectangle {
              visible: !!(root.installer && root.installer.running)
              width: parent.width
              height: Style.space(4)
              radius: height / 2
              color: Style.normalFillFor(root.foreground, root.accent)
              Rectangle {
                id: progressBar
                property real pulseX: 0
                readonly property bool determinate: root.installer !== null && root.installer.fraction >= 0
                height: parent.height
                radius: parent.radius
                color: root.accent
                width: determinate ? parent.width * root.installer.fraction : parent.width * 0.25
                x: determinate ? 0 : pulseX
                NumberAnimation on pulseX {
                  running: root.installer !== null && root.installer.running && !progressBar.determinate
                  from: 0; to: installCol.width * 0.75
                  duration: 1200; loops: Animation.Infinite; easing.type: Easing.InOutSine
                }
              }
            }
            Button {
              visible: !!(root.installer && root.installer.running)
              text: "Cancel"
              bordered: true
              foreground: root.foreground
              accent: root.accent
              onClicked: root.installer.cancel()
            }
          }
        }

        Repeater {
          model: root.sortedDatasets
          delegate: Column {
            id: dsEntry
            required property var modelData
            required property int index
            width: parent.width
            spacing: Style.spacing.sm

            // One line between what is installed and what is not.
            Item {
              width: parent.width
              height: visible ? Style.spacing.md * 2 : 0
              visible: dsEntry.index === root.installedCount() && dsEntry.index > 0
              Rectangle {
                anchors.verticalCenter: parent.verticalCenter
                width: parent.width
                height: Math.max(1, Style.normalBorderWidth)
                color: Util.alpha(root.foreground, 0.25)
              }
              Rectangle {
                objectName: "notInstalledLabel"
                anchors.verticalCenter: parent.verticalCenter
                anchors.left: parent.left
                width: notInstalledText.implicitWidth + Style.spacing.md
                height: notInstalledText.implicitHeight
                color: Color.menu.background
                Text {
                  id: notInstalledText
                  anchors.centerIn: parent
                  textFormat: Text.PlainText
                  text: "not installed"
                  color: root.muted
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.caption
                }
              }
            }

            BorderSurface {
            id: dsRow
            readonly property var modelData: dsEntry.modelData
            width: parent.width
            implicitHeight: dsContent.implicitHeight + Style.spacing.sm * 2
            radius: Style.cornerRadius
            color: "transparent"
            borderSpec: Border.controlSpec("normal", root.foreground, root.accent)
            Row {
              id: dsContent
              x: Style.spacing.sm
              y: Style.spacing.sm
              width: parent.width - Style.spacing.sm * 2
              spacing: Style.spacing.md
              Column {
                width: parent.width - dsActions.width - parent.spacing
                spacing: Style.spacing.xxs
                Row {
                  spacing: Style.spacing.md
                  Text {
                    id: dsTitle
                    textFormat: Text.PlainText
                    text: (dsRow.modelData.installed ? "✔ " : "") + dsRow.modelData.title
                    color: root.foreground
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.body
                    font.bold: true
                  }
                  Text {
                    textFormat: Text.PlainText
                    text: dsRow.modelData.id + " · " + dsRow.modelData.license
                      + (dsRow.modelData.installed ? " · " + (dsRow.modelData.entries || 0).toLocaleString() + " entries · " + root.humanBytes(dsRow.modelData.size) : "")
                    color: root.muted
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.caption
                    anchors.baseline: dsTitle.baseline
                  }
                }
                Text {
                  width: parent.width
                  textFormat: Text.PlainText
                  wrapMode: Text.WordWrap
                  text: dsRow.modelData.description
                  color: root.muted
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.caption
                }
              }
              Row {
                id: dsActions
                anchors.verticalCenter: parent.verticalCenter
                spacing: Style.spacing.xs
                Button {
                  text: dsRow.modelData.installed ? "Reinstall" : "Install"
                  bordered: true
                  enabled: !(root.installer && root.installer.running)
                  opacity: enabled ? 1 : 0.5
                  foreground: root.foreground
                  accent: root.accent
                  onClicked: root.installDataset(dsRow.modelData.id)
                }
                Button {
                  visible: dsRow.modelData.installed
                  iconText: "󰆴"
                  tooltipText: "Delete the index"
                  bordered: true
                  foreground: root.foreground
                  accent: root.accent
                  onClicked: root.removeDataset(dsRow.modelData.id)
                }
              }
            }
            }
          }
        }
      }
    }
  }
}
