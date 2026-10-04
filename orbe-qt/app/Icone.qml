import QtQuick
import "."

// Ícone simbólico do tema, pintado na cor pedida (image://icone na ponte).
Image {
    property string nome
    property color cor: Estilo.texto
    property int lado: 16
    width: lado
    height: lado
    sourceSize: Qt.size(lado * 2, lado * 2)
    smooth: true
    // sem "#": o fragmento da URL não chega ao provedor
    source: nome ? "image://icone/" + nome + "?" + cor.toString().slice(1) : ""
}
