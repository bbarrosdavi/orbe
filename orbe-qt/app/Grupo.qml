import QtQuick
import "."

// Grupo de preferências: título, descrição e as linhas numa caixa arredondada.
Column {
    id: g
    property string titulo
    property string descricao
    property bool caixa: true
    default property alias conteudo: lista.data
    width: parent ? parent.width : 300
    spacing: 8

    Text {
        visible: g.titulo !== ""
        text: g.titulo
        color: Estilo.texto
        font.pointSize: 11
        font.bold: true
    }
    Text {
        visible: g.descricao !== ""
        width: parent.width
        text: g.descricao
        color: Estilo.texto
        opacity: 0.55
        font.pointSize: 11
        wrapMode: Text.Wrap
    }
    Rectangle {
        width: parent.width
        height: lista.height
        radius: 12
        color: g.caixa ? Estilo.alfa(Estilo.vista, 0.30) : "transparent"
        border.width: g.caixa ? 1 : 0
        border.color: Estilo.alfa(Estilo.accent, 0.16)
        Column {
            id: lista
            width: parent.width
        }
    }
}
