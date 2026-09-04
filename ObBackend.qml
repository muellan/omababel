import QtQuick
import Quickshell.Io

// Bridge to backend/omababel.py.
//
// One python process per request: the request is a single JSON line on
// stdin, the reply the *last* JSON line on stdout.  Requests are queued so
// they never interleave; `busy` is true while one is running.
//
// A request may stream: every line before the reply that carries an `event`
// is handed to the call's `onProgress` callback as it arrives.  That is how
// a search shows each source's result while the slow ones are still running.
// The long install operation still uses ObInstaller.
//
// A process is *never* started from inside another process' `onExited`
// handler, neither directly nor through a reply callback that issues the
// next request (which is what the panel does while it loads its state).
// Re-arming a Process while Quickshell is still reaping the previous one
// took the whole shell down; every start therefore goes through `pump()`,
// which only ever runs from the event loop.
Item {
  id: root

  property string helperPath: ""
  property string pythonBin: "python3"
  property bool busy: false
  property var pending: []
  property string lastError: ""
  // True while a reply callback runs.  Requests issued from a callback are
  // queued and dispatched afterwards, never from within the exit handler.
  property bool inCallback: false

  signal failed(string message)

  // `onProgress` is optional and receives every streamed event object.
  function call(op, params, done, onProgress) {
    pending = pending.concat([{req: {op: op, params: params || {}}, done: done,
                               progress: onProgress || null}])
    schedule()
  }

  // Cheap round trip.  Called once when the panel is created so the first
  // user visible request does not pay for the interpreter start and the
  // bytecode compilation of the backend (which is what made the very first
  // open after an install or an update so much slower than every later one).
  function warmup() { call("ping", {}, null) }

  // Drop queued (not yet started) requests of the given op – used when a new
  // search supersedes older ones still waiting in line.
  function dropPending(op) {
    pending = pending.filter(function(item) { return item.req.op !== op })
  }

  function schedule() { Qt.callLater(root.pump) }

  // Hands the reply to the caller and lets the queue move on.  Runs from the
  // event loop after the process has exited (see Process.onExited).
  function finish() {
    if (!root.busy) return
    var reply = null
    try {
      reply = proc.responseText ? JSON.parse(proc.responseText) : null
    } catch (e) {
      reply = null
    }
    if (!reply || typeof reply !== "object") {
      var msg = proc.errorText.trim()
      if (msg.length > 400) msg = msg.slice(-400)
      reply = {ok: false, error: {code: "helper_failed",
                                  message: proc.exitCode === 0 ? "The backend returned no valid reply."
                                    : ("Backend failed (exit " + proc.exitCode + "): " + (msg || "no output"))}}
    }
    if (!reply.error) reply.error = {code: "unknown", message: "unknown error"}
    var cb = proc.done
    proc.done = null
    proc.progress = null
    proc.responseText = ""
    proc.errorText = ""
    root.busy = false
    root.inCallback = true
    try {
      if (!reply.ok) {
        root.lastError = reply.error.message || "unknown error"
        root.failed(root.lastError)
      }
      if (cb) cb(reply)
    } catch (e2) {
      console.warn("omababel: reply handler threw:", e2)
    }
    root.inCallback = false
    // Never start the next process from a reply callback – let the event loop.
    root.schedule()
  }

  // The single place a backend process is started.  Only ever reached from
  // the event loop (Qt.callLater), so the previous process is fully gone.
  function pump() {
    if (root.inCallback || root.busy || proc.running) return
    if (pending.length === 0) return
    var item = pending[0]
    pending = pending.slice(1)
    root.busy = true
    proc.payload = JSON.stringify(item.req)
    proc.done = item.done
    proc.progress = item.progress
    proc.responseText = ""
    proc.errorText = ""
    proc.command = [pythonBin, helperPath]
    try {
      proc.running = true
    } catch (e) {
      root.busy = false
      proc.done = null
      root.lastError = "Cannot start the backend: " + e
      root.failed(root.lastError)
      root.schedule()
    }
  }

  Process {
    id: proc
    property string payload: ""
    property var done: null
    property var progress: null
    property string responseText: ""
    property string errorText: ""
    stdinEnabled: true
    onStarted: {
      write(payload + "\n")
      payload = ""
    }
    // Line by line rather than in one lump: a streamed event has to reach
    // the panel while the process is still running.
    stdout: SplitParser {
      onRead: function(line) {
        var text = String(line).trim()
        if (!text) return
        var obj = null
        try { obj = JSON.parse(text) } catch (e) { obj = null }
        if (obj && typeof obj === "object" && obj.event !== undefined) {
          if (proc.progress) {
            try { proc.progress(obj) } catch (e) { console.warn("omababel: progress handler threw:", e) }
          }
          return
        }
        proc.responseText = text          // the reply is the last non-event line
      }
    }
    stderr: StdioCollector {
      waitForEnd: true
      onStreamFinished: proc.errorText = text
    }
    property int exitCode: 0
    // The reply is assembled from the event loop, not from the exit handler:
    // it lets any stdout line the parser still holds land first, and keeps
    // the rule that nothing which may start another process runs here.
    onExited: function(code, status) {
      proc.exitCode = code
      Qt.callLater(root.finish)
    }
  }
}
