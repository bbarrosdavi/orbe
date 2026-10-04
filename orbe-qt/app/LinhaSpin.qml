import QtQuick
import "."

Linha {
    id: r
    property real de: 0
    property real ate: 100
    property real passo: 1
    property int casas: 0
    property real valor: 0
    function ajustar(v) {
        if (isNaN(v)) v = valor
        v = Math.min(ate, Math.max(de, de + Math.round((v - de) / passo) * passo))
        valor = parseFloat(v.toFixed(casas))
        campo.text = valor.toFixed(casas)
    }
    onValorChanged: if (!campo.activeFocus) campo.text = valor.toFixed(casas)
    TextInput {
        id: campo
        anchors.verticalCenter: parent.verticalCenter
        width: 56
        horizontalAlignment: TextInput.AlignRight
        color: Estilo.texto
        selectionColor: Estilo.alfa(Estilo.accent, 0.4)
        font.pointSize: 11
        selectByMouse: true
        text: r.valor.toFixed(r.casas)
        onEditingFinished: r.ajustar(parseFloat(text.replace(",", ".")))
    }
    BotaoIcone {
        icone: "list-remove-symbolic"
        fundo: true
        ativo: r.valor > r.de
        onClicado: r.ajustar(r.valor - r.passo)
    }
    BotaoIcone {
        icone: "list-add-symbolic"
        fundo: true
        ativo: r.valor < r.ate
        onClicado: r.ajustar(r.valor + r.passo)
    }
}
