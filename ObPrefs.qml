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
  property string tab: "sources"    // "sources" | "data" | "edit"
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

  signal saveSource(var source, bool clearKey)
  signal deleteSource(string id)
  signal enableSource(string id, bool enabled)
  signal moveSource(string id, int delta)
  signal resetSources()
  signal installDataset(string id)
  signal removeDataset(string id)
  signal refreshDatasets()
  signal testSource(string id)
  signal closeRequested()

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
      translation_mode: "text", api_key: "", languages: [], pairs: [], builtin: false, notes: "", has_key: false
    }
    editingNew = true
    message = ""
    tab = "edit"
    Qt.callLater(function() { nameField.forceActiveFocus() })
  }

  function startEdit(row) {
    var copy = JSON.parse(JSON.stringify(row))
    copy.api_key = ""
    editing = copy
    editingNew = false
    message = ""
    tab = "edit"
    Qt.callLater(function() { nameField.forceActiveFocus() })
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
    }
    editing = copy
  }

  function commitEdit() {
    var row = JSON.parse(JSON.stringify(editing))
    row.name = nameField.text.trim()
    row.url = urlField.text.trim()
    row.path = pathField.text.trim()
    row.languages = langField.text.split(/[,;\s]+/).filter(function(x) { return x !== "" })
    row.pairs = pairsField.text.split(/[,;\s]+/).filter(function(x) { return x !== "" })
    row.api_key = keyField.text
    row.notes = notesField.text.trim()
    if (row.name === "") { message = "Give the source a name."; messageError = true; return }
    if (row.kind === "remote" && row.url === "") { message = "Enter the source URL."; messageError = true; return }
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
        options: [{value: "sources", label: "Sources"}, {value: "data", label: "Data"}]
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
        visible: root.tab !== "edit"
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

    Text {
      id: msgText
      visible: root.message !== ""
      width: parent.width
      textFormat: Text.PlainText
      wrapMode: Text.WordWrap
      text: root.message
      color: root.messageError ? Color.urgent : root.muted
      font.family: root.fontFamily
      font.pixelSize: Style.font.bodySmall
    }

    // ------------------------------------------------------- source list
    Flickable {
      id: listFlick
      visible: root.tab === "sources"
      width: parent.width
      height: layout.height - tabsRow.height - (root.message !== "" ? msgText.height + layout.spacing : 0) - layout.spacing
      contentWidth: width
      contentHeight: listCol.implicitHeight
      clip: true
      boundsBehavior: Flickable.StopAtBounds
      ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

      Column {
        id: listCol
        width: listFlick.width - Style.spacing.md
        spacing: Style.spacing.xs

        Repeater {
          model: root.sources
          delegate: BorderSurface {
            id: row
            required property var modelData
            required property int index
            width: parent.width
            implicitHeight: rowContent.implicitHeight + Style.spacing.sm * 2
            radius: Style.cornerRadius
            color: rowHover.hovered ? Style.hoverFillFor(root.foreground, root.accent) : "transparent"
            borderSpec: Border.controlSpec("normal", root.foreground, root.accent)
            opacity: row.modelData.enabled ? 1 : 0.6
            HoverHandler { id: rowHover }

            Row {
              id: rowContent
              x: Style.spacing.sm
              y: Style.spacing.sm
              width: parent.width - Style.spacing.sm * 2
              spacing: Style.spacing.md

              ToggleSwitch {
                id: rowSwitch
                anchors.verticalCenter: parent.verticalCenter
                checked: row.modelData.enabled
                foreground: root.foreground
                accent: root.accent
                onToggled: root.enableSource(row.modelData.id, !row.modelData.enabled)
              }
              Column {
                width: parent.width - rowSwitch.width - actions.width - parent.spacing * 2
                anchors.verticalCenter: parent.verticalCenter
                spacing: Style.spacing.xxs
                Row {
                  spacing: Style.spacing.md
                  Text {
                    id: rowName
                    textFormat: Text.PlainText
                    text: row.modelData.name
                    color: root.foreground
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
                    : row.modelData.url
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
                Button { iconText: "󰁝"; tooltipText: "Move up"; foreground: root.foreground; accent: root.accent; onClicked: root.moveSource(row.modelData.id, -1) }
                Button { iconText: "󰁅"; tooltipText: "Move down"; foreground: root.foreground; accent: root.accent; onClicked: root.moveSource(row.modelData.id, 1) }
                Button { iconText: "󰆴"; tooltipText: "Delete"; foreground: root.foreground; accent: root.accent; onClicked: root.deleteSource(row.modelData.id) }
              }
            }
          }
        }
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
            text: root.editing ? root.editing.name : ""
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

        Column {
          visible: !!(root.editing && root.editing.kind === "remote")
          width: parent.width
          spacing: Style.spacing.labelGap
          FieldLabel { text: "URL  (use {word}; translators may also use {from} and {to})" }
          TextField {
            id: urlField
            width: parent.width
            text: root.editing ? root.editing.url : ""
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
            text: root.editing ? root.editing.path : ""
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
              text: root.editing && root.editing.languages ? root.editing.languages.join(", ") : ""
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
              text: root.editing && root.editing.pairs ? root.editing.pairs.map(function(p) { return p[0] + "-" + p[1] }).join(", ") : ""
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
          Row {
            width: parent.width
            spacing: Style.spacing.md
            TextField {
              id: keyField
              width: parent.width - clearKeyRow.width - Style.spacing.md
              password: true
              placeholderText: root.editing && root.editing.has_key ? "key stored – enter a new one to replace it" : "no key"
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
        }

        Column {
          width: parent.width
          spacing: Style.spacing.labelGap
          FieldLabel { text: "Notes" }
          TextField {
            id: notesField
            width: parent.width
            text: root.editing ? root.editing.notes : ""
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
          model: root.datasets
          delegate: BorderSurface {
            id: dsRow
            required property var modelData
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
