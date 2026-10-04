#version 440
// Camada "olhar" de um pacote de skin: a imagem deslocada na direção do
// olhar, recortada pelo alfa da máscara (o branco do olho).

layout(location = 0) in vec2 qt_TexCoord0;
layout(location = 0) out vec4 fragColor;

layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    vec2 desloc;        // deslocamento em fração do item
    float usaMascara;   // 0 = sem máscara
};
layout(binding = 1) uniform sampler2D source;
layout(binding = 2) uniform sampler2D mascara;

void main() {
    vec2 uv = qt_TexCoord0 - desloc;
    vec4 c = (uv.x < 0.0 || uv.y < 0.0 || uv.x > 1.0 || uv.y > 1.0) ? vec4(0.0) : texture(source, uv);
    float m = usaMascara > 0.5 ? texture(mascara, qt_TexCoord0).a : 1.0;
    fragColor = c * m * qt_Opacity;
}
