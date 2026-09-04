import QtQuick
import Quickshell.Io

// Streams `data.install` progress from the backend: every stdout line is a
// JSON object – progress events first, the final reply last.
Item {
  id: root

  property string helperPath: ""
  property string pythonBin: "python3"
  property bool running: proc.running
  property string datasetId: ""
  property string phase: ""
  property string message: ""
  property real fraction: -1     // 0..1 while downloading, -1 when unknown
  property int count: 0

  signal progress(var event)
  signal finished(var reply)

  // Last reply, handed to `finished` from the event loop (see onExited).
  property var reply: null

  function emitFinished() {
    var r = root.reply
    root.reply = null
    if (r) root.finished(r)
  }

  function install(id, extraParams) {
    if (proc.running) return false
    datasetId = id
    phase = "starting"
    message = ""
    fraction = -1
    count = 0
    var params = {id: id}
    if (extraParams) for (var k in extraParams) params[k] = extraParams[k]
    proc.payload = JSON.stringify({op: "data.install", params: params})
    proc.lastLine = ""
    proc.command = [pythonBin, helperPath]
    proc.running = true
    return true
  }

  function cancel() {
    if (proc.running) proc.running = false
  }

  function humanBytes(n) {
    if (n >= 1073741824) return (n / 1073741824).toFixed(2) + " GB"
    if (n >= 1048576) return (n / 1048576).toFixed(1) + " MB"
    if (n >= 1024) return Math.round(n / 1024) + " kB"
    return n + " B"
  }

  Process {
    id: proc
    property string payload: ""
    property string lastLine: ""
    stdinEnabled: true
    onStarted: { write(payload + "\n"); payload = "" }
    stdout: SplitParser {
      onRead: function(line) {
        var text = String(line).trim()
        if (!text) return
        proc.lastLine = text
        var obj = null
        try { obj = JSON.parse(text) } catch (e) { return }
        if (obj && obj.event === "progress") {
          root.phase = obj.phase || ""
          if (obj.phase === "download") {
            root.fraction = obj.total > 0 ? obj.bytes / obj.total : -1
            root.message = "Downloading " + root.humanBytes(obj.bytes) + (obj.total > 0 ? " / " + root.humanBytes(obj.total) : "")
          } else if (obj.phase === "import") {
            root.fraction = -1
            root.count = obj.count || 0
            root.message = "Indexing… " + (obj.count ? obj.count.toLocaleString() + " entries" : "")
          } else if (obj.phase === "resolve") {
            root.message = obj.message || "Resolving download…"
          } else if (obj.phase === "warning") {
            root.message = "Warning: " + (obj.message || "")
          } else if (obj.phase === "done") {
            root.message = "Done: " + (obj.count || 0).toLocaleString() + " entries"
          }
          root.progress(obj)
        }
      }
    }
    onExited: function(code, status) {
      var reply = null
      try { reply = JSON.parse(proc.lastLine) } catch (e) { reply = null }
      if (!reply || typeof reply !== "object" || reply.event === "progress") {
        reply = {ok: false, error: {code: "helper_failed", message: "Installer exited with code " + code}}
      }
      root.phase = reply.ok ? "done" : "error"
      if (!reply.ok) root.message = reply.error ? reply.error.message : "install failed"
      // Handlers of `finished` start further backend processes; emitting the
      // signal from the event loop instead of from inside the exit handler
      // keeps them from re-arming a Process that is still being reaped.
      root.reply = reply
      Qt.callLater(root.emitFinished)
    }
  }
}
