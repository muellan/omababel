pragma Singleton
import QtQuick
QtObject {
  property string shellDir: ""
  function env(name) { return "" }
  function execDetached(cmd) {}
}
