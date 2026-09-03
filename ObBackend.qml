import QtQuick
import Quickshell.Io

// Bridge to backend/omababel.py.
//
// One python process per request: the request is a single JSON line on
// stdin, the reply a single JSON line on stdout.  Requests are queued so
// they never interleave; `busy` is true while one is running.
// Long running operations that stream progress (data.install) use 
// ObInstaller instead.
Item {
  id: root

  property string helperPath: ""
  property string pythonBin: "python3"
  property bool busy: false
  property var pending: []
  property string lastError: ""

  signal failed(string message)

  function call(op, params, done) {
    var req = {op: op, params: params || {}}
    if (busy) {
      pending = pending.concat([{req: req, done: done}])
      return
    }
    start(req, done)
  }

  // Drop queued (not yet started) requests of the given op – used when a new
  // search supersedes older ones still waiting in line.
  function dropPending(op) {
    pending = pending.filter(function(item) { return item.req.op !== op })
  }

  function start(req, done) {
    busy = true
    proc.payload = JSON.stringify(req)
    proc.done = done
    proc.responseText = ""
    proc.errorText = ""
    proc.command = [pythonBin, helperPath]
    proc.running = true
  }

  function next() {
    if (busy || pending.length === 0) return
    var item = pending[0]
    pending = pending.slice(1)
    start(item.req, item.done)
  }

  Process {
    id: proc
    property string payload: ""
    property var done: null
    property string responseText: ""
    property string errorText: ""
    stdinEnabled: true
    onStarted: {
      write(payload + "\n")
      payload = ""
    }
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: proc.responseText = text
    }
    stderr: StdioCollector {
      waitForEnd: true
      onStreamFinished: proc.errorText = text
    }
    onExited: function(code, status) {
      var reply = null
      var text = proc.responseText.trim()
      // Only the last line is the reply (earlier lines may be progress events).
      var lines = text.split("\n")
      var last = lines.length ? lines[lines.length - 1] : ""
      try {
        reply = last ? JSON.parse(last) : null
      } catch (e) {
        reply = null
      }
      if (!reply) {
        var msg = proc.errorText.trim()
        if (msg.length > 400) msg = msg.slice(-400)
        reply = {ok: false, error: {code: "helper_failed",
                                    message: code === 0 ? "The backend returned no valid reply." : ("Backend failed (exit " + code + "): " + (msg || "no output"))}}
      }
      var cb = proc.done
      proc.done = null
      proc.responseText = ""
      proc.errorText = ""
      root.busy = false
      if (!reply.ok) {
        root.lastError = reply.error ? reply.error.message : "unknown error"
        root.failed(root.lastError)
      }
      if (cb) {
        try { cb(reply) } catch (e) { console.warn("omababel: callback threw", e) }
      }
      root.next()
    }
  }
}
