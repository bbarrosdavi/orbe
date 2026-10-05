import QtQuick
import QtQuick.Shapes
import "."

// A sombra atrás do orbe em miniatura: o degradê (1 - r²)² do pos.frag na
// cor do fundo, com a opacidade do centro em [alfa]. O aro em accent deixa o
// botão à vista quando a sombra é escura sobre o vidro escuro.
Item {
    id: d
    property real alfa: 0.45
    function curva(r) { var q = 1 - r * r; return q * q }

    Shape {
        anchors.fill: parent
        preferredRendererType: Shape.CurveRenderer
        ShapePath {
            strokeWidth: 1.5
            strokeColor: Estilo.alfa(Estilo.accent, 0.8)
            fillGradient: RadialGradient {
                centerX: d.width / 2; centerY: d.height / 2
                focalX: centerX; focalY: centerY
                centerRadius: d.width / 2
                GradientStop { position: 0.0; color: Estilo.alfa(Estilo.fundo, d.alfa) }
                GradientStop { position: 0.25; color: Estilo.alfa(Estilo.fundo, d.alfa * d.curva(0.25)) }
                GradientStop { position: 0.5; color: Estilo.alfa(Estilo.fundo, d.alfa * d.curva(0.5)) }
                GradientStop { position: 0.75; color: Estilo.alfa(Estilo.fundo, d.alfa * d.curva(0.75)) }
                GradientStop { position: 1.0; color: Estilo.alfa(Estilo.fundo, 0) }
            }
            PathAngleArc {
                centerX: d.width / 2; centerY: d.height / 2
                radiusX: d.width / 2 - 1; radiusY: d.height / 2 - 1
                startAngle: 0; sweepAngle: 360
            }
        }
    }
}
