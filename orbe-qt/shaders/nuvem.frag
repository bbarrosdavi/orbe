#version 440
// Uma nuvem macia em volta de uma caixa, cheia no meio e esmaecendo devagar
// para fora, e zerada antes da borda do item. Dois usos:
// - a sombra atrás do texto do raciocínio, no tom do fundo em volta do bloco
//   de linhas (uma faixa por linha parecia marca-texto; a janela termina rente
//   ao texto e um borrão comum seria cortado na borda dela com uma quina dura);
// - o brilho atrás das luas com sessão ativa (caixa de um ponto: vira um halo).
layout(location = 0) in vec2 qt_TexCoord0;
layout(location = 0) out vec4 fragColor;
layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    vec2 tam;        // tamanho do item, em px
    vec4 caixa;      // o bloco de texto: x0, y0, x1, y1 em px
    vec4 cor;        // rgb do fundo do tema; a = a intensidade
    vec4 forma;      // x = largura do esmaecimento (px), y = raio dos cantos, z = margem da janela (px),
                     // w = 1: perfil aberto (halo); 0: de sino (sombra do texto)
};

// distância até uma caixa de cantos arredondados (negativa dentro)
float caixaArredondada(vec2 p, vec2 c, vec2 meia, float r) {
    vec2 q = abs(p - c) - meia + r;
    return length(max(q, 0.0)) + min(max(q.x, q.y), 0.0) - r;
}

void main() {
    vec2 p = qt_TexCoord0 * tam;
    vec2 c = 0.5 * (caixa.xy + caixa.zw);
    vec2 meia = max(0.5 * (caixa.zw - caixa.xy), vec2(1.0));
    float d = caixaArredondada(p, c, meia, min(forma.y, min(meia.x, meia.y)));
    // começa a esmaecer um pouco por dentro do bloco e some a forma.x por fora:
    // perfil de sino, sem degrau
    float u = clamp((d + 0.3 * forma.x) / (1.3 * forma.x), 0.0, 1.0);
    float a = 1.0 - u * u * (3.0 - 2.0 * u);
    if (forma.w < 0.5) a *= a;
    // perto da borda da janela, vai a zero
    float borda = min(min(p.x, tam.x - p.x), min(p.y, tam.y - p.y));
    a *= smoothstep(0.0, forma.z, borda);
    fragColor = vec4(cor.rgb, 1.0) * (cor.a * a * qt_Opacity);
}
