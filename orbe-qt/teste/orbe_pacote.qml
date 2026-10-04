import QtQuick
import "../comum"

// OrbeConteudo com um pacote de camadas e com um PNG solto, pensando.
Rectangle {
    id: folha
    property url dir
    property var manifesto: ({})
    width: 444; height: 148 * 2 + 20
    color: "#1d2324"
    Column {
        spacing: 20
        OrbeConteudo {
            id: a
            skin: "exemplo"; pacoteDir: folha.dir; pacoteManifesto: folha.manifesto
            Component.onCompleted: { comando("show thinking"); comando("line Pacote de camadas no orbe.") }
        }
        OrbeConteudo {
            id: b
            skin: "solto"; vidro: true
            pacoteDir: folha.dir + "/.."
            pacoteManifesto: ({ quadro: 1024, camadas: [{ arquivo: "solto.png", anim: "pulsar" }] })
            Component.onCompleted: comando("show speaking")
        }
    }
    function passo(dt) { a.passo(dt); b.passo(dt) }
}
