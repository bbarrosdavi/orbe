import QtQuick
import "../comum"

// Conferência pixel a pixel das skins de imagem: a figura na pose desenhada
// (repouso), a 1:1 com o recorte (R = RIMG), sem a cor nem o glitch do
// pos.frag. Sai o passe da máscara (r = traço, g = massa), que repouso.py
// compara com o atlas.
Item {
    id: f
    property string skin: "olho"
    property real rimg: 270
    width: 520; height: 649
    Figura {
        id: fig
        anchors.fill: parent
        skin: f.skin
        glitch: false
        repouso: true
        raioFixo: f.rimg
        mix: ({ idle: 0, listening: 1, thinking: 0, tools: 0, speaking: 0 })
        layer.enabled: false
    }
    function passo(dt) { fig.avancar(dt) }
}
