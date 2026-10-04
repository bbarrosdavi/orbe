pragma Singleton
import QtQuick

// Cores do matugen (dank-colors.css), lidas pela ponte em Python.
QtObject {
    readonly property var t: ponte.tema
    readonly property color accent: t.accent_bg_color
    readonly property color accentFg: t.accent_fg_color
    readonly property color fundo: t.window_bg_color
    readonly property color texto: t.window_fg_color
    readonly property color vista: t.view_bg_color
    readonly property color popover: t.popover_bg_color
    readonly property color anel: t.anel || t.accent_bg_color

    function alfa(c, a) {
        var q = Qt.color(c)
        return Qt.rgba(q.r, q.g, q.b, a)
    }
}
