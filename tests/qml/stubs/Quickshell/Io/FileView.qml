import QtQuick
// Test stub of Quickshell.Io.FileView: never loads anything.
QtObject {
  property string path: ""
  property bool watchChanges: false
  property bool printErrors: true
  property bool blockLoading: false
  property bool preload: true
  property bool loaded: false
  signal loaded()
  signal loadFailed()
  signal fileChanged()
  signal saved()
  function text() { return "" }
  function data() { return "" }
  function reload() {}
  function waitForJob() {}
  function setText(t) {}
}
