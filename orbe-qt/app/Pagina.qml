import QtQuick
import QtQuick.Controls.Basic
import "."

// Página rolável de grupos (o PreferencesPage do libadwaita).
Flickable {
    id: f
    default property alias conteudo: col.data
    clip: true
    contentWidth: width
    contentHeight: col.height + 32
    boundsBehavior: Flickable.StopAtBounds
    ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
    Column {
        id: col
        x: 20
        y: 12
        width: f.width - 40
        spacing: 24
    }
}
