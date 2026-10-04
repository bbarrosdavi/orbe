import QtQuick
import QtQuick.Controls.Basic
import "."

// Lista de escolha na linha (o ComboRow do libadwaita), com busca opcional.
Linha {
    id: r
    property var itens: []          // [{id, nome}]
    property string valor: ""
    property bool busca: false
    signal escolhido(string id)
    // fora da lista, vale o primeiro item, como o _combo_set do GTK
    readonly property int indice: {
        for (var i = 0; i < itens.length; i++)
            if (itens[i].id === valor) return i
        return itens.length ? 0 : -1
    }
    readonly property string efetivo: indice >= 0 ? itens[indice].id : ""
    property alias extra: mais.data           // botões depois da seta (ex.: consultar)
    clicavel: true
    onClicado: pop.open()

    Text {
        anchors.verticalCenter: parent.verticalCenter
        text: r.indice >= 0 ? r.itens[r.indice].nome : ""
        color: Estilo.texto
        font.pointSize: 11
        elide: Text.ElideMiddle
        width: Math.min(implicitWidth, r.width * 0.46)
    }
    Icone {
        anchors.verticalCenter: parent.verticalCenter
        nome: "pan-down-symbolic"
    }
    Row {
        id: mais
        anchors.verticalCenter: parent.verticalCenter
        spacing: 6
    }

    Popup {
        id: pop
        parent: r
        width: Math.min(340, r.width - 16)
        x: r.width - width - 8
        y: r.height - 6
        height: Math.min(360, cabeca.height + lista.contentHeight + 14)
        margins: 8
        padding: 6
        modal: false
        focus: true
        background: Rectangle {
            color: Estilo.popover
            radius: 12
            border.color: Estilo.alfa(Estilo.accent, 0.18)
        }
        onOpened: {
            filtro.text = ""
            if (r.busca) filtro.forceActiveFocus()
            lista.positionViewAtIndex(Math.max(0, r.indice), ListView.Center)
        }
        readonly property var filtrados: {
            var f = filtro.text.toLowerCase()
            return r.itens.filter(function (it) { return !f || it.nome.toLowerCase().indexOf(f) >= 0 })
        }
        contentItem: Column {
            spacing: 4
            Item {
                id: cabeca
                width: parent.width
                height: r.busca ? 34 : 0
                visible: r.busca
                Rectangle {
                    anchors.fill: parent
                    radius: 8
                    color: Estilo.alfa(Estilo.texto, 0.06)
                }
                Icone {
                    x: 9
                    anchors.verticalCenter: parent.verticalCenter
                    nome: "system-search-symbolic"
                    opacity: 0.6
                }
                TextInput {
                    id: filtro
                    x: 32
                    width: parent.width - 40
                    anchors.verticalCenter: parent.verticalCenter
                    color: Estilo.texto
                    font.pointSize: 11
                    clip: true
                }
            }
            ListView {
                id: lista
                width: parent.width
                height: pop.height - cabeca.height - 16
                clip: true
                model: pop.filtrados
                boundsBehavior: Flickable.StopAtBounds
                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                delegate: Rectangle {
                    width: lista.width
                    height: 34
                    radius: 8
                    color: Estilo.alfa(Estilo.accent, hv.hovered ? 0.10 : 0)
                    HoverHandler { id: hv }
                    Text {
                        x: 10
                        width: parent.width - 40
                        anchors.verticalCenter: parent.verticalCenter
                        text: modelData.nome
                        color: Estilo.texto
                        font.pointSize: 11
                        elide: Text.ElideRight
                    }
                    Icone {
                        anchors.right: parent.right
                        anchors.rightMargin: 8
                        anchors.verticalCenter: parent.verticalCenter
                        nome: "object-select-symbolic"
                        visible: modelData.id === r.efetivo
                    }
                    TapHandler {
                        onTapped: {
                            r.valor = modelData.id
                            r.escolhido(modelData.id)
                            pop.close()
                        }
                    }
                }
            }
        }
    }
}
