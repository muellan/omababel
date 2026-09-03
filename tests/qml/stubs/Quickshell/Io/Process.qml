import QtQuick
// Test stub of Quickshell.Io.Process: never runs anything.
QtObject {
  property var command: []
  property bool running: false
  property bool stdinEnabled: false
  property bool manageLifetime: true
  property bool clearEnvironment: false
  property var environment: ({})
  property string workingDirectory: ""
  property var stdout: null
  property var stderr: null
  property int processId: 0
  signal started()
  signal exited(int exitCode, int exitStatus)
  function write(data) {}
  function signal(sig) {}
  function startDetached() {}
}
