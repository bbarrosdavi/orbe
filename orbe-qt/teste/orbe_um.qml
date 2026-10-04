import QtQuick
import "../comum"
// Um orbe só, para medir custo por quadro de cada skin.
Rectangle {
    id: f
    width: 444; height: 148
    color: "#1d2324"
    property string skin: "serafim_gravura"
    property string estado: "speaking"
    property bool vidro: false
    property real t: 0
    OrbeConteudo {
        id: o
        skin: f.skin
        vidro: f.vidro
        Component.onCompleted: { o.comando("show " + f.estado); o.faseT = 1 }
    }
    function passo(dt) {
        t += dt
        var syl = Math.abs(Math.sin(t * 4.6)) * (0.62 + 0.38 * Math.sin(t * 1.3))
        if (o.estado === "speaking") o.comando("level " + (0.12 + 0.85 * syl).toFixed(3) + " " + (0.5 + 0.42 * Math.sin(t * 0.8)).toFixed(3))
        o.passo(dt)
    }
}
